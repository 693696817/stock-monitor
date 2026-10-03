
import os
import re
import json
import hmac
import hashlib
import base64
import secrets
import string
import datetime

from config import SESSION_SECRET
import settings
from sms_service import is_valid_mobile
from db import (
    get_conn, init_db as _db_init_db,
    insert_invite_record, insert_membership_order, insert_login_log,
    mark_analysis_failed,
)

TIERS = {
    0: {"level": 0, "name": "免费版",      "normal_daily": 2,    "deep_daily": 0,  "monthly_deep": 1, "pdf": False, "color": "secondary"},
    1: {"level": 1, "name": "VIP-1 会员",  "normal_daily": 5,    "deep_daily": 2,  "monthly_deep": 0, "pdf": True,  "color": "warning"},
    2: {"level": 2, "name": "VIP-2 尊享版", "normal_daily": 10,   "deep_daily": 5,  "monthly_deep": 0, "pdf": True,  "color": "info"},
}

def init_db():
    _db_init_db()

def _parse_date(exp):
    if exp is None:
        return None
    if isinstance(exp, datetime.datetime):
        return exp.date()
    if isinstance(exp, datetime.date):
        return exp
    s = str(exp).strip()
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s[:10])
    except Exception:
        return None

def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return dk.hex(), salt.hex()

def verify_password(password, password_hash, salt_hex):
    try:
        salt = bytes.fromhex(salt_hex)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return hmac.compare_digest(dk.hex(), password_hash)

def _gen_invite_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))

def _row_to_dict(row):
    if not row:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime.datetime):
            d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, datetime.date):
            d[k] = v.strftime("%Y-%m-%d")
    return d

def is_vip_active(user):
    if not user or user.get("membership_level", 0) < 1:
        return False
    d = _parse_date(user.get("membership_expiry"))
    if d is None:
        return True
    return d >= datetime.date.today()

def get_effective_tier(user):
    tier = TIERS[user["membership_level"]] if (user and is_vip_active(user)) else TIERS[0]
    try:
        rules = settings.get_quota_rules()
    except Exception:
        return tier
    if not rules:
        return tier
    t = dict(tier)
    prefix = "free" if t["level"] == 0 else ("vip%d" % t["level"])
    for attr, key in (("normal_daily", prefix + "_daily_normal"),
                      ("deep_daily", prefix + "_daily_deep"),
                      ("monthly_deep", prefix + "_monthly_deep")):
        try:
            v = int(str(rules.get(key)).strip())
            if v >= 0:
                t[attr] = v
        except (TypeError, ValueError):
            pass
    return t

PHONE_EMAIL_SUFFIX = "@phone.local"
_PHONE_EMAIL_PREFIX = "p"

def phone_to_email(phone):
    return "%s%s%s" % (_PHONE_EMAIL_PREFIX, str(phone or "").strip(), PHONE_EMAIL_SUFFIX)

def is_phone_email(email):
    return str(email or "").strip().lower().endswith(PHONE_EMAIL_SUFFIX)

def email_to_phone(email):
    e = str(email or "").strip().lower()
    if not e.endswith(PHONE_EMAIL_SUFFIX):
        return ""
    body = e[: -len(PHONE_EMAIL_SUFFIX)]
    return body[len(_PHONE_EMAIL_PREFIX):] if body.startswith(_PHONE_EMAIL_PREFIX) else body

def mask_phone(phone):
    p = str(phone or "").strip()
    return (p[:3] + "****" + p[-4:]) if len(p) >= 7 else "****"

def create_user(phone, password, invite_code=None, nickname=None, require_invite=False):
    phone = str(phone or "").strip()
    if not is_valid_mobile(phone):
        raise ValueError("手机号格式不正确")
    try:
        _policy = settings.get_register_policy()
    except Exception:
        _policy = {}
    try:
        min_len = int(str((_policy or {}).get("password_min_len") or 6).strip())
    except (TypeError, ValueError):
        min_len = 6
    if min_len < 4:
        min_len = 4
    if not password or len(password) < min_len:
        raise ValueError(f"密码至少 {min_len} 位")

    email = phone_to_email(phone)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cur.fetchone():
                raise ValueError("该手机号已注册")
            cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
            if cur.fetchone():
                raise ValueError("该手机号已注册")

            inviter_id = None
            if invite_code:
                cur.execute(
                    "SELECT id FROM users WHERE invite_code=%s",
                    (invite_code.strip().upper(),),
                )
                inv = cur.fetchone()
                if inv:
                    inviter_id = inv["id"]
            if require_invite and inviter_id is None:
                raise ValueError("邀请码无效或不存在，请核对后重新填写")

            ph, salt = _hash_password(password)
            code = _gen_invite_code()
            while True:
                cur.execute("SELECT id FROM users WHERE invite_code=%s", (code,))
                if not cur.fetchone():
                    break
                code = _gen_invite_code()

            default_name = nickname or ("手机用户" + phone[-4:])
            now = _now()
            try:
                bonus_normal, bonus_deep = settings.get_register_bonus()
            except Exception:
                bonus_normal, bonus_deep = 5, 1
            cur.execute(
                """INSERT INTO users
                   (email, username, password_hash, salt, nickname, membership_level,
                    membership_expiry, bonus_normal, bonus_deep, points, invite_code,
                    invited_by, phone, phone_verified,
                    created_at, daily_analysis_date, daily_analysis_count)
                   VALUES (%s,%s,%s,%s,%s,0,NULL,%s,%s,0,%s,%s,%s,1,%s,NULL,0)""",
                (email, default_name, ph, salt, default_name,
                 bonus_normal, bonus_deep,
                 code, inviter_id, phone, now),
            )
            uid = cur.lastrowid
            conn.commit()

            if inviter_id:
                _grant_vip(conn, inviter_id, 3)
                _grant_vip(conn, uid, 3)
                conn.commit()
                try:
                    insert_invite_record(inviter_id, uid, (invite_code or "").strip().upper(), 3, 1)
                except Exception as e:
                    print(f"[auth] insert_invite_record warn: {e}")

            return get_user_by_id(uid)
    finally:
        conn.close()

def create_user_admin(email, password, nickname=None, phone=None, phone_verified=0,
                      membership_level=0, membership_expiry=None, points=0,
                      is_admin=0, status=1):
    if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return False, "邮箱格式不正确", None
    if not password or len(password) < 6:
        return False, "密码至少 6 位", None
    if membership_level not in (0, 1, 2):
        return False, "未知的会员等级", None
    email = email.strip().lower()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cur.fetchone():
                return False, "该邮箱已注册", None
            if phone and phone.strip():
                p = phone.strip()
                cur.execute("SELECT id FROM users WHERE phone=%s", (p,))
                if cur.fetchone():
                    return False, "手机号已被其他用户占用", None

            ph, salt = _hash_password(password)
            code = _gen_invite_code()
            while True:
                cur.execute("SELECT id FROM users WHERE invite_code=%s", (code,))
                if not cur.fetchone():
                    break
                code = _gen_invite_code()

            default_name = nickname or email.split("@")[0]
            now = _now()
            cur.execute(
                """INSERT INTO users
                   (email, username, password_hash, salt, nickname, status,
                    phone, phone_verified, membership_level, membership_expiry,
                    points, invite_code, invited_by, created_at,
                    daily_analysis_date, daily_analysis_count)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,NULL,0)""",
                (email, default_name, ph, salt, default_name,
                 int(status), (phone.strip() if phone else None), int(phone_verified),
                 int(membership_level), membership_expiry or None, int(points),
                 code, now),
            )
            uid = cur.lastrowid
            conn.commit()
            return True, "创建成功", get_user_by_id(uid)
    finally:
        conn.close()

def _grant_vip(conn, uid, days, level=1):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT membership_level, membership_expiry FROM users WHERE id=%s", (uid,)
        )
        row = cur.fetchone()
        if not row:
            return None, None
        today = datetime.date.today()
        exp = _parse_date(row["membership_expiry"])
        cur_level = int(row["membership_level"] or 0)
        lifetime = cur_level >= 1 and exp is None
        still_active = cur_level >= 1 and (lifetime or bool(exp and exp >= today))
        new_level = max(cur_level, int(level)) if still_active else int(level)
        if lifetime:
            new_expiry = None
        else:
            base = exp if (exp and exp >= today) else today
            new_expiry = (base + datetime.timedelta(days=int(days))).isoformat()
        cur.execute(
            "UPDATE users SET membership_level=%s, membership_expiry=%s WHERE id=%s",
            (new_level, new_expiry, uid),
        )
        return new_level, new_expiry

def authenticate(identifier, password):
    ident = (identifier or "").strip()
    if not ident:
        return None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            row = None
            if "@" in ident:
                cur.execute("SELECT * FROM users WHERE email=%s", (ident.lower(),))
                row = cur.fetchone()
            else:
                cur.execute("SELECT * FROM users WHERE phone=%s", (ident,))
                row = cur.fetchone()
                if not row:
                    cur.execute("SELECT * FROM users WHERE email=%s", (ident.lower(),))
                    row = cur.fetchone()
            if not row:
                return None
            if int(row.get("status") or 0) != 1:
                return None
            if not verify_password(password, row["password_hash"], row["salt"]):
                return None
            return _row_to_dict(row)
    finally:
        conn.close()

def find_user_by_identifier(identifier):
    ident = (identifier or "").strip()
    if not ident:
        return None
    if "@" in ident:
        return get_user_by_email(ident)
    return get_user_by_phone(ident) or get_user_by_email(ident)

def get_user_by_id(uid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
            return _row_to_dict(cur.fetchone())
    finally:
        conn.close()

def get_user_by_email(email):
    email = (email or "").strip().lower()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email=%s", (email,))
            return _row_to_dict(cur.fetchone())
    finally:
        conn.close()

def get_user_by_phone(phone):
    phone = (phone or "").strip()
    if not phone:
        return None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE phone=%s", (phone,))
            return _row_to_dict(cur.fetchone())
    finally:
        conn.close()

def ensure_admin(email, password):
    email = (email or "").strip().lower()
    if not email or not password:
        return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE is_admin=1 LIMIT 1")
            if cur.fetchone():
                return
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cur.fetchone():
                cur.execute("UPDATE users SET is_admin=1 WHERE email=%s", (email,))
                conn.commit()
                return
            ph, salt = _hash_password(password)
            code = _gen_invite_code()
            now = _now()
            cur.execute(
                """INSERT INTO users
                   (email, username, password_hash, salt, nickname, membership_level,
                    membership_expiry, points, invite_code, invited_by, is_admin, created_at,
                    daily_analysis_date, daily_analysis_count)
                   VALUES (%s,%s,%s,%s,%s,2,NULL,0,%s,NULL,1,%s,NULL,0)""",
                (email, email.split("@")[0], ph, salt, "管理员", code, now),
            )
            conn.commit()
    finally:
        conn.close()

def upgrade_membership(uid, level, days, amount=0.0, currency="CNY",
                       payment_method="demo", payment_status=1, remark="演示开通（未真实扣费）"):
    if level not in TIERS:
        raise ValueError("未知的会员等级")
    conn = get_conn()
    try:
        if level == 0:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET membership_level=0, membership_expiry=NULL WHERE id=%s",
                    (uid,),
                )
            conn.commit()
            return
        _grant_vip(conn, uid, days, level)
        conn.commit()
    finally:
        conn.close()

    user = get_user_by_id(uid)
    plan_code = {1: "vip1", 2: "vip2"}.get(level, "vip%d" % level)
    start_at = _now()
    end_at = str(user["membership_expiry"]) if user and user.get("membership_expiry") else None
    insert_membership_order(
        _gen_order_no(), uid, plan_code, level, amount, currency,
        payment_method, payment_status, start_at, end_at, days, remark,
    )

def _gen_order_no(prefix="M"):
    return "%s%s%04d" % (prefix, datetime.datetime.now().strftime("%Y%m%d%H%M%S"), secrets.randbelow(10000))

def record_login(user_id, email, success, ip, user_agent, reason=None):
    try:
        insert_login_log(user_id, email, success, ip, user_agent, reason)
    except Exception as e:
        print(f"[auth] record_login warn: {e}")

def update_profile(uid, nickname, phone=None, phone_verified=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if phone is None and phone_verified is None:
                cur.execute("UPDATE users SET nickname=%s WHERE id=%s", (nickname, uid))
            else:
                sets = ["nickname=%s"]
                params = [nickname]
                if phone is not None:
                    sets.append("phone=%s")
                    params.append(phone or None)
                if phone_verified is not None:
                    sets.append("phone_verified=%s")
                    params.append(int(phone_verified))
                params.append(uid)
                cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s", params)
        conn.commit()
    finally:
        conn.close()

def count_admins():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin=1")
            return cur.fetchone()["c"]
    finally:
        conn.close()

def update_user_admin(uid, email=None, nickname=None, phone=None, phone_verified=None,
                      membership_level=None, membership_expiry=None, points=None,
                      is_admin=None, status=None, password=None, new_uid=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email, phone FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
            if not row:
                return False, "用户不存在"
            old_email = row["email"]

            if new_uid is not None:
                try:
                    new_uid = int(new_uid)
                except (TypeError, ValueError):
                    return False, "UID 必须为整数"
                if new_uid <= 0:
                    return False, "UID 必须为正整数"
                if new_uid != uid:
                    cur.execute("SELECT id FROM users WHERE id=%s", (new_uid,))
                    if cur.fetchone():
                        return False, f"UID {new_uid} 已被占用"
                    cascade_refs = [
                        ("analysis_records", "user_id"),
                        ("feedback", "user_id"),
                        ("login_logs", "user_id"),
                        ("membership_orders", "user_id"),
                        ("payment_orders", "user_id"),
                        ("invite_records", "inviter_id"),
                        ("invite_records", "invitee_id"),
                        ("users", "invited_by"),
                    ]
                    for tbl, col in cascade_refs:
                        cur.execute(f"UPDATE {tbl} SET {col}=%s WHERE {col}=%s", (new_uid, uid))
                    cur.execute("UPDATE users SET id=%s WHERE id=%s", (new_uid, uid))
                    try:
                        cur.execute("SELECT MAX(id) AS m FROM users")
                        mx = cur.fetchone().get("m") or 0
                        cur.execute(f"ALTER TABLE users AUTO_INCREMENT = {int(mx) + 1}")
                    except Exception:
                        pass
                    uid = new_uid

            if email is not None and email.strip().lower() != (old_email or ""):
                e = email.strip().lower()
                cur.execute("SELECT id FROM users WHERE email=%s AND id<>%s", (e, uid))
                if cur.fetchone():
                    return False, "邮箱已被其他用户占用"
            if phone is not None and phone.strip():
                p = phone.strip()
                cur.execute("SELECT id FROM users WHERE phone=%s AND id<>%s", (p, uid))
                if cur.fetchone():
                    return False, "手机号已被其他用户占用"
            sets, params = [], []
            if email is not None:
                sets.append("email=%s"); params.append(email.strip().lower())
            if nickname is not None:
                sets.append("nickname=%s"); params.append(nickname or None)
            if phone is not None:
                sets.append("phone=%s"); params.append(phone.strip() or None)
            if phone_verified is not None:
                sets.append("phone_verified=%s"); params.append(int(phone_verified))
            if membership_level is not None:
                sets.append("membership_level=%s"); params.append(int(membership_level))
            if membership_expiry is not None:
                sets.append("membership_expiry=%s"); params.append(membership_expiry or None)
            if points is not None:
                sets.append("points=%s"); params.append(int(points))
            if is_admin is not None:
                sets.append("is_admin=%s"); params.append(int(is_admin))
            if status is not None:
                sets.append("status=%s"); params.append(int(status))
            if password:
                ph, salt = _hash_password(password)
                sets.append("password_hash=%s"); params.append(ph)
                sets.append("salt=%s"); params.append(salt)
            if not sets:
                return True, "无变更"
            params.append(uid)
            cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s", params)
        conn.commit()
        return True, "已保存"
    finally:
        conn.close()

def delete_user(uid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id=%s", (uid,))
            if not cur.fetchone():
                return False, "用户不存在"
            cur.execute("DELETE FROM analysis_records WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM feedback WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM login_logs WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM membership_orders WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM payment_orders WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM invite_records WHERE inviter_id=%s OR invitee_id=%s", (uid, uid))
            cur.execute("DELETE FROM users WHERE id=%s", (uid,))
        conn.commit()
        return True, "已删除"
    finally:
        conn.close()

def get_today_counts(uid):
    today = datetime.date.today().isoformat()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT mode, COUNT(*) AS c FROM analysis_records "
                "WHERE user_id=%s AND substr(created_at,1,10)=%s "
                "AND (status IS NULL OR status='ok') "
                "AND (quota_source IS NULL OR quota_source='daily') GROUP BY mode",
                (uid, today),
            )
            rows = cur.fetchall()
            normal = sum(r["c"] for r in rows if r["mode"] == "normal")
            deep = sum(r["c"] for r in rows if r["mode"] == "deep")
            return normal, deep
    finally:
        conn.close()

def get_bonus(uid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bonus_normal, bonus_deep FROM users WHERE id=%s", (uid,)
            )
            row = cur.fetchone()
            if not row:
                return 0, 0
            return int(row.get("bonus_normal") or 0), int(row.get("bonus_deep") or 0)
    finally:
        conn.close()

def set_bonus(uid, normal=None, deep=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sets, params = [], []
            if normal is not None:
                sets.append("bonus_normal=%s")
                params.append(int(max(0, normal)))
            if deep is not None:
                sets.append("bonus_deep=%s")
                params.append(int(max(0, deep)))
            if not sets:
                return
            params.append(uid)
            cur.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE id=%s", params
            )
        conn.commit()
    finally:
        conn.close()

def consume_bonus_atomic(uid, mode):
    col = "bonus_deep" if mode == "deep" else "bonus_normal"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            n = cur.execute(
                f"UPDATE users SET {col} = {col} - 1 WHERE id=%s AND {col} > 0",
                (uid,),
            )
        conn.commit()
        return n == 1
    finally:
        conn.close()

def restore_bonus(uid, mode):
    col = "bonus_deep" if mode == "deep" else "bonus_normal"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {col} = {col} + 1 WHERE id=%s", (uid,))
        conn.commit()
        return True
    finally:
        conn.close()

def refund_analysis(uid, rid, mode="normal", bonus_consumed=0, error_msg=None):
    changed = mark_analysis_failed(rid, error_msg)
    if not changed:
        return False
    if bonus_consumed and bonus_consumed > 0:
        bn, bd = get_bonus(uid)
        if mode == "deep":
            set_bonus(uid, deep=int(bd) + 1)
        else:
            set_bonus(uid, normal=int(bn) + 1)
    return True

def record_analysis(uid, stock_name, stock_code, mode, model_id=None, preference=None,
                    report_md=None, quota_source="daily"):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            now = _now()
            cur.execute(
                "INSERT INTO analysis_records "
                "(user_id, stock_name, stock_code, mode, model_id, preference, report_md, "
                " quota_source, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (uid, stock_name, stock_code, mode or "normal",
                 model_id or None, preference or None, report_md or None,
                 "bonus" if quota_source == "bonus" else "daily", now),
            )
            rid = cur.lastrowid
        conn.commit()
        return rid
    finally:
        conn.close()

def update_analysis_report(rid, report_md):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE analysis_records SET report_md=%s WHERE id=%s",
                (report_md or None, rid),
            )
        conn.commit()
    finally:
        conn.close()

def get_analysis_by_id(uid, rid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM analysis_records WHERE id=%s AND user_id=%s",
                (rid, uid),
            )
            return _row_to_dict(cur.fetchone())
    finally:
        conn.close()

def get_analysis_by_id_any(rid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.*, u.email AS owner_email, u.nickname AS owner_nickname "
                "FROM analysis_records r LEFT JOIN users u ON u.id = r.user_id "
                "WHERE r.id=%s",
                (rid,),
            )
            return _row_to_dict(cur.fetchone())
    finally:
        conn.close()

def get_analysis_history(uid, limit=10):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, stock_name, stock_code, mode, model_id, preference, created_at "
                "FROM analysis_records "
                "WHERE user_id=%s ORDER BY id DESC LIMIT %s",
                (uid, limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def get_analysis_history_page(uid, page=1, per_page=10, mode=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = "WHERE user_id=%s"
            params = [uid]
            if mode in ("normal", "deep"):
                where += " AND mode=%s"
                params.append(mode)
            cur.execute(
                f"SELECT COUNT(*) AS c FROM analysis_records {where}", params
            )
            row = cur.fetchone()
            total = row["c"] if row else 0
            offset = max(0, (int(page) - 1)) * int(per_page)
            cur.execute(
                f"SELECT id, stock_name, stock_code, mode, model_id, preference, created_at "
                f"FROM analysis_records {where} "
                f"ORDER BY id DESC LIMIT %s OFFSET %s",
                params + [int(per_page), offset],
            )
            return total, [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def get_analysis_total(uid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM analysis_records WHERE user_id=%s", (uid,)
            )
            row = cur.fetchone()
            return row["c"] if row else 0
    finally:
        conn.close()

def reset_password_by_phone(phone, new_password):
    user = get_user_by_phone(phone)
    if not user:
        return False, "该手机号未注册"
    if not new_password or len(new_password) < 6:
        return False, "新密码至少 6 位"
    return _update_password(user["id"], new_password)

def reset_password_by_email(email, new_password):
    user = get_user_by_email(email)
    if not user:
        return False, "该邮箱未注册"
    if not new_password or len(new_password) < 6:
        return False, "新密码至少 6 位"
    return _update_password(user["id"], new_password)

def _update_password(uid, new_password):
    h, salt = _hash_password(new_password)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash=%s, salt=%s, "
                "pwd_version = COALESCE(pwd_version,0) + 1 WHERE id=%s",
                (h, salt, uid),
            )
        conn.commit()
        return True, "密码已重置，请使用新密码登录"
    finally:
        conn.close()

def add_watch(uid, ts_code, stock_name, note=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO watchlists (user_id, ts_code, stock_name, note, created_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (uid, ts_code, stock_name, note or None, _now()),
            )
        conn.commit()
        return True, "已加入自选"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def remove_watch(uid, ts_code):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM watchlists WHERE user_id=%s AND ts_code=%s",
                (uid, ts_code),
            )
        conn.commit()
        return True, "已取消收藏"
    finally:
        conn.close()

def list_watch(uid, limit=50):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ts_code, stock_name, note, group_name, cost, quantity, created_at "
                "FROM watchlists WHERE user_id=%s ORDER BY id DESC LIMIT %s",
                (uid, limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def is_watched(uid, ts_code):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM watchlists WHERE user_id=%s AND ts_code=%s LIMIT 1",
                (uid, ts_code),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()

def list_user_orders(uid, limit=20):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, order_no, plan_code, level, amount, currency, "
                "payment_method, payment_status, start_at, end_at, days, remark, created_at "
                "FROM membership_orders WHERE user_id=%s ORDER BY id DESC LIMIT %s",
                (uid, limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def get_invite_count(uid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM users WHERE invited_by=%s", (uid,)
            )
            row = cur.fetchone()
            return row["c"] if row else 0
    finally:
        conn.close()

def to_public(user):
    if not user:
        return None
    tier = get_effective_tier(user)
    raw_email = user.get("email") or ""
    has_email = bool(raw_email) and not is_phone_email(raw_email)
    account = mask_phone(user.get("phone") or email_to_phone(raw_email))
    return {
        "id": user["id"],
        "email": raw_email if has_email else "",
        "has_email": has_email,
        "account": account,
        "nickname": user["nickname"] or (raw_email.split("@")[0] if has_email else account),
        "membership_level": user["membership_level"],
        "membership_name": tier["name"],
        "tier": tier,
        "is_vip": tier["level"] >= 1,
        "is_admin": bool(user.get("is_admin", 0)),
        "membership_expiry": user["membership_expiry"],
        "points": user["points"],
        "invite_code": user["invite_code"],
        "phone": user.get("phone"),
        "created_at": user["created_at"],
        "tier": tier,
    }

def _sign(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"

def _unsign(token: str):
    try:
        raw, sig = token.rsplit(".", 1)
        expected = hmac.new(SESSION_SECRET.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        return json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except Exception:
        return None

def set_session_cookie(response, user_id, request=None, max_age=60 * 60 * 24 * 30):
    payload = {"uid": user_id, "iat": datetime.datetime.now().isoformat(timespec="seconds")}
    try:
        u = get_user_by_id(user_id) or {}
        payload["pwdv"] = int(u.get("pwd_version") or 0)
    except Exception:
        payload["pwdv"] = 0
    token = _sign(payload)
    secure = False
    if request is not None:
        proto = (request.headers.get("x-forwarded-proto") or "").lower()
        if proto:
            secure = proto == "https"
        else:
            secure = (request.url.scheme or "").lower() == "https"
    response.set_cookie(
        "geek_session", token, httponly=True, samesite="lax", max_age=max_age, path="/",
        secure=secure,
    )

def clear_session_cookie(response):
    response.delete_cookie("geek_session", path="/")

def get_current_user(request):
    token = request.cookies.get("geek_session")
    if not token:
        return None
    data = _unsign(token)
    if not data or "uid" not in data:
        return None
    user = get_user_by_id(data["uid"])
    if not user or int(user.get("status") or 0) != 1:
        return None
    if int(data.get("pwdv") or 0) != int(user.get("pwd_version") or 0):
        return None
    return user

def _membership_snapshot(cur, uid):
    cur.execute(
        "SELECT membership_level, membership_expiry FROM users WHERE id=%s", (uid,)
    )
    row = cur.fetchone() or {}
    exp = _parse_date(row.get("membership_expiry"))
    return {
        "level": int(row.get("membership_level") or 0),
        "expiry": str(row.get("membership_expiry") or "") or None,
        "active": int(row.get("membership_level") or 0) >= 1
                  and (exp is None or exp >= datetime.date.today()),
    }

def notify_redeem_success(uid, row, level, days, bn, bd, new_level, new_expiry):
    from db import create_notification

    parts = []
    if new_level and new_expiry:
        parts.append("VIP-%d 会员有效期至 %s" % (new_level, new_expiry))
    if bn:
        parts.append("普通分析 %d 次" % bn)
    if bd:
        parts.append("深度分析 %d 次" % bd)
    plan = "%s · %s" % (row.get("plan_name") or "", row.get("sku_label") or "")
    return create_notification(
        uid, "redeem", "兑换成功：%s" % (plan.strip(" ·") or "权益已到账"),
        "您兑换的 %s 已到账：%s。感谢支持！" % (plan.strip(" ·") or "权益", "、".join(parts) or "权益已发放"),
        link="/profile#membership", level="success",
        dedup_key="redeem:%s" % (row.get("code") or ""),
    )

def redeem_code(uid, code):
    from db import fetch_redeem_code_locked, mark_redeem_code_used, add_user_bonus

    raw = str(code or "").strip().upper().replace("-", "").replace(" ", "")
    if not raw:
        return False, "请输入兑换码", {}
    if len(raw) > 32 or not raw.isalnum():
        return False, "兑换码格式不正确", {}

    row = None
    conn = get_conn()
    try:
        conn.begin()
        with conn.cursor() as cur:
            row = fetch_redeem_code_locked(cur, raw)
            if not row:
                conn.rollback()
                return False, "兑换码不存在，请核对后重试", {}
            st = int(row.get("status") or 0)
            if st == 1:
                conn.rollback()
                return False, "该兑换码已被使用", {}
            if st == 2:
                conn.rollback()
                return False, "该兑换码已作废", {}
            exp = row.get("expire_at")
            if exp:
                try:
                    if exp < datetime.datetime.now():
                        conn.rollback()
                        return False, "该兑换码已过期", {}
                except Exception:
                    pass

            level = int(row.get("level") or 0)
            days = int(row.get("days") or 0)
            bn = int(row.get("bonus_normal") or 0)
            bd = int(row.get("bonus_deep") or 0)

            before = _membership_snapshot(cur, uid)
            new_level, new_expiry = (None, None)
            if level > 0 and days > 0:
                new_level, new_expiry = _grant_vip(conn, uid, days, level)
            if bn or bd:
                add_user_bonus(uid, bn, bd, conn=conn)

            if not mark_redeem_code_used(cur, raw, uid):
                conn.rollback()
                return False, "兑换失败，请重试", {}
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print("⚠️ [Redeem] 核销失败 uid=%s: %s: %s" % (uid, type(e).__name__, e))
        return False, "兑换失败，请稍后重试", {}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    try:
        insert_membership_order(
            _gen_order_no("R"), uid, str(row.get("plan_key") or "redeem"), level, 0.0, "CNY",
            "redeem_code", 1, _now(),
            new_expiry, days,
            "兑换码核销（批次 %s，原到期 %s）" % (row.get("batch_no") or "-",
                                          (before or {}).get("expiry") or "无"),
        )
    except Exception as e:
        print("⚠️ [Redeem] 订单流水写入失败 uid=%s: %s" % (uid, e))

    try:
        notify_redeem_success(uid, row, level, days, bn, bd, new_level, new_expiry)
    except Exception as e:
        print("⚠️ [Redeem] 通知写入失败 uid=%s: %s" % (uid, e))

    parts = []
    if new_level and new_expiry:
        parts.append("VIP-%d 会员有效期至 %s" % (new_level, new_expiry))
    elif level > 0 and days > 0:
        parts.append("VIP-%d 会员 %d 天" % (level, days))
    if bn:
        parts.append("普通分析 %d 次" % bn)
    if bd:
        parts.append("深度分析 %d 次" % bd)
    return True, ("兑换成功：" + "、".join(parts) if parts else "兑换成功"), {
        "plan_name": row.get("plan_name") or "",
        "sku_label": row.get("sku_label") or "",
        "level": level, "days": days,
        "bonus_normal": bn, "bonus_deep": bd,
        "new_level": new_level, "new_expiry": new_expiry,
        "level_upgraded": bool(new_level and (before or {}).get("level")
                               and new_level > int((before or {}).get("level") or 0)),
    }

def get_deep_usage(uid):
    today = datetime.date.today().isoformat()
    ym = today[:7]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT "
                "SUM(CASE WHEN mode='deep' AND substr(created_at,1,10)=%s THEN 1 ELSE 0 END) AS d_today, "
                "SUM(CASE WHEN mode='deep' AND substr(created_at,1,7)=%s THEN 1 ELSE 0 END) AS d_month "
                "FROM analysis_records WHERE user_id=%s "
                "AND (status IS NULL OR status='ok') "
                "AND (quota_source IS NULL OR quota_source='daily')",
                (today, ym, uid),
            )
            row = cur.fetchone() or {}
            return int(row.get("d_today") or 0), int(row.get("d_month") or 0)
    finally:
        conn.close()

def get_month_deep_count(uid):
    ym = datetime.date.today().strftime("%Y-%m")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM analysis_records "
                "WHERE user_id=%s AND mode='deep' AND substr(created_at,1,7)=%s "
                "AND (status IS NULL OR status='ok') "
                "AND (quota_source IS NULL OR quota_source='daily')",
                (uid, ym),
            )
            row = cur.fetchone() or {}
            return int(row.get("c") or 0)
    finally:
        conn.close()

def deep_quota_state(uid, tier, deep_used_today=None, bonus_deep=None):
    daily_quota = int(tier.get("deep_daily") or 0)
    monthly_quota = int(tier.get("monthly_deep") or 0)
    if deep_used_today is None or monthly_quota > 0:
        _d_today, _d_month = get_deep_usage(uid)
        deep_used_today = _d_today if deep_used_today is None else deep_used_today
    else:
        _d_month = 0
    deep_used_month = _d_month if monthly_quota > 0 else 0
    if bonus_deep is None:
        _bn, bonus_deep = get_bonus(uid)

    daily_rem = max(0, daily_quota - deep_used_today)
    monthly_rem = max(0, monthly_quota - deep_used_month) if monthly_quota > 0 else 0
    total_rem = daily_rem + monthly_rem + bonus_deep

    detail = {
        "daily_quota": daily_quota, "daily_used": deep_used_today, "daily_rem": daily_rem,
        "monthly_quota": monthly_quota, "monthly_used": deep_used_month,
        "monthly_rem": monthly_rem,
        "bonus_deep": bonus_deep, "remain": total_rem,
    }
    if total_rem <= 0:
        reason = "vip_only" if (daily_quota <= 0 and monthly_quota <= 0 and bonus_deep <= 0) \
            else "exhausted"
        return False, reason, detail
    return True, "", detail
