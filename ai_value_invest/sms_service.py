
import re
import json
import secrets
import time
import datetime
import threading
import urllib.request
import urllib.parse

from db import get_conn
from config import SPUG_SMS_TEMPLATE_CODE, SMS_ENABLED

CODE_MAX_FAIL = 5
_CODE_FAIL_LOCK = threading.Lock()

def _code_max_fail():
    try:
        v = int(str((settings.get_rate_limits() or {}).get("sms_code_max_fail") or CODE_MAX_FAIL).strip())
        return v if v > 0 else CODE_MAX_FAIL
    except Exception:
        return CODE_MAX_FAIL

SCENES = ("register", "login", "bind", "reset")
_SCENE_LABEL = {"register": "注册", "login": "登录", "bind": "绑定手机"}

def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _to_ts(s):
    try:
        return datetime.datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return 0

def _today_start():
    return datetime.date.today().isoformat() + " 00:00:00"

def gen_code():
    return "%06d" % secrets.randbelow(1000000)

def is_valid_mobile(mobile):
    return bool(re.match(r"^1[3-9]\d{9}$", (mobile or "").strip()))

def send_sms(mobile, code, ttl_minutes=5):
    if not SMS_ENABLED:
        return False, "短信服务未启用"
    if not SPUG_SMS_TEMPLATE_CODE:
        return False, "未配置短信模板编码(SPUG_SMS_TEMPLATE_CODE)"
    if not is_valid_mobile(mobile):
        return False, "手机号格式不正确"

    params = {"to": mobile, "code": str(code), "number": str(ttl_minutes)}
    url = SPUG_SMS_BASE + SPUG_SMS_TEMPLATE_CODE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "geek-ai-sms/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        return False, f"网关 HTTP {e.code}: {detail}"
    except Exception as e:
        return False, f"发送失败: {e}"

    return _parse_spug(body)

def _parse_spug(body):
    try:
        obj = json.loads(body)
    except Exception:
        if "success" in (body or "").lower():
            return True, "发送成功"
        return False, f"网关返回异常: {body[:120]}"
    code = obj.get("code")
    msg = obj.get("msg") or obj.get("message") or ""
    ok_codes = (0, 200, "0", "200", "success", "ok")
    if code in ok_codes or str(code).lower() in ("success", "ok"):
        return True, "发送成功"
    return False, f"网关错误 {code}: {msg}"

def can_send(mobile, scene, ip):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT created_at FROM verification_codes "
                "WHERE mobile=%s AND scene=%s ORDER BY id DESC LIMIT 1",
                (mobile, scene),
            )
            row = cur.fetchone()
            if row:
                last = row["created_at"]
                if isinstance(last, datetime.datetime):
                    last = last.strftime("%Y-%m-%d %H:%M:%S")
                elapsed = int(time.time() - _to_ts(last))
                if elapsed < RESEND_INTERVAL:
                    wait = RESEND_INTERVAL - elapsed
                    return False, f"发送过于频繁，请 {wait} 秒后再试", wait
            cur.execute(
                "SELECT COUNT(*) AS c FROM verification_codes "
                "WHERE mobile=%s AND created_at>=%s",
                (mobile, _today_start()),
            )
            if cur.fetchone()["c"] >= DAILY_LIMIT_PER_MOBILE:
                return False, "该手机号今日发送次数已达上限", 0
            if ip:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM verification_codes "
                    "WHERE ip=%s AND created_at>=%s",
                    (ip, _today_start()),
                )
                if cur.fetchone()["c"] >= DAILY_LIMIT_PER_IP:
                    return False, "请求过于频繁，请稍后再试", 0
        return True, "ok", 0
    finally:
        conn.close()

def store_code(mobile, code, scene, ip):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO verification_codes (mobile, code, scene, ip, expire_at, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (mobile, code, scene, ip,
                 datetime.datetime.now() + datetime.timedelta(seconds=CODE_TTL),
                 _now()),
            )
        conn.commit()
    finally:
        conn.close()

def _fail_clean(now=None):
    now = now or time.time()
    for k in [k for k, v in _CODE_FAILS.items() if v[1] < now]:
        _CODE_FAILS.pop(k, None)

def _fail_count(key):
    with _CODE_FAIL_LOCK:
        v = _CODE_FAILS.get(key)
        return v[0] if v else 0

def _fail_bump(key):
    with _CODE_FAIL_LOCK:
        if len(_CODE_FAILS) > 5000:
            _fail_clean()
        cnt, _ = _CODE_FAILS.get(key, (0, 0))
        cnt += 1
        _CODE_FAILS[key] = (cnt, time.time() + CODE_TTL)
        return cnt

def _fail_reset(key):
    with _CODE_FAIL_LOCK:
        _CODE_FAILS.pop(key, None)

def send_code(mobile, scene, ip=""):
    if scene not in SCENES:
        return False, "未知场景"
    if not is_valid_mobile(mobile):
        return False, "手机号格式不正确"
    ok, msg, _ = can_send(mobile, scene, ip)
    if not ok:
        return False, msg
    code = gen_code()
    ok2, msg2 = send_sms(mobile, code, CODE_TTL // 60)
    if not ok2:
        return False, msg2
    store_code(mobile, code, scene, ip)
    return True, "验证码已发送"

def verify_code(mobile, code, scene):
    if not is_valid_mobile(mobile):
        return False, "手机号格式不正确"
    if not code or len(str(code)) != 6:
        return False, "验证码格式不正确"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, code, expire_at FROM verification_codes "
                "WHERE mobile=%s AND scene=%s ORDER BY id DESC LIMIT 1",
                (mobile, scene),
            )
            row = cur.fetchone()
            if not row:
                return False, "验证码不存在或已过期"
            fkey = (mobile, scene, row["id"])
            exp = row["expire_at"]
            if isinstance(exp, datetime.datetime):
                expired = exp < datetime.datetime.now()
            else:
                expired = _to_ts(str(exp)[:19]) < time.time()
            if expired:
                _fail_reset(fkey)
                cur.execute("DELETE FROM verification_codes WHERE mobile=%s AND scene=%s", (mobile, scene))
                conn.commit()
                return False, "验证码已过期，请重新获取"

            if _fail_count(fkey) >= _code_max_fail():
                _fail_reset(fkey)
                cur.execute("DELETE FROM verification_codes WHERE id=%s", (row["id"],))
                conn.commit()
                return False, "错误次数过多，验证码已作废，请重新获取"

            if str(row["code"]) != str(code):
                left = _code_max_fail() - _fail_bump(fkey)
                if left <= 0:
                    _fail_reset(fkey)
                    cur.execute("DELETE FROM verification_codes WHERE id=%s", (row["id"],))
                    conn.commit()
                    return False, "错误次数过多，验证码已作废，请重新获取"
                return False, f"验证码错误，还可尝试 {left} 次"

            _fail_reset(fkey)
            cur.execute("DELETE FROM verification_codes WHERE id=%s", (row["id"],))
            conn.commit()
            return True, "验证通过"
    finally:
        conn.close()
