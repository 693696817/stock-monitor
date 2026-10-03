import sys
import json
import random
import datetime
import urllib.request
import urllib.error

import db
import auth

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + "  " + str(detail))

def make_user(tag):
    for _ in range(6):
        phone = "131%08d" % random.randint(10000000, 99999999)
        try:
            return auth.create_user(phone, "Tes@123456", None, tag, require_invite=False)
        except Exception:
            continue
    raise RuntimeError("创建测试用户失败")

def set_membership(uid, level, expiry):
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET membership_level=%s, membership_expiry=%s WHERE id=%s",
                (level, expiry, uid))
        conn.commit()
    finally:
        conn.close()

def get_membership(uid):
    u = auth.get_user_by_id(uid)
    return int(u["membership_level"] or 0), str(u["membership_expiry"] or "")

def make_code(plan_key, level, days, bn=0, bd=0, plan_name="P", sku="S", expire_at=None):
    b, codes = db.create_redeem_codes(plan_key, plan_name, sku, level, days, bn, bd,
                                      1, expire_at, 1, "test")
    return b, codes[0]

def cleanup(uids, batches=()):
    for uid in uids:
        try:
            conn = db.get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM analysis_records WHERE user_id=%s", (uid,))
                    cur.execute("DELETE FROM membership_orders WHERE user_id=%s", (uid,))
                    cur.execute("DELETE FROM notification_reads WHERE user_id=%s", (uid,))
                    cur.execute("DELETE FROM notifications WHERE user_id=%s", (uid,))
                conn.commit()
            finally:
                conn.close()
            auth.delete_user(uid)
        except Exception as e:
            print("  ⚠️ 清理失败 uid=%s: %s" % (uid, e))
    for b in batches:
        try:
            conn = db.get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM redeem_codes WHERE batch_no=%s", (b,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

def test_membership():
    print("\n[A] 会员续费与到期")
    today = datetime.date.today()
    batches = []
    uids = []

    try:
        u = make_user("m1")
        uids.append(u["id"])
        uid = u["id"]

        set_membership(uid, 2, (today - datetime.timedelta(days=10)).isoformat())
        b, code = make_code("vip1", 1, 30)
        batches.append(b)
        ok, msg, info = auth.redeem_code(uid, code)
        lvl, exp = get_membership(uid)
        check("过期后买 VIP-1 → 等级为 1（不被历史 VIP-2 升格）", lvl == 1, (lvl, exp))
        check("过期后续费从今天起算", exp == (today + datetime.timedelta(days=30)).isoformat(), exp)
        check("回显带新到期日", info.get("new_expiry") == exp, info.get("new_expiry"))

        first_exp = exp
        b2, code2 = make_code("vip1", 1, 30)
        batches.append(b2)
        auth.redeem_code(uid, code2)
        lvl2, exp2 = get_membership(uid)
        want = (datetime.date.fromisoformat(first_exp) + datetime.timedelta(days=30)).isoformat()
        check("未过期续费叠加到原到期日之后", exp2 == want, (exp2, want))

        b3, code3 = make_code("vip2", 2, 30)
        batches.append(b3)
        _ok, _m, info3 = auth.redeem_code(uid, code3)
        lvl3, exp3 = get_membership(uid)
        check("未过期兑换更高档 → 升级为 VIP-2", lvl3 == 2, lvl3)
        check("升级时天数同样叠加", exp3 == (datetime.date.fromisoformat(exp2)
                                       + datetime.timedelta(days=30)).isoformat(), exp3)
        check("回显标记 level_upgraded", info3.get("level_upgraded") is True, info3)

        set_membership(uid, 2, (today - datetime.timedelta(days=1)).isoformat())
        tier = auth.get_effective_tier(auth.get_user_by_id(uid))
        check("过期会员的生效档位回落为免费版", tier["level"] == 0, tier["level"])
        check("过期会员 is_vip_active 为 False",
              auth.is_vip_active(auth.get_user_by_id(uid)) is False)
    finally:
        cleanup(uids, batches)

def test_notifications():
    print("\n[B] 站内通知")
    db.ensure_notifications_table()
    uids = []
    nids = []
    try:
        a = make_user("n1")
        b = make_user("n2")
        uids = [a["id"], b["id"]]
        ua, ub = a["id"], b["id"]

        n1 = db.create_notification(None, "system", "全站广播", "内容", level="info")
        nids.append(n1)
        check("全站广播对用户 A 可见",
              any(r["id"] == n1 for r in db.list_user_notifications(ua)))
        check("全站广播对用户 B 可见",
              any(r["id"] == n1 for r in db.list_user_notifications(ub)))

        db.mark_notification_read(ua, n1)
        ra = [r for r in db.list_user_notifications(ua) if r["id"] == n1]
        rb = [r for r in db.list_user_notifications(ub) if r["id"] == n1]
        check("A 已读后 A 侧 is_read=1", ra and int(ra[0]["is_read"]) == 1, ra)
        check("A 已读不影响 B（B 仍未读）", rb and int(rb[0]["is_read"]) == 0, rb)
        check("A 未读数减少、B 未读数不变",
              db.count_unread_notifications(ua) < db.count_unread_notifications(ub),
              (db.count_unread_notifications(ua), db.count_unread_notifications(ub)))

        n2 = db.create_notification(ua, "redeem", "专属消息", "给 A 的")
        nids.append(n2)
        check("专属消息对本人可见",
              any(r["id"] == n2 for r in db.list_user_notifications(ua)))
        check("专属消息对他人不可见",
              not any(r["id"] == n2 for r in db.list_user_notifications(ub)))
        check("notification_visible 校验生效",
              db.notification_visible(n2, ua) and not db.notification_visible(n2, ub))

        n3 = db.create_notification(ua, "membership_expire", "到期提醒",
                                    dedup_key="expire:1:2026-01-01:7")
        n4 = db.create_notification(ua, "membership_expire", "到期提醒（重复）",
                                    dedup_key="expire:1:2026-01-01:7")
        for n in (n3, n4):
            if n:
                nids.append(n)
        check("相同 dedup_key 只入库一条", n3 is not None and n4 is None, (n3, n4))

        past = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        n5 = db.create_notification(ua, "system", "过期通知", level="info", expire_at=past)
        nids.append(n5)
        check("过期通知不出现在列表",
              not any(r["id"] == n5 for r in db.list_user_notifications(ua)))
        check("过期通知不计入未读",
              db.count_unread_notifications(ua) ==
              len([r for r in db.list_user_notifications(ua) if not int(r["is_read"])]),
              db.count_unread_notifications(ua))

        db.mark_all_notifications_read(ub)
        check("一键已读后 B 未读归零", db.count_unread_notifications(ub) == 0,
              db.count_unread_notifications(ub))
    finally:
        try:
            conn = db.get_conn()
            try:
                with conn.cursor() as cur:
                    for n in nids:
                        cur.execute("DELETE FROM notification_reads WHERE notification_id=%s", (n,))
                        cur.execute("DELETE FROM notifications WHERE id=%s", (n,))
                    cur.execute("DELETE FROM notifications WHERE dedup_key LIKE 'expire:1:%'")
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
        cleanup(uids)

def test_expiry_scan():
    print("\n[C] 会员到期扫描")
    today = datetime.date.today()
    uids = []
    try:
        u = make_user("s1")
        uid = u["id"]
        uids.append(uid)
        set_membership(uid, 1, (today + datetime.timedelta(days=3)).isoformat())
        c1, s1 = db.scan_membership_expiry()
        check("命中 3 天后到期的会员", s1 >= 1 and c1 >= 1, (c1, s1))
        c2, _s2 = db.scan_membership_expiry()
        check("重复扫描不重复推送（dedup 生效）", c2 == 0, c2)
        set_membership(uid, 1, (today + datetime.timedelta(days=7)).isoformat())
        c3, _s3 = db.scan_membership_expiry()
        check("到期日变化后可再次提醒", c3 >= 1, c3)
    finally:
        cleanup(uids)
        conn = db.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM notifications WHERE type LIKE 'membership_expir%'")
            conn.commit()
        finally:
            conn.close()

def test_upgrade_backdoor():
    print("\n[D] HTTP：直接开通后门已堵死（需要 8015 在跑）")
    uids = []
    try:
        u = make_user("bk")
        uid = u["id"]
        uids.append(uid)
        set_membership(uid, 0, None)
        req = urllib.request.Request(
            "http://127.0.0.1:8015/api/membership/upgrade",
            data=json.dumps({"plan": "vip2"}).encode(),
            headers={"Content-Type": "application/json",
                     "Cookie": "geek_session=" + auth._sign({"uid": uid})},
        )
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            r = op.open(req, timeout=30)
            code = r.status
            body = r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            code = e.code
            body = e.read().decode("utf-8", "ignore")
        except Exception as e:
            check("服务可达", False, e)
            return
        check("直接开通接口被拒绝（403）", code == 403, (code, body[:120]))
        lvl, _exp = get_membership(uid)
        check("调用后会员等级未被提升", lvl == 0, lvl)
    finally:
        cleanup(uids)

def test_notification_api():
    print("\n[E] HTTP：通知接口与越权防护（需要 8015 在跑）")
    uids = []
    nids = []
    try:
        a = make_user("na")
        b = make_user("nb")
        uids = [a["id"], b["id"]]
        ua, ub = a["id"], b["id"]
        secret = db.create_notification(ua, "system", "给 A 的私密消息")
        nids.append(secret)

        def post(path, payload, uid):
            req = urllib.request.Request(
                "http://127.0.0.1:8015" + path,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "Cookie": "geek_session=" + auth._sign({"uid": uid})},
            )
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                r = op.open(req, timeout=30)
                return r.status, r.read().decode("utf-8", "ignore")
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8", "ignore")

        code, body = post("/api/notifications/read", {"id": secret}, ub)
        check("标记他人私密消息已读被拒（404）", code == 404, (code, body[:100]))

        code, body = post("/api/notifications/read", {"id": secret}, ua)
        check("标记自己的消息已读成功", code == 200, (code, body[:100]))

        req = urllib.request.Request(
            "http://127.0.0.1:8015/api/notifications",
            headers={"Content-Type": "application/json"})
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            r = op.open(req, timeout=30)
            code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        check("未登录读取通知被拒（401）", code == 401, code)
    finally:
        try:
            conn = db.get_conn()
            try:
                with conn.cursor() as cur:
                    for n in nids:
                        cur.execute("DELETE FROM notification_reads WHERE notification_id=%s", (n,))
                        cur.execute("DELETE FROM notifications WHERE id=%s", (n,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
        cleanup(uids)

def main():
    test_membership()
    test_notifications()
    test_expiry_scan()
    test_upgrade_backdoor()
    test_notification_api()
    print("\n---- PASS %d / FAIL %d" % (PASS, FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
