import sys
import random
import datetime
import http.cookiejar
import urllib.request
import urllib.error

import db
import auth

BASE = "http://127.0.0.1:8015"
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

_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(),
                                      urllib.request.ProxyHandler({}))

def get_html(path, cookie=None):
    req = urllib.request.Request(BASE + path)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with _opener.open(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")

def make_user(tag):
    for _ in range(6):
        phone = "132%08d" % random.randint(10000000, 99999999)
        try:
            u = auth.create_user(phone, "Tes@123456", None, tag, require_invite=False)
            return int(u["id"]) if isinstance(u, dict) else int(u)
        except Exception:
            continue
    raise RuntimeError("创建测试用户失败")

def set_membership(uid, level, expiry):
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET membership_level=%s, membership_expiry=%s WHERE id=%s",
                        (level, expiry, uid))
        conn.commit()
    finally:
        conn.close()

def cookie_for(uid):
    return "geek_session=" + auth._sign({"uid": uid})

def cleanup(uids):
    for uid in uids:
        try:
            auth.delete_user(uid)
        except Exception as e:
            print("  ⚠️ 清理失败 uid=%s: %s" % (uid, e))

def main():
    uids = []
    today = datetime.date.today()

    print("[A] 套餐收敛：半年卡与多余按量包已下线")
    code, html = get_html("/pricing")
    check("游客访问 /pricing 返回 200", code == 200, code)
    check("页面不再出现「半年卡」", "半年卡" not in html)
    check("页面保留「月卡」", "月卡" in html)
    check("页面保留「年卡」", "年卡" in html)
    check("按量包只剩体验包（不出现 20 次包 / 10 次包）",
          "20次包" not in html and "10次包" not in html and "普通分析20" not in html)
    check("体验包文案存在", "新人体验包" in html and "¥9.9" in html)
    check("周期按钮只有 2 个（月/年）", html.count('onclick="switchPeriod(') == 2,
          html.count('onclick="switchPeriod('))
    check("不再宣传未实现权益（潮汐量化指标 / 专属群聊）",
          "潮汐量化指标" not in html and "专属群聊" not in html)
    check("不再有空的「更多其它权益」", "更多其它权益" not in html)

    print("[B] 游客：按钮为「立即开通」，提示先登录")
    check("游客看到「立即开通」", "立即开通" in html)
    check("游客不显示「续费会员」", "续费会员" not in html)
    check("游客提示需登录", "登录" in html)

    print("[C] 免费已登录用户：仍是「立即开通」")
    u_free = make_user("t-free")
    uids.append(u_free)
    code, html = get_html("/pricing", cookie_for(u_free))
    check("免费用户访问 200", code == 200, code)
    check("免费用户看到「立即开通」", "立即开通" in html)
    check("免费用户不显示「续费会员」", "续费会员" not in html)

    print("[D] VIP-1 用户：VIP-1 卡显示续费 + 到期日，VIP-2 卡显示升级")
    u1 = make_user("t-vip1")
    uids.append(u1)
    exp1 = (today + datetime.timedelta(days=25)).isoformat()
    set_membership(u1, 1, exp1)
    code, html = get_html("/pricing", cookie_for(u1))
    check("VIP-1 访问 200", code == 200, code)
    check("VIP-1 卡显示「续费会员」", "续费会员" in html)
    check("VIP-1 卡显示到期日", exp1 in html, exp1)
    check("VIP-1 卡显示剩余天数", "剩余 25 天" in html)
    check("VIP-2 卡显示「升级到 VIP-2」", "升级到 VIP-2" in html)
    check("免费卡显示已升级", "已升级至" in html)
    check("状态条显示会员等级", "VIP-1 会员" in html)

    print("[E] VIP-2 用户：VIP-2 卡续费，VIP-1 卡不诱导降级")
    u2 = make_user("t-vip2")
    uids.append(u2)
    exp2 = (today + datetime.timedelta(days=200)).isoformat()
    set_membership(u2, 2, exp2)
    code, html = get_html("/pricing", cookie_for(u2))
    check("VIP-2 访问 200", code == 200, code)
    check("VIP-2 卡显示「续费会员」", "续费会员" in html)
    check("VIP-2 显示「无需降级购买」", "无需降级购买" in html)
    check("VIP-2 不出现「升级到 VIP-2」", "升级到 VIP-2" not in html)

    print("[F] 过期会员：按未开通处理（不显示续费按钮）")
    u3 = make_user("t-exp")
    uids.append(u3)
    exp_old = (today - datetime.timedelta(days=3)).isoformat()
    set_membership(u3, 2, exp_old)
    code, html = get_html("/pricing", cookie_for(u3))
    check("过期会员访问 200", code == 200, code)
    check("过期会员不显示「续费会员」", "续费会员" not in html)
    check("过期会员显示未开通提示", "尚未开通会员" in html)

    print("[H] 终身会员（expiry=NULL）：显示长期有效，不能算成剩余 0 天")
    u4 = make_user("t-life")
    uids.append(u4)
    set_membership(u4, 2, None)
    code, html = get_html("/pricing", cookie_for(u4))
    check("终身会员访问 200", code == 200, code)
    check("终身会员显示「长期有效」", "长期有效" in html)
    check("终身会员不显示「剩余 0 天」", "剩余 0 天" not in html)

    print("[G] FAQ / 结构化数据一致性")
    check("FAQ 不再提半年卡", "半年卡" not in html)
    check("FAQ 有 VIP-1 / VIP-2 区别说明", "VIP-1 和 VIP-2 有什么区别" in html)
    check("JSON-LD 同步（无半年卡）", "半年卡" not in html)

    cleanup(uids)
    print("\n----\nPASS=%d FAIL=%d" % (PASS, FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
