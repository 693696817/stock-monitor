import sys
import random
import datetime

import db
import auth
import settings

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

def make_user():
    for _ in range(5):
        phone = "137%08d" % random.randint(10000000, 99999999)
        try:
            return auth.create_user(phone, "Tes@123456", None, "quota_tester",
                                    require_invite=False)
        except Exception:
            continue
    raise RuntimeError("创建测试用户失败")

def insert_rec(uid, mode, status, created_at, quota_source="daily"):
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO analysis_records "
                "(user_id, stock_name, stock_code, mode, status, quota_source, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (uid, "测试标的", "000000.SZ", mode, status, quota_source, created_at))
        conn.commit()
    finally:
        conn.close()

def set_bonus(uid, normal=0, deep=0):
    auth.set_bonus(uid, normal=normal, deep=deep)

def main():
    now = datetime.datetime.now()
    this_month = now.strftime("%Y-%m-15 %H:%M:%S")
    last_month = (now.replace(day=1) - datetime.timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")

    db.ensure_analysis_quota_source_column()

    free_user = make_user()
    vip_user = make_user()
    auth.upgrade_membership(vip_user["id"], 1, 30)
    uids = [free_user["id"], vip_user["id"]]
    set_bonus(free_user["id"], 0, 0)
    set_bonus(vip_user["id"], 0, 0)

    try:
        print("\n[A] 配置：QUOTA_RULES 与 tier 派生")
        rules = settings.get_quota_rules()
        check("配置含 free_monthly_deep 且默认 1",
              int(rules.get("free_monthly_deep") or 0) == 1, rules.get("free_monthly_deep"))
        check("VIP 档月度体验默认关闭",
              int(rules.get("vip1_monthly_deep") or 0) == 0, rules.get("vip1_monthly_deep"))

        saved = settings.get_setting("QUOTA_RULES")
        try:
            import json
            old = json.loads(saved) if saved else {}
            stripped = {k: v for k, v in old.items() if not k.endswith("monthly_deep")}
            settings.set_setting("QUOTA_RULES", json.dumps(stripped, ensure_ascii=False))
            r2 = settings.get_quota_rules()
            check("旧配置缺 monthly 键时自动补全为 1",
                  int(r2.get("free_monthly_deep") or 0) == 1, r2.get("free_monthly_deep"))
        finally:
            if saved is not None:
                settings.set_setting("QUOTA_RULES", saved)

        tf = auth.get_effective_tier(auth.get_user_by_id(free_user["id"]))
        tv = auth.get_effective_tier(auth.get_user_by_id(vip_user["id"]))
        check("免费档 tier 带 monthly_deep=1", int(tf.get("monthly_deep") or 0) == 1, tf)
        check("VIP-1 tier 的 monthly_deep=0", int(tv.get("monthly_deep") or 0) == 0, tv)

        print("\n[B] 计数：只算当月 + 只算成功")
        check("初始当月深度次数为 0", auth.get_month_deep_count(free_user["id"]) == 0)
        check("只统计当月的成功深度分析（=1）",
              auth.get_month_deep_count(free_user["id"]) == 1,
              auth.get_month_deep_count(free_user["id"]))

        print("\n[B2] 通道分离：走赠送的记录不侵占每月/每日额度")
        insert_rec(free_user["id"], "deep", "ok", this_month, quota_source="bonus")
        check("赠送记录不计入每月用量（仍=1）",
              auth.get_month_deep_count(free_user["id"]) == 1,
              auth.get_month_deep_count(free_user["id"]))
        _n_today, deep_today = auth.get_today_counts(free_user["id"])
        check("赠送记录不计入每日用量（=0）", deep_today == 0, deep_today)

        print("\n[C] 判定：并行通道而非叠加放开")
        ok, reason, detail = auth.deep_quota_state(free_user["id"], tf)
        check("免费用户本月已用 1 次 → 拒绝", ok is False, (reason, detail))
        check("拒绝原因是「已用尽」而非「会员专属」", reason == "exhausted", reason)

        ok2, reason2, detail2 = auth.deep_quota_state(vip_user["id"], tv)
        check("VIP-1 走每日额度仍可用", ok2 is True, (reason2, detail2))
        check("VIP-1 不叠加月度额度（monthly_rem=0）",
              detail2.get("monthly_rem") == 0, detail2)

        set_bonus(free_user["id"], 0, 1)
        okb, reasonb, detailb = auth.deep_quota_state(free_user["id"], tf)
        check("每月体验用尽但仍有赠送 → 放行", okb is True, (reasonb, detailb))
        check("放行时余量只来自赠送（monthly_rem=0, bonus=1）",
              detailb.get("monthly_rem") == 0 and detailb.get("bonus_deep") == 1
              and detailb.get("remain") == 1, detailb)
        set_bonus(free_user["id"], 0, 0)

        try:
            import json
            cur_rules = json.loads(settings.get_setting("QUOTA_RULES") or "{}")
            cur_rules["free_monthly_deep"] = 0
            settings.set_setting("QUOTA_RULES", json.dumps(cur_rules, ensure_ascii=False))
            tf0 = auth.get_effective_tier(auth.get_user_by_id(free_user["id"]))
            check("关闭后 tier 的 monthly_deep 变 0",
                  int(tf0.get("monthly_deep") or 0) == 0, tf0.get("monthly_deep"))
            ok3, reason3, _d3 = auth.deep_quota_state(free_user["id"], tf0)
            check("关闭月度体验后 → 会员专属提示",
                  ok3 is False and reason3 == "vip_only", (ok3, reason3))
        finally:
            if saved is not None:
                settings.set_setting("QUOTA_RULES", saved)

        print("\n[D] 跨月重置：本月的记录挪到上月后应恢复可用")
        conn = db.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE analysis_records SET created_at=%s "
                    "WHERE user_id=%s AND mode='deep' AND status='ok'",
                    (last_month, free_user["id"]))
            conn.commit()
        finally:
            conn.close()
        check("挪到上月后当月计数归零",
              auth.get_month_deep_count(free_user["id"]) == 0,
              auth.get_month_deep_count(free_user["id"]))
        tf1 = auth.get_effective_tier(auth.get_user_by_id(free_user["id"]))
        ok4, reason4, detail4 = auth.deep_quota_state(free_user["id"], tf1)
        check("新月恢复 1 次体验", ok4 is True and detail4.get("monthly_rem") == 1,
              (reason4, detail4))
        ok5, _r5, _d5 = auth.deep_quota_state(free_user["id"], tf1)
        check("同一时刻重复判定仍只有 1 次余量（不会叠加）",
              _d5.get("remain") == _d5.get("monthly_rem") + _d5.get("daily_rem")
              + _d5.get("bonus_deep"), _d5)
    finally:
        for uid in uids:
            try:
                conn = db.get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM analysis_records WHERE user_id=%s", (uid,))
                        cur.execute("DELETE FROM membership_orders WHERE user_id=%s", (uid,))
                    conn.commit()
                finally:
                    conn.close()
                auth.delete_user(uid)
            except Exception as e:
                print("  ⚠️ 清理失败 uid=%s: %s" % (uid, e))

    print("\n---- PASS %d / FAIL %d" % (PASS, FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
