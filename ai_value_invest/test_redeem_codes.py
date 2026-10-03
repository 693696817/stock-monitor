import os
import sys
import json
import random
import threading
import datetime
import urllib.request

import db
import auth
import settings

BASE = "http://127.0.0.1:8015"
PASS = 0
FAIL = 0

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + "  " + str(detail))

def _get(path, cookie=None, timeout=60):
    op = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    if cookie:
        op.addheaders = [("Cookie", cookie)]
    r = op.open(BASE + path, timeout=timeout)
    return r.status, r.read().decode("utf-8", "ignore")

def _post(path, payload, cookie=None, timeout=60):
    op = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        r = op.open(req, timeout=timeout)
        return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")

def make_user():
    for _ in range(5):
        phone = "139%08d" % random.randint(10000000, 99999999)
        try:
            return auth.create_user(phone, "Tes@123456", None, "redeem_tester",
                                    require_invite=False)
        except Exception:
            continue
    raise RuntimeError("创建测试用户失败")

def main():
    db.ensure_redeem_codes_table()
    user = make_user()
    uid = user["id"]
    test_batches = []

    try:
        print("\n[A] 数据层：生成 / 列表 / 统计 / 作废")
        batch1, codes1 = db.create_redeem_codes(
            "vip1", "VIP-1 会员", "月卡", 1, 30, 0, 0, 5, None, uid, "TEST-A")
        test_batches.append(batch1)
        check("生成 5 张码", len(codes1) == 5, codes1)
        check("码互不重复", len(set(codes1)) == 5, codes1)
        check("码长 16 位且无易混字符",
              all(len(c) == 16 and all(ch not in "IO01" for ch in c) for c in codes1),
              codes1[:2])

        total, rows = db.list_redeem_codes(page=1, per_page=100, batch_no=batch1)
        check("按批次可查到 5 条", total == 5 and len(rows) == 5, (total, len(rows)))

        _t, rows_unused = db.list_redeem_codes(page=1, per_page=100,
                                               batch_no=batch1, status=0)
        check("状态筛选（未使用）命中 5 条", len(rows_unused) == 5, len(rows_unused))

        st = db.redeem_code_stats()
        check("统计返回四个键且总数自洽",
              set(st) == {"total", "unused", "used", "voided"}
              and st["total"] == st["unused"] + st["used"] + st["voided"], st)

        n1 = db.void_redeem_codes([codes1[0]])
        n2 = db.void_redeem_codes([codes1[0]])
        check("未使用的码可作废", n1 == 1, n1)
        check("已作废的码不会重复作废", n2 == 0, n2)

        b0, d0 = auth.get_bonus(uid)
        db.add_user_bonus(uid, normal=3, deep=1)
        b1, d1 = auth.get_bonus(uid)
        check("原子加次数：普通 +3", b1 - b0 == 3, (b0, b1))
        check("原子加次数：深度 +1", d1 - d0 == 1, (d0, d1))

        print("\n[B] 核销状态机：正常 / 重复 / 不存在 / 作废 / 过期 / 次数包")
        _b, vip_codes = db.create_redeem_codes(
            "vip1", "VIP-1 会员", "月卡", 1, 30, 0, 0, 1, None, uid, "TEST-B")
        test_batches.append(_b)
        ok, msg, info = auth.redeem_code(uid, vip_codes[0])
        check("正常兑换成功", ok is True, msg)
        check("兑换后会员等级 = VIP-1",
              (auth.get_user_by_id(uid) or {}).get("membership_level") == 1,
              (auth.get_user_by_id(uid) or {}).get("membership_level"))
        exp = (auth.get_user_by_id(uid) or {}).get("membership_expiry")
        check("兑换后有效期被写入", exp is not None, exp)

        ok2, msg2, _ = auth.redeem_code(uid, vip_codes[0])
        check("同一个码不能兑换两次", ok2 is False and "已被使用" in msg2, msg2)

        ok3, msg3, _ = auth.redeem_code(uid, "ZZZZZZZZZZZZZZZZ")
        check("不存在的码被拒绝", ok3 is False and "不存在" in msg3, msg3)

        _b2, void_codes = db.create_redeem_codes(
            "vip1", "VIP-1 会员", "月卡", 1, 30, 0, 0, 1, None, uid, "TEST-B2")
        test_batches.append(_b2)
        db.void_redeem_codes(void_codes)
        ok4, msg4, _ = auth.redeem_code(uid, void_codes[0])
        check("已作废的码被拒绝", ok4 is False and "作废" in msg4, msg4)

        past = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        _b3, exp_codes = db.create_redeem_codes(
            "vip1", "VIP-1 会员", "月卡", 1, 30, 0, 0, 1, past, uid, "TEST-B3")
        test_batches.append(_b3)
        ok5, msg5, _ = auth.redeem_code(uid, exp_codes[0])
        check("过期的码被拒绝", ok5 is False and "过期" in msg5, msg5)

        bn0, bd0 = auth.get_bonus(uid)
        _b4, payg_codes = db.create_redeem_codes(
            "payg", "按量付费包", "普通分析20次包", 0, 0, 20, 0, 1, None, uid, "TEST-B4")
        test_batches.append(_b4)
        ok6, msg6, info6 = auth.redeem_code(uid, payg_codes[0])
        bn1, bd1 = auth.get_bonus(uid)
        check("次数包兑换成功", ok6 is True, msg6)
        check("次数包普通 +20", bn1 - bn0 == 20, (bn0, bn1))
        check("次数包不改会员天数", (info6 or {}).get("days") == 0, info6)

        _b5, norm_codes = db.create_redeem_codes(
            "payg", "按量付费包", "深度分析10次包", 0, 0, 0, 10, 1, None, uid, "TEST-B5")
        test_batches.append(_b5)
        pretty = db.format_redeem_code(norm_codes[0]).lower()
        ok7, msg7, _ = auth.redeem_code(uid, " " + pretty + " ")
        check("小写 + 横线 + 空格可正常兑换", ok7 is True, msg7)

        ok8, msg8, _ = auth.redeem_code(uid, "非法码!!")
        check("含非法字符的码被拒绝", ok8 is False and "格式" in msg8, msg8)

        print("\n[C] 并发安全：同一个码 10 线程同时兑换，只能成功 1 次")
        _b6, race_codes = db.create_redeem_codes(
            "vip2", "VIP-2 尊享版", "年卡", 2, 365, 0, 0, 1, None, uid, "TEST-C")
        test_batches.append(_b6)
        race_code = race_codes[0]
        results = []
        lock = threading.Lock()

        def worker():
            ok_r, _m, _i = auth.redeem_code(uid, race_code)
            with lock:
                results.append(ok_r)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check("并发 10 次只有 1 次成功", results.count(True) == 1, results)
        check("并发后码状态为已使用",
              (db.list_redeem_codes(page=1, per_page=1, kw=race_code)[1] or
               [{}])[0].get("status") == 1)

        print("\n[D] HTTP：服务端权威 + 鉴权（需要 8015 在跑）")
        try:
            _get("/login")
        except Exception as e:
            print("  SKIP 服务未运行（%s），跳过 HTTP 段" % type(e).__name__)
        else:
            admin_cookie = "geek_session=" + auth._sign({"uid": 1})
            user_cookie = "geek_session=" + auth._sign({"uid": uid})

            code, body = _post("/api/admin/redeem/generate",
                               {"plan_key": "vip1", "sku_index": 0, "count": 2,
                                "level": 99, "days": 99999},
                               cookie=admin_cookie)
            if code == 200:
                j = json.loads(body)
                spec = j.get("spec") or {}
                check("月卡推导为 VIP-1 / 30 天",
                      spec.get("level") == 1 and spec.get("days") == 30, spec)
                check("前端传入的 level/days 被服务端忽略",
                      spec.get("level") != 99 and spec.get("days") != 99999, spec)
                test_batches.append(j.get("batch_no"))
            else:
                check("管理员生成接口返回 200", False, (code, body[:120]))

            code, body = _post("/api/admin/redeem/generate",
                               {"plan_key": "vip2", "sku_index": 2, "count": 1},
                               cookie=admin_cookie)
            j = json.loads(body) if code == 200 else {}
            check("年卡推导为 VIP-2 / 365 天",
                  (j.get("spec") or {}).get("days") == 365, (code, j.get("spec")))
            if code == 200:
                test_batches.append(j.get("batch_no"))

            code, body = _post("/api/admin/redeem/generate",
                               {"plan_key": "payg", "sku_index": 0, "count": 1},
                               cookie=admin_cookie)
            j = json.loads(body) if code == 200 else {}
            check("体验包推导为 10 普通 + 2 深度",
                  (j.get("spec") or {}).get("bonus_normal") == 10
                  and (j.get("spec") or {}).get("bonus_deep") == 2, (code, j.get("spec")))
            if code == 200:
                test_batches.append(j.get("batch_no"))

            code, body = _get("/api/admin/redeem/preview?plan_key=payg&sku_index=1",
                              cookie=admin_cookie)
            j = json.loads(body) if code == 200 else {}
            check("按量包越界 sku 回落到体验包（不 500）",
                  (j.get("spec") or {}).get("bonus_normal") == 10
                  and (j.get("spec") or {}).get("bonus_deep") == 2, (code, j.get("spec")))

            code, body = _get("/api/admin/redeem/preview?plan_key=vip1&sku_index=2",
                              cookie=admin_cookie)
            j = json.loads(body) if code == 200 else {}
            check("订阅卡越界 sku 回落到年卡 365 天",
                  (j.get("spec") or {}).get("days") == 365, (code, j.get("spec")))

            code, _ = _post("/api/admin/redeem/generate",
                            {"plan_key": "free", "sku_index": 0, "count": 1},
                            cookie=admin_cookie)
            check("免费版拒绝发码（400）", code == 400, code)

            code, _ = _post("/api/admin/redeem/generate",
                            {"plan_key": "__evil__", "sku_index": 0, "count": 1},
                            cookie=admin_cookie)
            check("伪造套餐拒绝发码（400）", code == 400, code)

            code, _ = _post("/api/admin/redeem/generate",
                            {"plan_key": "vip1", "sku_index": 0, "count": 1},
                            cookie=user_cookie)
            check("非管理员调用生成被拒（非 200）", code != 200, code)

            code, _ = _post("/api/admin/redeem/generate",
                            {"plan_key": "vip1", "sku_index": 0, "count": 1})
            check("未登录调用生成被拒（401/403）", code in (401, 403), code)

            code, _ = _post("/api/redeem", {"code": "AAAAAAAAAAAAAAAA"})
            check("未登录核销被拒（401）", code == 401, code)

            _b7, http_codes = db.create_redeem_codes(
                "payg", "按量付费包", "普通分析20次包", 0, 0, 20, 0, 1, None, uid, "TEST-D")
            test_batches.append(_b7)
            code, body = _post("/api/redeem", {"code": db.format_redeem_code(http_codes[0])},
                               cookie=user_cookie)
            j = json.loads(body) if code == 200 else {}
            check("登录用户 HTTP 核销成功", j.get("status") == "success", (code, body[:120]))

            code, _ = _get("/api/admin/redeem/export?status=0", cookie=admin_cookie)
            check("管理员导出 CSV 返回 200", code == 200, code)

            code, _ = _get("/admin/redeem", cookie=admin_cookie)
            check("后台兑换码页返回 200", code == 200, code)
    finally:
        try:
            auth.delete_user(uid)
        except Exception as e:
            print("  ⚠️ 测试用户清理失败: %s" % e)
        try:
            conn = db.get_conn()
            try:
                with conn.cursor() as cur:
                    for b in test_batches:
                        if b:
                            cur.execute("DELETE FROM redeem_codes WHERE batch_no=%s", (b,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print("  ⚠️ 测试码清理失败: %s" % e)

    print("\n---- PASS %d / FAIL %d" % (PASS, FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
