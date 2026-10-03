
import os
import json
import hashlib
import datetime
import pymysql
from pymysql.cursors import DictCursor

from config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, MYSQL_CHARSET
)

_SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema_mysql.sql")

try:
    from dbutils.pooled_db import PooledDB
    _POOL = None

    def _init_pool():
        global _POOL
        if _POOL is None:
            _POOL = PooledDB(
                creator=pymysql,
                maxconnections=20,
                mincached=2,
                maxcached=10,
                maxshared=0,
                blocking=False,
                maxusage=None,
                setsession=[],
                ping=1,
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DB,
                charset=MYSQL_CHARSET,
                cursorclass=DictCursor,
                autocommit=False,
            )
        return _POOL

    def get_conn():
        """从连接池取出一个连接（DictCursor）。用毕调用 close() 即归还池中。"""
        return _init_pool().connection()

    USING_POOL = True
except ImportError:
    USING_POOL = False

    def get_conn():
        """返回一个 MySQL 连接（DictCursor，autocommit=False）。"""
        return pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB,
            charset=MYSQL_CHARSET,
            cursorclass=DictCursor,
            autocommit=False,
        )

def init_db():
    """按 schema_mysql.sql 建表（幂等，CREATE TABLE IF NOT EXISTS）。"""
    with open(_SCHEMA_FILE, "r", encoding="utf-8") as f:
        sql = f.read()
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()
    ensure_admin_column()
    ensure_pwd_version_column()
    ensure_feedback_columns()
    ensure_analysis_columns()
    ensure_stocks_table()
    ensure_lixinger_top_list_table()
    ensure_stock_detail_cache_table()
    ensure_settings_value_mediumtext()
    ensure_bonus_logs_table()
    ensure_watchlist_columns()
    ensure_watch_alerts_table()
    ensure_analysis_valuation_table()

def ensure_settings_value_mediumtext():
    """幂等：把 system_settings.value 从 TEXT 加宽到 MEDIUMTEXT。

    原因：LIXINGER_API_CATALOG 目录 JSON 约 7.3 万字节，超过 TEXT 的 65,535 字节上限，
    插入会报 1406 "Data too long"，导致该设置永远 seed 不进库（后台目录页无数据）。
    MEDIUMTEXT 上限 16MB，足够容纳接口目录这类大 JSON。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW COLUMNS FROM `system_settings` LIKE 'value'")
            row = cur.fetchone()
            if not row:
                return
            cur_type = (row.get("Type") or "").lower()
            if cur_type.startswith("mediumtext") or cur_type.startswith("longtext"):
                return
            cur.execute(
                "ALTER TABLE `system_settings` MODIFY `value` MEDIUMTEXT DEFAULT NULL "
                "COMMENT '设置值'"
            )
            conn.commit()
            print(f"[db] system_settings.value: {row.get('Type')} -> MEDIUMTEXT")
    except Exception as e:
        print(f"[db] ensure_settings_value_mediumtext warn: {e}")
    finally:
        conn.close()

def ensure_admin_column():
    """幂等：给 users 表补 is_admin 列（早期表无此列）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "ALTER TABLE `users` ADD COLUMN `is_admin` TINYINT NOT NULL DEFAULT 0 "
                    "COMMENT '1=管理员' AFTER `status`"
                )
                conn.commit()
            except pymysql.err.OperationalError as e:
                if e.args[0] in (1060, 1061):
                    conn.rollback()
                else:
                    raise
    finally:
        conn.close()

def ensure_pwd_version_column():
    """幂等：给 users 表补 pwd_version 列（会话撤销用）。

    背景：会话 token 只含 uid+iat，且**不校验 iat** —— 用户改密后，
    攻击者手里的旧会话仍能一直用到 Cookie 自然过期（30 天）为止，改密形同虚设。
    加了版本号后：token 里带签发时的 pwd_version，改密时 +1，
    校验时两边对不上就判未登录 → 旧会话当场失效。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "ALTER TABLE `users` ADD COLUMN `pwd_version` INT NOT NULL DEFAULT 0 "
                    "COMMENT '密码版本号，改密/重置时+1，用于让旧会话失效' AFTER `salt`"
                )
                conn.commit()
            except pymysql.err.OperationalError as e:
                if e.args[0] in (1060, 1061):
                    conn.rollback()
                else:
                    raise
    finally:
        conn.close()

def get_setting(key, default=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `value` FROM system_settings WHERE `key`=%s", (key,))
            row = cur.fetchone()
            return row["value"] if row else default
    finally:
        conn.close()

def set_setting(key, value):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO system_settings (`key`, `value`) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE `value`=%s, updated_at=NOW()",
                (key, value, value),
            )
        conn.commit()
    finally:
        conn.close()

def ensure_feedback_columns():
    """幂等：给 feedback 表补 type 列（早期表无此列，前端图标依赖 type）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "ALTER TABLE `feedback` ADD COLUMN `type` VARCHAR(16) NOT NULL DEFAULT 'other' "
                    "COMMENT 'bug/feature/data/other' AFTER `user_id`"
                )
                conn.commit()
            except pymysql.err.OperationalError as e:
                if e.args[0] in (1060, 1061):
                    conn.rollback()
                else:
                    raise
    finally:
        conn.close()

def ensure_analysis_columns():
    """幂等：给 analysis_records 表补 model_id / preference 列（记录模型与投资偏好）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for col, ddl in [
                ("model_id", "ADD COLUMN `model_id` VARCHAR(32) DEFAULT NULL COMMENT '使用的模型渠道ID' AFTER `mode`"),
                ("preference", "ADD COLUMN `preference` VARCHAR(32) DEFAULT NULL COMMENT '投资偏好ID' AFTER `model_id`"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE `analysis_records` {ddl}")
                    conn.commit()
                except pymysql.err.OperationalError as e:
                    if e.args[0] in (1060, 1061):
                        conn.rollback()
                    else:
                        raise
    finally:
        conn.close()

def mark_analysis_failed(rid, error_msg=None):
    """把一条分析记录标记为「失败不计费」。

    幂等：只有在 status 仍是 ok 时才更新并返回 True；已经是 failed 的重复调用返回 False。
    （流式分析结束、客户端断连重连等场景可能触发多次，必须避免重复退还。）
    """
    if not rid:
        return False
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE analysis_records SET status='failed', error_msg=%s "
                "WHERE id=%s AND status='ok'",
                ((str(error_msg)[:250] if error_msg else None), rid),
            )
            changed = cur.rowcount > 0
        conn.commit()
        return changed
    finally:
        conn.close()

def ensure_analysis_status_columns():
    """幂等：给 analysis_records 补 status / error_msg 列。

    用途：AI 调用失败（模型被关停、超时、鉴权失败等）时把记录标成 failed，
    让 get_today_counts 不再计入今日用量 —— 即「失败不扣配额」。
    保留记录本身而不是删除，方便后台排查「哪个模型老失败」。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for col, ddl in [
                ("status", "ADD COLUMN `status` VARCHAR(16) NOT NULL DEFAULT 'ok' "
                           "COMMENT 'ok=成功计费 / failed=失败不计费' AFTER `preference`"),
                ("error_msg", "ADD COLUMN `error_msg` VARCHAR(255) DEFAULT NULL "
                              "COMMENT '失败原因摘要' AFTER `status`"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE `analysis_records` {ddl}")
                    conn.commit()
                except pymysql.err.OperationalError as e:
                    if e.args[0] in (1060, 1061):
                        conn.rollback()
                    else:
                        raise
    finally:
        conn.close()

def ensure_analysis_quota_source_column():
    """幂等：给 analysis_records 补 quota_source 列（区分「走的哪条配额通道」）。

    为什么必须有：赠送额度（users.bonus_*）与每日/每月额度是**两条独立通道**，
    但扣减时二者都会留下一条 analysis_records —— 而每日/每月用量正是数这张表。
    结果是「用 1 次赠送同时烧掉 1 次每日/每月额度」，用户在个人中心看到
    「剩余 = 每日 + 每月 + 赠送」却实际拿不到这么多，属于前台承诺与后台口径不一致。
    标记来源后，计数时把 bonus 记录排除掉，两条通道才真正互不侵占。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "ALTER TABLE `analysis_records` "
                    "ADD COLUMN `quota_source` VARCHAR(16) NOT NULL DEFAULT 'daily' "
                    "COMMENT 'daily=计入每日/每月额度 / bonus=消耗一次性赠送，不计入' "
                    "AFTER `status`"
                )
                conn.commit()
            except pymysql.err.OperationalError as e:
                if e.args[0] in (1060, 1061):
                    conn.rollback()
                else:
                    raise
    finally:
        conn.close()

def ensure_stocks_table():
    """幂等：创建 stocks 股票全量代码表（A股+港股）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `stocks` (
                    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `code` VARCHAR(16) NOT NULL,
                    `ts_code` VARCHAR(16) DEFAULT NULL,
                    `name` VARCHAR(64) NOT NULL,
                    `market` VARCHAR(8) NOT NULL,
                    `exchange` VARCHAR(12) DEFAULT NULL,
                    `list_status` VARCHAR(4) NOT NULL DEFAULT 'L',
                    `updated_at` DATETIME NOT NULL,
                    PRIMARY KEY (`id`),
                    UNIQUE KEY `uk_code_market` (`code`, `market`),
                    KEY `idx_name` (`name`),
                    KEY `idx_ts_code` (`ts_code`),
                    KEY `idx_market_status` (`market`, `list_status`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='股票全量代码表（A股+港股）'"""
            )
        conn.commit()
    finally:
        conn.close()

def upsert_stocks(rows):
    """批量 upsert 股票列表。rows: [{code, ts_code, name, market, exchange, list_status}, ...]"""
    if not rows:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = (
                "INSERT INTO `stocks` (`code`, `ts_code`, `name`, `market`, `exchange`, `list_status`, `updated_at`) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE `ts_code`=VALUES(`ts_code`), `name`=VALUES(`name`), "
                "`exchange`=VALUES(`exchange`), `list_status`=VALUES(`list_status`), `updated_at`=VALUES(`updated_at`)"
            )
            now = datetime.datetime.now()
            data = [
                (r["code"], r.get("ts_code"), r["name"], r["market"], r.get("exchange"),
                 r.get("list_status", "L"), now)
                for r in rows
            ]
            step = 500
            for i in range(0, len(data), step):
                cur.executemany(sql, data[i:i + step])
            conn.commit()
        return len(data)
    finally:
        conn.close()

def search_stocks(q, limit=10):
    """按名称 / 代码 / ts_code 模糊匹配已上市股票。返回 [{code,ts_code,name,market,exchange}, ...]

    ⚠️ 2026-10-03 排序修正：旧版只按 `code ASC` 排，「同名不同股」时纯属碰运气对。
       改成「精确名 > 名称前缀 > 其余包含」，同级再按代码：
       输入「华兰」时，库里三个「华兰生物/华兰疫苗/华兰皮康」，
       联想首位必须是**前缀完全对得上且最接近**的那只，而不是碰巧代码小的那只。
    """
    q = (q or "").strip()
    if not q:
        return []
    like = "%" + q + "%"
    prefix = q + "%"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `code`, `ts_code`, `name`, `market`, `exchange` FROM `stocks` "
                "WHERE `list_status`='L' AND (`name` LIKE %s OR `code` LIKE %s OR `ts_code` LIKE %s) "
                "ORDER BY CASE WHEN `name` = %s THEN 0 "
                "              WHEN `name` LIKE %s THEN 1 "
                "              WHEN `code` = %s THEN 2 ELSE 3 END, "
                "         `market`='A' DESC, `code` ASC LIMIT %s",
                (like, like, like, q, prefix, q, int(limit)),
            )
            return cur.fetchall()
    finally:
        conn.close()

def list_all_stock_basics():
    """返回全量上市股票的 (ts_code, code, name) 列表，不走分页。

    用途：给 data_service 的股票列表兜底缓存用（list_stocks 有 100 条/页上限，
    用它分页拉全量既慢又容易写错）。数据量约 5.5k 行，一次取回可接受。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `ts_code`, `code`, `name` FROM `stocks` "
                "WHERE `list_status`='L' ORDER BY `code` ASC"
            )
            return cur.fetchall()
    finally:
        conn.close()

def get_site_stats():
    """站点真实统计数字（供价格页「数据说话」等展示用，必须真实可核验）。

    只统计能真查出来的客观指标，**不含**「分析准确率」之类无法验证、
    且与免责声明相冲突的宣传口径。
    """
    conn = get_conn()
    stats = {
        "stock_count": 0, "user_count": 0, "report_count": 0, "news_count": 0,
    }
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM `stocks` WHERE `list_status`='L'")
            stats["stock_count"] = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute("SELECT COUNT(*) AS n FROM `users`")
            stats["user_count"] = int((cur.fetchone() or {}).get("n") or 0)
            try:
                cur.execute("SELECT COUNT(*) AS n FROM `analysis_records`")
                stats["report_count"] = int((cur.fetchone() or {}).get("n") or 0)
            except Exception:
                stats["report_count"] = 0
            try:
                cur.execute("SELECT COUNT(*) AS n FROM `news`")
                stats["news_count"] = int((cur.fetchone() or {}).get("n") or 0)
            except Exception:
                stats["news_count"] = 0
    except Exception as e:
        print(f"[db] get_site_stats error: {e}")
    finally:
        conn.close()
    return stats

def get_stock_by_ts_code(ts_code):
    """按规范 ts_code（如 600519.SH）精确查一只已上市股票。

    返回 {code,ts_code,name,market,exchange} 或 None。
    用于写入类操作（如加入自选）的存在性校验 —— 不能只靠 6 位数字本地推演后缀，
    否则 999999 这种不存在的代码也会被当成合法股票写库。
    """
    ts_code = (ts_code or "").strip().upper()
    if not ts_code:
        return None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `code`, `ts_code`, `name`, `market`, `exchange` FROM `stocks` "
                "WHERE `ts_code`=%s LIMIT 1",
                (ts_code,),
            )
            return cur.fetchone()
    finally:
        conn.close()

def count_stocks():
    """返回 {total, A, HK}（按 list_status='L' 统计）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `market`, COUNT(*) AS cnt FROM `stocks` WHERE `list_status`='L' GROUP BY `market`"
            )
            rows = cur.fetchall()
        stat = {"total": 0, "A": 0, "HK": 0}
        for r in rows:
            m = r["market"]
            c = r["cnt"]
            stat[m] = c
            stat["total"] += c
        return stat
    finally:
        conn.close()

def list_stocks(page=1, per_page=20, market=None, q=None, status="L"):
    """分页浏览股票库。返回 (total, rows)。

    Args:
        page: 页码（1 起）
        per_page: 每页条数（上限 100）
        market: 市场筛选 'A' / 'HK' / None 全部
        q: 关键词（名称/代码/ts_code 模糊匹配）
        status: 上市状态 L上市/D退市/P暂停，None 或 'ALL' 表示全部
    """
    page = max(1, int(page or 1))
    per_page = min(100, max(1, int(per_page or 20)))
    where, args = [], []
    if market in ("A", "HK"):
        where.append("`market`=%s")
        args.append(market)
    if status and status != "ALL":
        where.append("`list_status`=%s")
        args.append(status)
    q = (q or "").strip()
    if q:
        like = "%" + q + "%"
        where.append("(`name` LIKE %s OR `code` LIKE %s OR `ts_code` LIKE %s)")
        args.extend([like, like, like])
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM `stocks`" + cond, args)
            total = cur.fetchone()["cnt"]
            offset = (page - 1) * per_page
            cur.execute(
                "SELECT `code`, `ts_code`, `name`, `market`, `exchange`, "
                "`list_status`, `updated_at` FROM `stocks`" + cond +
                " ORDER BY `market`='A' DESC, `code` ASC LIMIT %s OFFSET %s",
                args + [per_page, offset],
            )
            rows = cur.fetchall()
        return total, rows
    finally:
        conn.close()

def insert_feedback(user_id, title, content, feedback_type="other", contact=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur.execute(
                "INSERT INTO feedback (user_id, type, title, content, contact, votes, status, created_at) "
                "VALUES (%s,%s,%s,%s,%s,0,0,%s)",
                (user_id, feedback_type, title, content, contact, now),
            )
            fid = cur.lastrowid
        conn.commit()
        return fid
    finally:
        conn.close()

def list_feedback(page=1, per_page=20, status=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = ""
            params = []
            if status is not None:
                where = "WHERE status=%s"
                params.append(int(status))
            cur.execute(f"SELECT COUNT(*) AS c FROM feedback {where}", params)
            total = cur.fetchone()["c"]
            offset = (page - 1) * per_page
            cur.execute(
                f"SELECT * FROM feedback {where} ORDER BY votes DESC, id DESC LIMIT %s OFFSET %s",
                params + [per_page, offset],
            )
            return total, list(cur.fetchall())
    finally:
        conn.close()

def vote_feedback(fid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE feedback SET votes=votes+1 WHERE id=%s", (fid,))
            if cur.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
            cur.execute("SELECT votes FROM feedback WHERE id=%s", (fid,))
            row = cur.fetchone()
            return row["votes"] if row else None
    finally:
        conn.close()

def get_admin_stats():
    """后台仪表盘统计：用户/会员/分析/反馈概览。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            def count(sql, params=()):
                cur.execute(sql, params)
                return cur.fetchone()["c"]
            today = datetime.date.today().isoformat()
            return {
                "users_total": count("SELECT COUNT(*) AS c FROM users"),
                "users_today": count(
                    "SELECT COUNT(*) AS c FROM users WHERE substr(created_at,1,10)=%s", (today,)
                ),
                "vip_total": count("SELECT COUNT(*) AS c FROM users WHERE membership_level>=1"),
                "analyses_total": count("SELECT COUNT(*) AS c FROM analysis_records"),
                "analyses_today": count(
                    "SELECT COUNT(*) AS c FROM analysis_records WHERE substr(created_at,1,10)=%s", (today,)
                ),
                "feedback_total": count("SELECT COUNT(*) AS c FROM feedback"),
                "feedback_votes": count("SELECT COALESCE(SUM(votes),0) AS c FROM feedback"),
            }
    finally:
        conn.close()

_EMAIL_DISPLAY_SQL = (
    "CASE WHEN INSTR(COALESCE(u.email,''), '@phone.local') > 0 "
    "     THEN CONCAT(COALESCE(u.phone, ''), '（手机账号）') "
    "     ELSE COALESCE(u.email, '') END AS email_display"
)

def list_users(page=1, per_page=20):
    """后台用户列表（脱敏：不含密码/盐）。

    额外返回 email_display 派生列供列表展示用；email 保持原值供编辑表单使用。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM users")
            total = cur.fetchone()["c"]
            offset = (page - 1) * per_page
            cur.execute(
                "SELECT u.id, u.email, u.nickname, u.membership_level, u.membership_expiry, "
                "u.points, u.invite_code, u.is_admin, u.status, u.phone, u.phone_verified, "
                "u.created_at, " + _EMAIL_DISPLAY_SQL + " "
                "FROM users u ORDER BY u.id DESC LIMIT %s OFFSET %s",
                (per_page, offset),
            )
            return total, list(cur.fetchall())
    finally:
        conn.close()

def list_analysis_records(page=1, per_page=20, mode=None):
    """后台分析记录（关联用户邮箱）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = ""
            params = []
            if mode:
                where = "WHERE r.mode=%s"
                params.append(mode)
            cur.execute(f"SELECT COUNT(*) AS c FROM analysis_records r {where}", params)
            total = cur.fetchone()["c"]
            offset = (page - 1) * per_page
            cur.execute(
                f"SELECT r.id, r.user_id, u.email, {_EMAIL_DISPLAY_SQL}, "
                f"r.stock_name, r.stock_code, r.mode, "
                f"r.model_id, r.status, r.created_at "
                f"FROM analysis_records r LEFT JOIN users u ON u.id=r.user_id "
                f"{where} ORDER BY r.id DESC LIMIT %s OFFSET %s",
                params + [per_page, offset],
            )
            return total, list(cur.fetchall())
    finally:
        conn.close()

def get_hot_analysis_stocks(days=7, limit=10):
    """本站最热门分析个股：统计近 N 天被分析次数最多的前 limit 只。

    只统计成功记录（status IS NULL 为兼容加字段前的老数据）。
    同一只票可能被不同用户反复分析，故按 stock_code 分组计数。
    返回 [{'stock_code','stock_name','cnt','last_at'}, ...]
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.stock_code, "
                "       MAX(NULLIF(TRIM(COALESCE(r.stock_name,'')),'')) AS stock_name, "
                "       COUNT(*) AS cnt, "
                "       MAX(r.created_at) AS last_at "
                "FROM analysis_records r "
                "WHERE r.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY) "
                "  AND r.stock_code IS NOT NULL AND TRIM(r.stock_code) <> '' "
                "  AND (r.status IS NULL OR r.status = 'ok') "
                "GROUP BY r.stock_code "
                "ORDER BY cnt DESC, last_at DESC "
                "LIMIT %s",
                (int(days), int(limit)),
            )
            rows = list(cur.fetchall())
    finally:
        conn.close()
    out = []
    for r in rows:
        code = (r.get("stock_code") or "").strip()
        if not code:
            continue
        last = r.get("last_at")
        out.append({
            "stock_code": code,
            "stock_name": (r.get("stock_name") or "").strip() or code,
            "cnt": int(r.get("cnt") or 0),
            "last_at": last.strftime("%Y-%m-%d %H:%M") if hasattr(last, "strftime") else str(last or ""),
        })
    return out

def update_feedback_status(fid, status):
    """后台更新反馈状态（0待处理/1开发中/2已上线）。返回受影响行数。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE feedback SET status=%s WHERE id=%s", (int(status), fid))
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()

def table_list():
    """返回当前库所有表名（用于校验建表结果）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            return [list(r.values())[0] for r in cur.fetchall()]
    finally:
        conn.close()

def insert_login_log(user_id, email, success, ip, user_agent, reason=None):
    """写入一条登录/登出审计记录。success=1 成功 / 0 失败。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO login_logs
                   (user_id, email, success, ip, user_agent, reason, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (user_id, email, 1 if success else 0, ip, user_agent, reason, _now()),
            )
        conn.commit()
    finally:
        conn.close()

def list_login_logs(page=1, per_page=20, success=None):
    """后台登录日志列表（success 过滤：1/0/None 全部）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = ""
            params = []
            if success is not None:
                where = "WHERE success=%s"
                params.append(1 if success else 0)
            cur.execute(f"SELECT COUNT(*) AS c FROM login_logs {where}", params)
            total = cur.fetchone()["c"]
            offset = (page - 1) * per_page
            cur.execute(
                f"""SELECT id, user_id, email, success, ip, user_agent, reason, created_at
                    FROM login_logs {where} ORDER BY id DESC LIMIT %s OFFSET %s""",
                params + [per_page, offset],
            )
            return total, list(cur.fetchall())
    finally:
        conn.close()

def insert_membership_order(order_no, user_id, plan_code, level, amount, currency,
                             payment_method, payment_status, start_at, end_at, days, remark):
    """写入一条会员订单（开通/续费）。payment_status: 0待付 1已付 2退款 3关闭。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO membership_orders
                   (order_no, user_id, plan_code, level, amount, currency,
                    payment_method, payment_status, paid_at, start_at, end_at, days, remark, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (order_no, user_id, plan_code, level, amount, currency,
                 payment_method, payment_status,
                 _now() if payment_status == 1 else None,
                 start_at, end_at, days, remark, _now()),
            )
        conn.commit()
    finally:
        conn.close()

def list_membership_orders(page=1, per_page=20):
    """后台会员订单列表。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM membership_orders")
            total = cur.fetchone()["c"]
            offset = (page - 1) * per_page
            cur.execute(
                """SELECT id, order_no, user_id, plan_code, level, amount, currency,
                          payment_method, payment_status, start_at, end_at, days, remark, created_at
                   FROM membership_orders ORDER BY id DESC LIMIT %s OFFSET %s""",
                (per_page, offset),
            )
            return total, list(cur.fetchall())
    finally:
        conn.close()

def insert_invite_record(inviter_id, invitee_id, invite_code, reward_days, reward_level):
    """写入一条邀请奖励记录（注册时实时落库）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO invite_records
                   (inviter_id, invitee_id, invite_code, reward_days, reward_level, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (inviter_id, invitee_id, invite_code, reward_days, reward_level, _now()),
            )
        conn.commit()
    finally:
        conn.close()

def list_invite_records(page=1, per_page=20):
    """后台邀请记录列表。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM invite_records")
            total = cur.fetchone()["c"]
            offset = (page - 1) * per_page
            cur.execute(
                """SELECT r.id, r.inviter_id, r.invitee_id, r.invite_code, r.reward_days,
                          r.reward_level, r.created_at,
                          u1.email AS inviter_email, u2.email AS invitee_email
                   FROM invite_records r
                   LEFT JOIN users u1 ON u1.id=r.inviter_id
                   LEFT JOIN users u2 ON u2.id=r.invitee_id
                   ORDER BY r.id DESC LIMIT %s OFFSET %s""",
                (per_page, offset),
            )
            return total, list(cur.fetchall())
    finally:
        conn.close()

def _now():
    """MySQL DATETIME 友好格式（空格分隔）。"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _serialize_row(row):
    """把 DB 行转 dict，并把日期类型统一序列化为字符串（供 JSON 返回，避免 datetime 无法序列化）。"""
    if not row:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime.datetime):
            d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, datetime.date):
            d[k] = v.strftime("%Y-%m-%d")
    return d

def ensure_bonus_logs_table():
    """幂等：创建 bonus_logs 配额流水表（管理员手动补/扣一次性赠送余量的审计轨迹）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `bonus_logs` (
                    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `user_id` BIGINT UNSIGNED NOT NULL COMMENT '目标用户',
                    `admin_id` BIGINT UNSIGNED DEFAULT NULL COMMENT '操作管理员 user.id',
                    `delta_normal` INT NOT NULL DEFAULT 0 COMMENT '普通分析余量变动（正加负减）',
                    `delta_deep` INT NOT NULL DEFAULT 0 COMMENT '深度分析余量变动（正加负减）',
                    `bonus_normal_after` INT NOT NULL DEFAULT 0 COMMENT '调整后普通余量',
                    `bonus_deep_after` INT NOT NULL DEFAULT 0 COMMENT '调整后深度余量',
                    `reason` VARCHAR(255) DEFAULT '' COMMENT '调整原因',
                    `created_at` DATETIME NOT NULL,
                    PRIMARY KEY (`id`),
                    KEY `idx_user` (`user_id`),
                    KEY `idx_created` (`created_at`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='配额手动调整流水（审计轨迹）'"""
            )
        conn.commit()
    finally:
        conn.close()

def adjust_bonus(uid, delta_normal=0, delta_deep=0, admin_id=None, reason=None):
    """管理员手动调整一次性赠送配额（可加可减），并写流水。

    余额用 max(0, ...) 下限钳制到 0，绝不出现负数；单条 UPDATE 保证并发下余额不错乱。
    返回 (ok, msg, new_balances)。new_balances 形如 {"bonus_normal": n, "bonus_deep": n}。
    """
    try:
        dn = int(delta_normal or 0)
        dd = int(delta_deep or 0)
    except (TypeError, ValueError):
        return False, "调整量必须为整数", None
    if dn == 0 and dd == 0:
        return False, "调整量不能为 0", None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, bonus_normal, bonus_deep FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
            if not row:
                return False, "用户不存在", None
            bn = int(row.get("bonus_normal") or 0)
            bd = int(row.get("bonus_deep") or 0)
            nbn = max(0, bn + dn)
            nbd = max(0, bd + dd)
            cur.execute(
                "UPDATE users SET bonus_normal=%s, bonus_deep=%s WHERE id=%s", (nbn, nbd, uid)
            )
            cur.execute(
                "INSERT INTO bonus_logs "
                "(user_id, admin_id, delta_normal, delta_deep, bonus_normal_after, bonus_deep_after, reason, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (uid, admin_id, dn, dd, nbn, nbd, (reason or "")[:255], _now()),
            )
        conn.commit()
        return True, "已调整", {"bonus_normal": nbn, "bonus_deep": nbd}
    finally:
        conn.close()

def list_bonus_logs(uid=None, page=1, per_page=20):
    """后台配额流水列表。uid 非 None 时只看该用户的流水；否则全量（供全局审计）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = ""
            params = []
            if uid is not None:
                where = " WHERE bl.user_id=%s"
                params.append(uid)
            cur.execute("SELECT COUNT(*) AS c FROM bonus_logs bl" + where, params)
            total = cur.fetchone()["c"]
            offset = (page - 1) * per_page
            cur.execute(
                "SELECT bl.id, bl.user_id, bl.admin_id, bl.delta_normal, bl.delta_deep, "
                "bl.bonus_normal_after, bl.bonus_deep_after, bl.reason, bl.created_at, "
                + _EMAIL_DISPLAY_SQL + ", "
                "a.nickname AS admin_nickname "
                "FROM bonus_logs bl "
                "LEFT JOIN users u ON u.id=bl.user_id "
                "LEFT JOIN users a ON a.id=bl.admin_id" + where +
                " ORDER BY bl.id DESC LIMIT %s OFFSET %s",
                params + [per_page, offset],
            )
            return total, [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()

def get_user_profile(uid):
    """聚合单个用户的完整画像（后台「用户详情」下钻用）。

    返回 dict：基本信息 + 统计 + 最近记录（分析/订单/邀请/登录日志/反馈/配额流水）。
    用户不存在返回 None。
    """
    conn = get_conn()
    profile = {
        "user": None, "stats": {}, "analyses": [], "orders": [],
        "invites": [], "login_logs": [], "feedback": [], "bonus_logs": [],
    }
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
            user = cur.fetchone()
            if not user:
                return None
            profile["user"] = _serialize_row(user)

            today = datetime.date.today().isoformat()
            def one(sql, *args):
                cur.execute(sql, args)
                return int((cur.fetchone() or {}).get("c") or 0)

            profile["stats"]["analyses_ok"] = one(
                "SELECT COUNT(*) AS c FROM analysis_records WHERE user_id=%s AND (status IS NULL OR status='ok')", uid)
            profile["stats"]["analyses_total"] = one(
                "SELECT COUNT(*) AS c FROM analysis_records WHERE user_id=%s", uid)
            profile["stats"]["analyses_today"] = one(
                "SELECT COUNT(*) AS c FROM analysis_records WHERE user_id=%s AND substr(created_at,1,10)=%s", uid, today)
            profile["stats"]["invited_count"] = one(
                "SELECT COUNT(*) AS c FROM invite_records WHERE inviter_id=%s", uid)
            profile["stats"]["orders_count"] = one(
                "SELECT COUNT(*) AS c FROM membership_orders WHERE user_id=%s", uid)
            profile["stats"]["feedback_count"] = one(
                "SELECT COUNT(*) AS c FROM feedback WHERE user_id=%s", uid)

            cur.execute(
                "SELECT r.id, r.stock_name, r.stock_code, r.mode, r.model_id, r.preference, r.status, r.created_at "
                "FROM analysis_records r WHERE r.user_id=%s ORDER BY r.id DESC LIMIT 10", (uid,))
            profile["analyses"] = [_serialize_row(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT id, order_no, plan_code, level, amount, currency, payment_method, payment_status, "
                "start_at, end_at, days, remark, created_at "
                "FROM membership_orders WHERE user_id=%s ORDER BY id DESC LIMIT 10", (uid,))
            profile["orders"] = [_serialize_row(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT r.id, r.inviter_id, r.invitee_id, r.reward_days, r.reward_level, r.created_at, "
                "u2.nickname AS invitee_nickname, u2.email AS invitee_email, u2.phone AS invitee_phone "
                "FROM invite_records r LEFT JOIN users u2 ON u2.id=r.invitee_id "
                "WHERE r.inviter_id=%s ORDER BY r.id DESC LIMIT 10", (uid,))
            profile["invites"] = [_serialize_row(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT id, email, success, ip, user_agent, reason, created_at "
                "FROM login_logs WHERE user_id=%s ORDER BY id DESC LIMIT 10", (uid,))
            profile["login_logs"] = [_serialize_row(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT id, type, title, content, votes, status, created_at "
                "FROM feedback WHERE user_id=%s ORDER BY id DESC LIMIT 10", (uid,))
            profile["feedback"] = [_serialize_row(r) for r in cur.fetchall()]

            try:
                cur.execute(
                    "SELECT id, admin_id, delta_normal, delta_deep, bonus_normal_after, bonus_deep_after, reason, created_at "
                    "FROM bonus_logs WHERE user_id=%s ORDER BY id DESC LIMIT 20", (uid,))
                profile["bonus_logs"] = [_serialize_row(r) for r in cur.fetchall()]
            except Exception:
                profile["bonus_logs"] = []

            inviter_id = profile["user"].get("invited_by")
            if inviter_id:
                cur.execute("SELECT id, nickname, email, phone FROM users WHERE id=%s", (inviter_id,))
                profile["inviter"] = _serialize_row(cur.fetchone())
            else:
                profile["inviter"] = None
    finally:
        conn.close()
    return profile

def upsert_market_vote(user_id, trade_date, vote):
    """投票（每用户每交易日一票，可改票）。vote: 1=看涨 / 0=看跌。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO `market_votes` (`user_id`,`trade_date`,`vote`,`created_at`) "
                "VALUES (%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE `vote`=VALUES(`vote`), `updated_at`=NOW()",
                (user_id, trade_date, 1 if vote else 0, _now()),
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"[db] upsert_market_vote error: {e}")
        return False
    finally:
        conn.close()

def get_market_vote_stats(trade_date):
    """指定交易日的投票统计：{up, down, total, up_pct}。无票时 total=0。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT SUM(`vote`=1) AS up_cnt, SUM(`vote`=0) AS down_cnt, COUNT(*) AS total "
                "FROM `market_votes` WHERE `trade_date`=%s",
                (trade_date,),
            )
            r = cur.fetchone() or {}
        up = int(r.get("up_cnt") or 0)
        down = int(r.get("down_cnt") or 0)
        total = int(r.get("total") or 0)
        return {
            "up": up,
            "down": down,
            "total": total,
            "up_pct": round(up / total * 100, 1) if total else 0.0,
            "down_pct": round(down / total * 100, 1) if total else 0.0,
        }
    except Exception as e:
        print(f"[db] get_market_vote_stats error: {e}")
        return {"up": 0, "down": 0, "total": 0, "up_pct": 0.0, "down_pct": 0.0}
    finally:
        conn.close()

def get_user_market_vote(user_id, trade_date):
    """取用户当日投票：1 / 0 / None（未投）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `vote` FROM `market_votes` WHERE `user_id`=%s AND `trade_date`=%s LIMIT 1",
                (user_id, trade_date),
            )
            r = cur.fetchone()
        return None if not r else int(r["vote"])
    except Exception as e:
        print(f"[db] get_user_market_vote error: {e}")
        return None
    finally:
        conn.close()

def ensure_news_table():
    """幂等：创建 news 快讯表；并对已有表做字段迁移（新增 likes 点赞列）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `news` (
                    `gid` BIGINT UNSIGNED NOT NULL,
                    `category` VARCHAR(16) NOT NULL DEFAULT 'all',
                    `title` VARCHAR(512) NOT NULL DEFAULT '',
                    `content` TEXT,
                    `create_timestamp` BIGINT NOT NULL DEFAULT 0,
                    `news_date` DATE DEFAULT NULL,
                    `news_time` TIME DEFAULT NULL,
                    `important` TINYINT(1) NOT NULL DEFAULT 0,
                    `sentiment` VARCHAR(10) DEFAULT 'neutral',
                    `tags` VARCHAR(255) DEFAULT '',
                    `ai_comment` VARCHAR(512) DEFAULT '',
                    `likes` INT UNSIGNED NOT NULL DEFAULT 0,
                    `views` INT UNSIGNED NOT NULL DEFAULT 0,
                    `pinned` TINYINT(1) NOT NULL DEFAULT 0,
                    `created_at` DATETIME NOT NULL,
                    PRIMARY KEY (`gid`),
                    KEY `idx_create` (`create_timestamp`),
                    KEY `idx_important` (`important`),
                    KEY `idx_pinned` (`pinned`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='市场快讯（格隆汇来源，落库每小时更新，展示不写来源）'"""
            )
            for col_ddl in [
                "ADD COLUMN `likes` INT UNSIGNED NOT NULL DEFAULT 0",
                "ADD COLUMN `views` INT UNSIGNED NOT NULL DEFAULT 0",
                "ADD COLUMN `pinned` TINYINT(1) NOT NULL DEFAULT 0",
            ]:
                try:
                    cur.execute(f"ALTER TABLE `news` {col_ddl}")
                except Exception:
                    pass
        conn.commit()
    finally:
        conn.close()

def increment_news_likes(gid, delta=1):
    """更新某条快讯的点赞数（delta 可为负，下限 0），返回最新点赞数。

    匿名点赞：不区分用户，仅维护总量；前端用 localStorage 防止重复点击。
    """
    gid = int(gid)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE `news` SET `likes` = GREATEST(0, `likes` + %s) WHERE `gid`=%s",
                (int(delta), gid),
            )
            if cur.rowcount == 0:
                return 0
            cur.execute("SELECT `likes` FROM `news` WHERE `gid`=%s", (gid,))
            row = cur.fetchone()
            conn.commit()
            return int(row["likes"]) if row else 0
    finally:
        conn.close()

def upsert_news(rows):
    """批量 upsert 快讯。rows: [{gid,category,title,content,create_timestamp,news_date,news_time,important,sentiment,tags,ai_comment}, ...]
    去重键为 gid；important 取二者较大值（保留重大标记）。"""
    if not rows:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = (
                "INSERT INTO `news` "
                "(`gid`,`category`,`title`,`content`,`create_timestamp`,`news_date`,`news_time`,"
                "`important`,`sentiment`,`tags`,`ai_comment`,`created_at`) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE "
                "`category`=VALUES(`category`), `title`=VALUES(`title`), `content`=VALUES(`content`), "
                "`create_timestamp`=VALUES(`create_timestamp`), `news_date`=VALUES(`news_date`), `news_time`=VALUES(`news_time`), "
                "`important`=GREATEST(`important`, VALUES(`important`)), "
                "`sentiment`=VALUES(`sentiment`), `tags`=VALUES(`tags`), `ai_comment`=VALUES(`ai_comment`), "
                "`created_at`=VALUES(`created_at`)"
            )
            now = _now()
            data = [
                (
                    int(r["gid"]), r.get("category", "all"), r.get("title", "") or "",
                    r.get("content", "") or "", int(r.get("create_timestamp", 0) or 0),
                    r.get("news_date"), r.get("news_time"),
                    int(bool(r.get("important", 0))), r.get("sentiment", "neutral") or "neutral",
                    r.get("tags", "") or "", r.get("ai_comment", "") or "", now,
                )
                for r in rows
            ]
            step = 200
            for i in range(0, len(data), step):
                cur.executemany(sql, data[i:i + step])
            conn.commit()
        return len(data)
    finally:
        conn.close()

def list_news(limit=50, offset=0, important_only=False):
    """读取快讯（按发布时间倒序，置顶优先）。

    Args:
        limit: 返回条数上限（最大 200）
        offset: 偏移（用于「加载历史快讯」分页）
        important_only: 仅返回重大快讯
    """
    limit = min(200, max(1, int(limit)))
    offset = max(0, int(offset))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = ""
            args = []
            if important_only:
                where = " WHERE `important`=1"
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM `news`" + where, args
            )
            total = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT `gid`,`category`,`title`,`content`,`create_timestamp`,`news_date`,"
                "`news_time`,`important`,`sentiment`,`tags`,`ai_comment`,`likes`,`views`,`pinned` FROM `news`" + where +
                " ORDER BY `pinned` DESC, `create_timestamp` DESC LIMIT %s OFFSET %s",
                args + [limit, offset],
            )
            return total, list(cur.fetchall())
    finally:
        conn.close()

def get_news_by_gid(gid):
    """按 gid 精确取一条快讯（后台详情用）。不存在返回 None。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `gid`,`category`,`title`,`content`,`create_timestamp`,`news_date`,"
                "`news_time`,`important`,`sentiment`,`tags`,`ai_comment`,`likes`,`views`,`pinned` "
                "FROM `news` WHERE `gid`=%s LIMIT 1",
                (int(gid),),
            )
            return cur.fetchone()
    finally:
        conn.close()

def delete_news(gid):
    """删除一条快讯（后台管理）。返回受影响行数（0=不存在）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            n = cur.execute("DELETE FROM `news` WHERE `gid`=%s", (int(gid),))
        conn.commit()
        return n
    finally:
        conn.close()

def set_news_pinned(gid, pinned):
    """置顶 / 取消置顶一条快讯。返回最新 pinned 值；不存在返回 None。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            n = cur.execute(
                "UPDATE `news` SET `pinned`=%s WHERE `gid`=%s",
                (1 if pinned else 0, int(gid)),
            )
            if n == 0:
                return None
        conn.commit()
        return 1 if pinned else 0
    finally:
        conn.close()

def increment_news_views(gids):
    """批量 +1 快讯浏览量（前台列表曝光计数）。gids: 快讯 gid 列表。"""
    gids = [int(g) for g in (gids or []) if g]
    if not gids:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(gids))
            n = cur.execute(
                f"UPDATE `news` SET `views`=`views`+1 WHERE `gid` IN ({placeholders})",
                tuple(gids),
            )
        conn.commit()
        return n
    finally:
        conn.close()

def ensure_lixinger_top_list_table():
    """幂等：创建理杏仁龙虎榜汇总缓存表（按 抓取日+排序键 缓存，避免重复打 API）。

    sort_key 形如 'tatnpa_last:desc'（净买入 TOP）/ 'tatnpa_last:asc'（净卖出 TOP），
    因理杏仁 hot/t_a 单页上限 100 条，净卖出端需用升序单独拉取并分别缓存。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `lixinger_top_list` (
                    `snap_date` DATE NOT NULL,
                    `sort_key` VARCHAR(40) NOT NULL DEFAULT 'tatnpa_last:desc',
                    `stock_code` VARCHAR(12) NOT NULL,
                    `net_total_yi` DOUBLE NOT NULL DEFAULT 0,
                    `net_org_yi` DOUBLE NOT NULL DEFAULT 0,
                    `last_data_date` VARCHAR(32) DEFAULT '',
                    `created_at` DATETIME NOT NULL,
                    PRIMARY KEY (`snap_date`, `sort_key`, `stock_code`),
                    KEY `idx_sort` (`sort_key`, `snap_date`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='理杏仁龙虎榜汇总缓存（金融大数据源，按日缓存降频）'"""
            )
        conn.commit()
    finally:
        conn.close()

def upsert_lixinger_top_list(rows, snap_date, sort_key):
    """批量 upsert 龙虎榜汇总。rows: [{stock_code, net_total_yi, net_org_yi, last_data_date}, ...]"""
    if not rows:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = (
                "INSERT INTO `lixinger_top_list` "
                "(`snap_date`,`sort_key`,`stock_code`,`net_total_yi`,`net_org_yi`,`last_data_date`,`created_at`) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE "
                "`net_total_yi`=VALUES(`net_total_yi`), `net_org_yi`=VALUES(`net_org_yi`), "
                "`last_data_date`=VALUES(`last_data_date`), `created_at`=VALUES(`created_at`)"
            )
            now = _now()
            data = [
                (snap_date, sort_key, str(r.get("stock_code", "")),
                 float(r.get("net_total_yi") or 0), float(r.get("net_org_yi") or 0),
                 str(r.get("last_data_date") or ""), now)
                for r in rows
            ]
            step = 200
            for i in range(0, len(data), step):
                cur.executemany(sql, data[i:i + step])
            conn.commit()
        return len(data)
    finally:
        conn.close()

def list_lixinger_top_list(snap_date, sort_key, limit=200):
    """读取某抓取日+排序键的龙虎榜汇总（按净买入额降序）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `stock_code`,`net_total_yi`,`net_org_yi`,`last_data_date` "
                "FROM `lixinger_top_list` WHERE `snap_date`=%s AND `sort_key`=%s "
                "ORDER BY `net_total_yi` DESC LIMIT %s",
                (snap_date, sort_key, int(limit)),
            )
            return list(cur.fetchall())
    finally:
        conn.close()

def ensure_stock_detail_cache_table():
    """幂等：创建个股详情页数据缓存表。

    设计要点：
      - `cache_key` 主键，形如 `quote:600519.SH` / `section:600519.SH:financials`
        / `kline:600519.SH:lxr_fc_rights:120` / `website:www.example.com`。
      - `payload` 存 JSON 文本（LONGTEXT，容纳财报/K线等大对象）。
      - `expire_at` 到期时间；读取时若已过期仍返回，但标记 stale=1，
        由上层决定「先用旧数据渲染 + 后台异步刷新」，避免用户等待外部 API。
      - `hit_count` 便于后台观察缓存命中收益。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `stock_detail_cache` (
                    `cache_key` VARCHAR(191) NOT NULL COMMENT '缓存键',
                    `ts_code` VARCHAR(16) NOT NULL DEFAULT '' COMMENT '股票代码',
                    `section` VARCHAR(48) NOT NULL DEFAULT '' COMMENT '数据块名',
                    `payload` LONGTEXT COMMENT 'JSON 数据',
                    `ttl` INT NOT NULL DEFAULT 1800 COMMENT '有效期秒',
                    `hit_count` INT NOT NULL DEFAULT 0 COMMENT '命中次数',
                    `updated_at` DATETIME NOT NULL COMMENT '写入时间',
                    `expire_at` DATETIME NOT NULL COMMENT '过期时间',
                    PRIMARY KEY (`cache_key`),
                    KEY `idx_code_section` (`ts_code`, `section`),
                    KEY `idx_expire` (`expire_at`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='个股详情页数据缓存（降低外部 API 调用频次）'"""
            )
        conn.commit()
    finally:
        conn.close()

def get_stock_detail_cache(cache_key):
    """读取缓存。

    返回 None（无记录）或 dict：
      {"value": <反序列化后的对象>, "stale": bool, "updated_at": datetime, "age": 秒}
    过期记录也会返回，但 stale=True，交由上层做「陈旧可用 + 异步刷新」。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `payload`,`updated_at`,`expire_at` FROM `stock_detail_cache` "
                "WHERE `cache_key`=%s",
                (cache_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            try:
                value = json.loads(row["payload"]) if row["payload"] else None
            except (ValueError, TypeError):
                return None
            now = datetime.datetime.now()
            exp = row.get("expire_at")
            upd = row.get("updated_at")
            stale = bool(exp and now > exp)
            age = int((now - upd).total_seconds()) if upd else 0
            try:
                cur.execute(
                    "UPDATE `stock_detail_cache` SET `hit_count`=`hit_count`+1 "
                    "WHERE `cache_key`=%s",
                    (cache_key,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
            return {"value": value, "stale": stale, "updated_at": upd, "age": age}
    except Exception as e:
        print(f"[db] get_stock_detail_cache warn {cache_key}: {e}")
        return None
    finally:
        conn.close()

def set_stock_detail_cache(cache_key, value, ttl=1800, ts_code="", section=""):
    """写入/更新缓存。value 会被 json.dumps（date/datetime 走 str 兜底）。"""
    try:
        payload = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        print(f"[db] set_stock_detail_cache serialize fail {cache_key}: {e}")
        return False
    now = datetime.datetime.now()
    expire_at = now + datetime.timedelta(seconds=int(ttl))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO `stock_detail_cache` "
                "(`cache_key`,`ts_code`,`section`,`payload`,`ttl`,`hit_count`,`updated_at`,`expire_at`) "
                "VALUES (%s,%s,%s,%s,%s,0,%s,%s) "
                "ON DUPLICATE KEY UPDATE `payload`=VALUES(`payload`), `ttl`=VALUES(`ttl`), "
                "`updated_at`=VALUES(`updated_at`), `expire_at`=VALUES(`expire_at`)",
                (cache_key, ts_code, section, payload, int(ttl), now, expire_at),
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"[db] set_stock_detail_cache warn {cache_key}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()

def delete_stock_detail_cache(ts_code=None, section=None, cache_key=None):
    """删除缓存（后台强制刷新用）。三个条件择一或组合。"""
    where, args = [], []
    if cache_key:
        where.append("`cache_key`=%s")
        args.append(cache_key)
    if ts_code:
        where.append("`ts_code`=%s")
        args.append(ts_code)
    if section:
        where.append("`section`=%s")
        args.append(section)
    if not where:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            n = cur.execute(
                "DELETE FROM `stock_detail_cache` WHERE " + " AND ".join(where), tuple(args)
            )
        conn.commit()
        return n
    except Exception as e:
        print(f"[db] delete_stock_detail_cache warn: {e}")
        return 0
    finally:
        conn.close()

def purge_stock_detail_cache(keep_days=7):
    """清理长期不再访问的过期缓存（防止表无限膨胀）。"""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=int(keep_days))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            n = cur.execute(
                "DELETE FROM `stock_detail_cache` WHERE `expire_at` < %s", (cutoff,)
            )
        conn.commit()
        return n
    except Exception as e:
        print(f"[db] purge_stock_detail_cache warn: {e}")
        return 0
    finally:
        conn.close()

def stock_detail_cache_stats():
    """后台观测：缓存条目数 / 命中总数 / 新鲜条目数。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(`hit_count`),0) AS hits, "
                "SUM(CASE WHEN `expire_at` > NOW() THEN 1 ELSE 0 END) AS fresh "
                "FROM `stock_detail_cache`"
            )
            return cur.fetchone() or {}
    except Exception as e:
        print(f"[db] stock_detail_cache_stats warn: {e}")
        return {}
    finally:
        conn.close()

def ensure_watchlist_columns():
    """幂等：给 watchlists 表补 分组/备注/持仓 相关列（旧表 ALTER 兼容，重复列忽略）。"""
    cols = [
        ("group_name", "VARCHAR(32) NOT NULL DEFAULT '' COMMENT '分组名'"),
        ("note", "VARCHAR(255) DEFAULT NULL COMMENT '用户备注'"),
        ("cost", "DECIMAL(12,4) DEFAULT NULL COMMENT '持仓成本(元/股)'"),
        ("quantity", "INT UNSIGNED DEFAULT NULL COMMENT '持仓数量(股)'"),
    ]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for name, ddl in cols:
                try:
                    cur.execute(f"ALTER TABLE `watchlists` ADD COLUMN `{name}` {ddl}")
                except Exception:
                    pass
        conn.commit()
    finally:
        conn.close()

def ensure_disclosure_table():
    """幂等：创建 disclosure_schedule 财报披露计划表。

    数据源 DATAHUB disclosure_date（Tushare 兼容，实测 000963 返回全历史 102 行）：
      end_date=报告期(YYYYMMDD)，pre_date=预约披露日，actual_date=实际披露日，ann_date=预约公告日。
    用途：① 财报披露日历页（按 pre_date 查窗口）② 自选股「财报前 N 天」提醒
      ③ 个股页下个披露日 chip。日期一律 CHAR(8) 原样入库（与 Tushare 口径一致），
      展示层再格式化 —— 不要在 DB 层做 YYYYMMDD↔DATE 换算，容易踩时区/空值坑。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `disclosure_schedule` (
                    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `ts_code` VARCHAR(32) NOT NULL COMMENT '股票代码',
                    `stock_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '股票名称',
                    `end_date` CHAR(8) NOT NULL COMMENT '报告期 YYYYMMDD',
                    `pre_date` CHAR(8) DEFAULT NULL COMMENT '预约披露日',
                    `actual_date` CHAR(8) DEFAULT NULL COMMENT '实际披露日',
                    `ann_date` CHAR(8) DEFAULT NULL COMMENT '预约公告日',
                    `updated_at` DATETIME NOT NULL COMMENT '同步时间',
                    PRIMARY KEY (`id`),
                    UNIQUE KEY `uq_code_period` (`ts_code`, `end_date`),
                    KEY `idx_pre` (`pre_date`),
                    KEY `idx_ts` (`ts_code`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='财报披露计划（DATAHUB disclosure_date 同步）'"""
            )
        conn.commit()
    finally:
        conn.close()

def upsert_disclosure_rows(rows):
    """批量写入/更新披露计划。rows: [{ts_code, stock_name, end_date, pre_date, actual_date, ann_date}]。

    pre_date/actual_date 空串一律归一为 None（CHAR 列存空串会让 idx_pre 失效 + 判断变复杂）。
    """
    if not rows:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO disclosure_schedule "
                "(ts_code, stock_name, end_date, pre_date, actual_date, ann_date, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE "
                "stock_name=IF(VALUES(stock_name)='', stock_name, VALUES(stock_name)), pre_date=VALUES(pre_date), "
                "actual_date=VALUES(actual_date), ann_date=VALUES(ann_date), updated_at=VALUES(updated_at)",
                [
                    (
                        r["ts_code"], r.get("stock_name") or "", str(r.get("end_date") or ""),
                        (str(r.get("pre_date")) or None) if r.get("pre_date") else None,
                        (str(r.get("actual_date")) or None) if r.get("actual_date") else None,
                        (str(r.get("ann_date")) or None) if r.get("ann_date") else None,
                        _now(),
                    )
                    for r in rows
                ],
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()

def list_disclosure_window(start_yyyymmdd, end_yyyymmdd, limit=500):
    """预约披露日落在 [start, end] 的披露计划（按日期升序），供披露日历页。

    只要有预约日就展示：已实际披露的行带 actual_date，前端标注「已披露」。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ts_code, stock_name, end_date, pre_date, actual_date "
                "FROM disclosure_schedule "
                "WHERE pre_date IS NOT NULL AND pre_date >= %s AND pre_date <= %s "
                "ORDER BY pre_date ASC, ts_code ASC LIMIT %s",
                (str(start_yyyymmdd), str(end_yyyymmdd), int(limit)),
            )
            return cur.fetchall()
    finally:
        conn.close()

def get_next_disclosure(ts_code):
    """某股票最近一条「未实际披露」的计划（含已逾期跳票的），无则 None。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ts_code, stock_name, end_date, pre_date, actual_date "
                "FROM disclosure_schedule "
                "WHERE ts_code=%s AND actual_date IS NULL AND pre_date IS NOT NULL "
                "ORDER BY pre_date ASC LIMIT 1",
                (ts_code,),
            )
            return cur.fetchone()
    finally:
        conn.close()

def list_disclosure_by_stock(ts_code, limit=6):
    """某股票最近几个报告期的披露计划（按报告期倒序），供个股页。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT end_date, pre_date, actual_date FROM disclosure_schedule "
                "WHERE ts_code=%s ORDER BY end_date DESC LIMIT %s",
                (ts_code, int(limit)),
            )
            return cur.fetchall()
    finally:
        conn.close()

def list_distinct_watch_codes(limit=200):
    """全部自选股去重后的 ts_code 列表（披露同步的种子：优先保证用户关心的票在日历里）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ts_code FROM watchlists ORDER BY ts_code ASC LIMIT %s",
                (int(limit),),
            )
            return [r["ts_code"] for r in cur.fetchall()]
    finally:
        conn.close()

def ensure_watch_alerts_table():
    """幂等：创建 watch_alerts 提醒规则表（通用结构，市值/价格/涨跌幅/PE 共用）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `watch_alerts` (
                    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户',
                    `ts_code` VARCHAR(32) NOT NULL COMMENT '股票代码',
                    `stock_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '股票名称',
                    `metric` VARCHAR(16) NOT NULL DEFAULT 'total_mv' COMMENT '监控指标: total_mv/price/pct_chg/pe_ttm',
                    `operator` VARCHAR(8) NOT NULL DEFAULT 'gte' COMMENT '比较符: gte/lte/between',
                    `threshold` DECIMAL(16,4) NOT NULL DEFAULT 0 COMMENT '阈值(主)',
                    `threshold2` DECIMAL(16,4) DEFAULT NULL COMMENT '阈值(区间上界, between 用)',
                    `enabled` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
                    `triggered` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已触发(去重)',
                    `last_value` DECIMAL(16,4) DEFAULT NULL COMMENT '最近一次观测值',
                    `triggered_at` DATETIME DEFAULT NULL COMMENT '最近触发时间',
                    `created_at` DATETIME NOT NULL,
                    PRIMARY KEY (`id`),
                    KEY `idx_user` (`user_id`),
                    KEY `idx_enabled` (`enabled`, `triggered`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='自选股提醒规则表'"""
            )
        conn.commit()
    finally:
        conn.close()

def add_alert(uid, ts_code, stock_name, metric, operator, threshold, threshold2=None):
    """新增提醒规则，返回 (ok, msg, alert_id)。"""
    metric = (metric or "total_mv").strip()
    op = (operator or "gte").strip()
    if metric not in ("val_low", "total_mv", "price", "pct_chg", "pe_ttm",
                      "pb", "pb_y5", "disclosure"):
        return False, "不支持的指标", None
    if metric == "val_low":
        op = "lte"
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO watch_alerts "
                    "(user_id, ts_code, stock_name, metric, operator, threshold, enabled, triggered, created_at) "
                    "VALUES (%s,%s,%s,'val_low','lte',0,1,0,%s)",
                    (uid, ts_code, stock_name, _now()),
                )
                aid = cur.lastrowid
            conn.commit()
            return True, "已设置「跌破研报合理价」提醒（该股需先做过深度研报）", aid
        finally:
            conn.close()
    if metric == "disclosure":
        op = "lte"
        try:
            thr = int(float(threshold))
        except (TypeError, ValueError):
            return False, "提前天数必须为数字", None
        if not (1 <= thr <= 60):
            return False, "提前天数需在 1~60 之间", None
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO watch_alerts "
                    "(user_id, ts_code, stock_name, metric, operator, threshold, enabled, triggered, created_at) "
                    "VALUES (%s,%s,%s,'disclosure','lte',%s,1,0,%s)",
                    (uid, ts_code, stock_name, thr, _now()),
                )
                aid = cur.lastrowid
            conn.commit()
            return True, "已设置财报提醒", aid
        finally:
            conn.close()
    if op not in ("gte", "lte", "between"):
        return False, "不支持的比较符", None
    try:
        thr = float(threshold)
    except (TypeError, ValueError):
        return False, "阈值必须为数字", None
    thr2 = None
    if op == "between":
        try:
            thr2 = float(threshold2)
        except (TypeError, ValueError):
            return False, "区间上界必须为数字", None
        if thr2 <= thr:
            return False, "区间上界须大于下界", None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO watch_alerts "
                "(user_id, ts_code, stock_name, metric, operator, threshold, threshold2, enabled, triggered, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,1,0,%s)",
                (uid, ts_code, stock_name, metric, op, thr, thr2, _now()),
            )
            aid = cur.lastrowid
        conn.commit()
        return True, "已设置提醒", aid
    finally:
        conn.close()

def list_alerts(uid, ts_code=None, enabled_only=False):
    """某用户（可选按股票）的提醒规则列表，倒序。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where = ["user_id=%s"]
            params = [uid]
            if ts_code:
                where.append("ts_code=%s")
                params.append(ts_code)
            if enabled_only:
                where.append("enabled=1")
            cur.execute(
                "SELECT * FROM watch_alerts WHERE " + " AND ".join(where) + " ORDER BY id DESC",
                params,
            )
            return [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()

def get_alert(aid, uid=None):
    """取单条提醒（uid 传了则校验归属，越权返回 None）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if uid is not None:
                cur.execute("SELECT * FROM watch_alerts WHERE id=%s AND user_id=%s", (aid, uid))
            else:
                cur.execute("SELECT * FROM watch_alerts WHERE id=%s", (aid,))
            return _serialize_row(cur.fetchone())
    finally:
        conn.close()

def update_alert(aid, uid, **fields):
    """更新提醒规则（enabled/triggered/threshold 等），白名单字段防注入。"""
    allowed = {"metric", "operator", "threshold", "threshold2", "enabled", "triggered",
               "last_value", "triggered_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False, "无可更新字段"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"`{k}`=%s" for k in updates)
            vals = list(updates.values())
            vals.append(aid)
            vals.append(uid)
            cur.execute(f"UPDATE watch_alerts SET {sets} WHERE id=%s AND user_id=%s", vals)
        conn.commit()
        return True, "已更新"
    finally:
        conn.close()

def delete_alert(aid, uid):
    """删除提醒规则，返回是否删到。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM watch_alerts WHERE id=%s AND user_id=%s", (aid, uid))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def list_all_enabled_alerts():
    """调度用：拉取所有启用且未触发的提醒规则（跨用户）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM watch_alerts WHERE enabled=1 AND triggered=0")
            return [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()

def count_unread_alerts(uid):
    """某用户已触发但未读的提醒条数（站内红点）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM watch_alerts WHERE user_id=%s AND triggered=1", (uid,))
            return int((cur.fetchone() or {}).get("c") or 0)
    finally:
        conn.close()

def list_triggered_alerts(uid, limit=20):
    """某用户最近触发的提醒（铃铛下拉列表）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM watch_alerts WHERE user_id=%s AND triggered=1 "
                "ORDER BY triggered_at DESC LIMIT %s",
                (uid, limit),
            )
            return [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()

def update_watch_meta(uid, ts_code, **fields):
    """更新自选股元信息（group_name/note/cost/quantity），白名单字段。"""
    allowed = {"group_name", "note", "cost", "quantity"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False, "无可更新字段"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"`{k}`=%s" for k in updates)
            vals = list(updates.values())
            vals += [uid, ts_code]
            cur.execute(f"UPDATE watchlists SET {sets} WHERE user_id=%s AND ts_code=%s", vals)
        conn.commit()
        return True, "已更新"
    finally:
        conn.close()

BACKTEST_PREFERENCES = ("long_term_value", "comprehensive", "deep_value")

def ensure_analysis_valuation_table():
    """幂等：创建回测估值台账表。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `analysis_valuation` (
                    `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `record_id`      BIGINT UNSIGNED DEFAULT NULL COMMENT '关联 analysis_records.id（可回溯研报全文）',
                    `user_id`        BIGINT UNSIGNED NOT NULL COMMENT '分析用户',
                    `stock_name`     VARCHAR(64)  DEFAULT NULL COMMENT '股票名称',
                    `stock_code`     VARCHAR(32)  DEFAULT NULL COMMENT '股票代码（ts_code）',
                    `analysis_date`  DATE         NOT NULL     COMMENT '分析日期',
                    `val_low`        DECIMAL(16,2) DEFAULT NULL COMMENT '合理市值下限（亿元）',
                    `val_high`       DECIMAL(16,2) DEFAULT NULL COMMENT '合理市值上限（亿元）',
                    `val_mid`        DECIMAL(16,2) DEFAULT NULL COMMENT '合理市值中枢（亿元，两端均值）',
                    `score`          DECIMAL(3,1)  DEFAULT NULL COMMENT '性价比评分 0-10',
                    `model`          VARCHAR(64)  DEFAULT NULL COMMENT '使用模型（别名，给人看）',
                    `model_id`       VARCHAR(32)  DEFAULT NULL COMMENT '使用模型（内部ID，给程序用）',
                    `preference`     VARCHAR(32)  DEFAULT NULL COMMENT '投资偏好ID',
                    `verdict`        VARCHAR(16)  DEFAULT NULL COMMENT '结论：低估/合理/高估/回避',
                    `confidence`     TINYINT      DEFAULT NULL COMMENT '模型自评置信度 1-5',
                    `horizon`        VARCHAR(16)  DEFAULT NULL COMMENT '建议持有周期（6m/12m/24m...）',
                    `key_reason`     VARCHAR(255) DEFAULT NULL COMMENT '评分核心依据（模型一句话）',
                    `mc_at`          DECIMAL(16,2) DEFAULT NULL COMMENT '分析时点总市值（亿元，回测基准锚点）',
                    `price_at`       DECIMAL(12,3) DEFAULT NULL COMMENT '分析时点股价（元）',
                    `pe_ttm_at`      DECIMAL(12,3) DEFAULT NULL COMMENT '分析时点 PE(TTM)',
                    `pb_at`          DECIMAL(12,3) DEFAULT NULL COMMENT '分析时点 PB',
                    `upside_pct`     DECIMAL(8,2)  DEFAULT NULL COMMENT '中枢相对当前市值的预期空间（%）',
                    `panel_chars`    INT          DEFAULT 0    COMMENT '数据面板字符数（prompt 规模，解释模型表现差异）',
                    `panel_hash`     VARCHAR(40)  DEFAULT NULL COMMENT '数据面板指纹（识别同参数重跑）',
                    `panel_text`     MEDIUMTEXT   DEFAULT NULL COMMENT '分析时喂给模型的完整数据面板（可复现）',
                    `detail`         MEDIUMTEXT   DEFAULT NULL COMMENT '详情：数据面板参数快照（数据组/字段/偏好/模型，JSON）',
                    `raw_json`       TEXT         DEFAULT NULL COMMENT '模型返回的原始回测 JSON',
                    `fallback`       TINYINT      NOT NULL DEFAULT 0 COMMENT '1=曾触发模型回退（影响结论可比性）',
                    `duration_ms`    INT          DEFAULT NULL COMMENT '分析总耗时（毫秒）',
                    `px_20d`         DECIMAL(12,3) DEFAULT NULL COMMENT '回填：20 交易日后收盘价',
                    `px_60d`         DECIMAL(12,3) DEFAULT NULL COMMENT '回填：60 交易日后收盘价',
                    `px_120d`        DECIMAL(12,3) DEFAULT NULL COMMENT '回填：120 交易日后收盘价',
                    `px_250d`        DECIMAL(12,3) DEFAULT NULL COMMENT '回填：250 交易日后收盘价',
                    `ret_20d`        DECIMAL(8,2)  DEFAULT NULL COMMENT '回填：20 交易日实际涨跌幅（%）',
                    `ret_60d`        DECIMAL(8,2)  DEFAULT NULL COMMENT '回填：60 交易日实际涨跌幅（%）',
                    `ret_120d`       DECIMAL(8,2)  DEFAULT NULL COMMENT '回填：120 交易日实际涨跌幅（%）',
                    `ret_250d`       DECIMAL(8,2)  DEFAULT NULL COMMENT '回填：250 交易日实际涨跌幅（%）',
                    `backfilled_at`  DATETIME     DEFAULT NULL COMMENT '回填时间',
                    `created_at`     DATETIME     NOT NULL,
                    PRIMARY KEY (`id`),
                    KEY `idx_created` (`created_at`),
                    KEY `idx_stock_date` (`stock_code`, `analysis_date`),
                    KEY `idx_pref_model` (`preference`, `model_id`),
                    KEY `idx_score` (`score`),
                    KEY `idx_record` (`record_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='回测估值台账（合理市值区间 + 性价比评分，供未来回测模型靠谱程度）'"""
            )
        conn.commit()
    finally:
        conn.close()

def save_analysis_valuation(*, record_id=None, user_id=None, stock_name=None, stock_code=None,
                            model=None, model_id=None, preference=None, bt=None,
                            panel_text=None, detail=None, fallback=0, duration_ms=None,
                            analysis_date=None):
    """写入一条回测估值记录。bt 为 parse_backtest_json() 的返回值。

    ⚠️ 调用方必须保证 preference 属于 BACKTEST_PREFERENCES（其余偏好没有估值结论）。
    ⚠️ bt 为 None（模型没吐 JSON / JSON 解析失败）时**直接返回 None 不落库** ——
       宁可缺一条，也不要存一条 score 全空的废数据污染回测样本。
    """
    if not bt:
        return None
    if preference and preference not in BACKTEST_PREFERENCES:
        return None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO analysis_valuation "
                "(record_id, user_id, stock_name, stock_code, analysis_date, "
                " val_low, val_high, val_mid, score, model, model_id, preference, "
                " verdict, confidence, horizon, key_reason, "
                " mc_at, price_at, pe_ttm_at, pb_at, upside_pct, "
                " panel_chars, panel_hash, panel_text, detail, raw_json, "
                " fallback, duration_ms, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    record_id,
                    user_id,
                    (stock_name or "")[:64] or None,
                    (stock_code or "")[:32] or None,
                    analysis_date or datetime.datetime.now().strftime("%Y-%m-%d"),
                    bt.get("valuation_low"),
                    bt.get("valuation_high"),
                    bt.get("valuation_mid"),
                    bt.get("score"),
                    (model or "")[:64] or None,
                    (model_id or "")[:32] or None,
                    preference,
                    bt.get("verdict"),
                    bt.get("confidence"),
                    bt.get("horizon"),
                    bt.get("key_reason"),
                    bt.get("mc_now"),
                    bt.get("price_now"),
                    bt.get("pe_ttm_now"),
                    bt.get("pb_now"),
                    bt.get("upside_pct"),
                    int(len(panel_text or "")),
                    (hashlib.sha1((panel_text or "").encode("utf-8")).hexdigest()[:16]
                     if panel_text else None),
                    panel_text,
                    (json.dumps(detail, ensure_ascii=False) if detail else None),
                    bt.get("raw"),
                    1 if fallback else 0,
                    duration_ms,
                    _now(),
                ),
            )
            new_id = cur.lastrowid
        conn.commit()
        return new_id
    finally:
        conn.close()

def list_analysis_valuations(page=1, per_page=20, preference=None, model=None, kw=None,
                             min_score=None, max_score=None):
    """后台回测台账列表（支持按偏好/模型/关键字/评分区间过滤）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where, params = [], []
            if preference:
                where.append("v.preference=%s")
                params.append(preference)
            if model:
                where.append("(v.model=%s OR v.model_id=%s)")
                params += [model, model]
            if min_score is not None:
                where.append("v.score >= %s")
                params.append(min_score)
            if max_score is not None:
                where.append("v.score <= %s")
                params.append(max_score)
            if kw:
                where.append("(v.stock_name LIKE %s OR v.stock_code LIKE %s)")
                params += [f"%{kw}%", f"%{kw}%"]
            w = (" WHERE " + " AND ".join(where)) if where else ""
            cur.execute("SELECT COUNT(*) AS c FROM analysis_valuation v" + w, params)
            total = cur.fetchone()["c"]
            offset = (page - 1) * per_page
            cur.execute(
                "SELECT v.id, v.record_id, v.user_id, v.stock_name, v.stock_code, "
                " v.analysis_date, v.val_low, v.val_high, v.val_mid, v.score, "
                " v.model, v.model_id, v.preference, v.verdict, v.confidence, v.horizon, "
                " v.key_reason, v.mc_at, v.price_at, v.pe_ttm_at, v.pb_at, v.upside_pct, "
                " v.panel_chars, v.panel_hash, v.fallback, v.duration_ms, "
                " v.px_20d, v.px_60d, v.px_120d, v.px_250d, "
                " v.ret_20d, v.ret_60d, v.ret_120d, v.ret_250d, v.backfilled_at, v.created_at, "
                + _EMAIL_DISPLAY_SQL +
                " FROM analysis_valuation v LEFT JOIN users u ON u.id=v.user_id" + w +
                " ORDER BY v.id DESC LIMIT %s OFFSET %s",
                params + [per_page, offset],
            )
            return total, [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()

def get_valuation_detail(rid):
    """取单条回测记录的完整详情（含数据面板快照与模型原始 JSON），供后台「详情」弹窗。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM analysis_valuation WHERE id=%s", (rid,))
            return _serialize_row(cur.fetchone())
    finally:
        conn.close()

def delete_analysis_valuation(vid):
    """删除一条回测台账记录（analysis_valuation）。

    只删台账行，不触碰关联的 analysis_records（研报全文保留，
    前台历史回看不受影响）。返回 True 表示删到，False 表示不存在。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analysis_valuation WHERE id=%s", (vid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def get_valuation_summary():
    """回测总览：按「模型 × 偏好」聚合，用来横向比较谁更靠谱。

    返回三组数据：
      groups       —— 每个模型/偏好组合：去重样本数、平均评分、看多/看空预期空间、
                      方向命中率（预测方向 vs 60 日真实涨跌）、已回填收益
      overall      —— 全局统计
      score_buckets —— 评分-收益关联：按评分档（<4 / 4~7 / ≥7）分桶的实际收益，
                      用来验证「评分高的模型是不是真的更准」（正相关才有效）

    ⚠️ 去重口径：同一 (股票, 分析日, 模型, 偏好) 同日多次重跑只取最新一条
    （ROW_NUMBER 取 id 最大）。否则单票刷屏会把聚合平均带偏
    （实测丰立智能一天 7 条 Qwen3.5-9B）。raw_cnt 保留原始行数供对照。
    需要 MySQL 8.0+（窗口函数）。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            dedup_sql = (
                "SELECT d.*, COUNT(*) OVER () AS raw_total FROM ( "
                "  SELECT t.*, COUNT(*) OVER (PARTITION BY COALESCE(t.model,'-'), "
                "                             COALESCE(t.preference,'-')) AS raw_cnt "
                "  FROM ( "
                "    SELECT v.*, ROW_NUMBER() OVER ( "
                "      PARTITION BY COALESCE(v.stock_code,''), COALESCE(v.analysis_date,''), "
                "                   COALESCE(v.model,'-'), COALESCE(v.preference,'-') "
                "      ORDER BY v.id DESC) AS rn "
                "    FROM analysis_valuation v "
                "  ) t "
                ") d WHERE d.rn = 1"
            )
            cur.execute(
                "SELECT COALESCE(model,'-') AS model, COALESCE(preference,'-') AS preference, "
                " COUNT(*) AS cnt, MAX(raw_cnt) AS raw_cnt, "
                " AVG(score) AS avg_score, AVG(confidence) AS avg_conf, "
                " AVG(CASE WHEN verdict IN ('低估','合理') THEN upside_pct END) AS avg_upside_bull, "
                " AVG(CASE WHEN verdict IN ('高估','回避') THEN upside_pct END) AS avg_upside_bear, "
                " AVG(CASE WHEN val_low>0 AND val_high>0 "
                "         THEN (val_high - val_low)/val_low*100 END) AS avg_band, "
                " SUM(CASE WHEN fallback=1 THEN 1 ELSE 0 END) AS fb_cnt, "
                " SUM(CASE WHEN ret_60d IS NOT NULL THEN 1 ELSE 0 END) AS scored_cnt, "
                " AVG(ret_60d) AS avg_ret60, AVG(ret_120d) AS avg_ret120, "
                " SUM(CASE WHEN upside_pct IS NOT NULL AND ret_60d IS NOT NULL "
                "           AND upside_pct <> 0 AND ret_60d <> 0 "
                "           AND SIGN(upside_pct) = SIGN(ret_60d) THEN 1 ELSE 0 END) AS hit_cnt, "
                " SUM(CASE WHEN upside_pct IS NOT NULL AND ret_60d IS NOT NULL "
                "           THEN 1 ELSE 0 END) AS dir_cnt "
                f"FROM ({dedup_sql}) s "
                "GROUP BY COALESCE(model,'-'), COALESCE(preference,'-') "
                "ORDER BY cnt DESC"
            )
            groups = [_serialize_row(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT COUNT(*) AS total, MAX(raw_total) AS raw_total, "
                " COUNT(DISTINCT stock_code) AS stocks, COUNT(DISTINCT model) AS models, "
                " MIN(analysis_date) AS first_date, MAX(analysis_date) AS last_date, "
                " AVG(score) AS avg_score, "
                " SUM(CASE WHEN ret_60d IS NOT NULL THEN 1 ELSE 0 END) AS backfilled "
                f"FROM ({dedup_sql}) s"
            )
            overall = _serialize_row(cur.fetchone()) or {}
            cur.execute(
                "SELECT CASE WHEN score >= 7 THEN 'high' WHEN score >= 4 THEN 'mid' "
                "        ELSE 'low' END AS bucket, "
                " COUNT(*) AS cnt, AVG(score) AS avg_score, "
                " AVG(ret_60d) AS avg_ret60, AVG(ret_120d) AS avg_ret120 "
                f"FROM ({dedup_sql}) s "
                "WHERE score IS NOT NULL AND ret_60d IS NOT NULL "
                "GROUP BY bucket ORDER BY FIELD(bucket, 'low', 'mid', 'high')"
            )
            buckets = [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return {"groups": groups, "overall": overall, "score_buckets": buckets}

def get_user_valuation_dashboard(uid, limit=60):
    """用户视角的「研报复盘」看板数据（前台 /valuation 用）。

    与后台的 get_valuation_summary 区别有两点，都是为前台体验服务的：
      1. **只统计当前用户**（后台那套是全站的，管理员视角）；
      2. **多返回一个 records 列表**（我的判断档案），并给每条算出「观察进度」——
         因为回填是按 horizon 分别到期（20 日档要 45 个自然日），用户刚分析完
         的票一条数据都还没有，页面若只展示已回填的收益率会「空得像坏了」。

    去重口径与后台保持一致：同一 (股票, 分析日, 模型, 偏好) 只取最新一条，
    否则单票反复重跑会把平均收益带偏。

    观察进度：progress = 已过自然日 / 该 horizon 到期阈值（DUE_DAYS）。
    ⚠️ 阈值与 list_valuations_for_backfill 的 SQL 必须一致，否则页面显示
       「已到期」但后台还没回填，用户会觉得数据自相矛盾。
    """
    if not uid:
        return {"overall": {}, "groups": [], "buckets": [], "records": []}
    due_days = {"20": 45, "60": 105, "120": 195, "250": 395}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            dedup_sql = (
                "SELECT d.*, COUNT(*) OVER () AS raw_total FROM ( "
                "  SELECT t.* FROM ( "
                "    SELECT v.*, ROW_NUMBER() OVER ( "
                "      PARTITION BY COALESCE(v.stock_code,''), COALESCE(v.analysis_date,''), "
                "                   COALESCE(v.model,'-'), COALESCE(v.preference,'-') "
                "      ORDER BY v.id DESC) AS rn "
                "    FROM analysis_valuation v WHERE v.user_id = %s "
                "  ) t WHERE t.rn = 1 "
                ") d"
            )
            args = (uid,)
            cur.execute(
                "SELECT COUNT(*) AS total, COUNT(DISTINCT stock_code) AS stocks, "
                " COUNT(DISTINCT model) AS models, "
                " MIN(analysis_date) AS first_date, MAX(analysis_date) AS last_date, "
                " AVG(score) AS avg_score, "
                " SUM(CASE WHEN ret_20d IS NOT NULL OR ret_60d IS NOT NULL "
                "          THEN 1 ELSE 0 END) AS backfilled "
                f"FROM ({dedup_sql}) s", args
            )
            overall = _serialize_row(cur.fetchone()) or {}
            cur.execute(
                "SELECT COALESCE(model,'-') AS model, COUNT(*) AS cnt, "
                " AVG(score) AS avg_score, "
                " AVG(CASE WHEN ret_20d IS NOT NULL THEN ret_20d END) AS avg_ret20, "
                " AVG(CASE WHEN ret_60d IS NOT NULL THEN ret_60d END) AS avg_ret60, "
                " SUM(CASE WHEN ret_20d IS NOT NULL OR ret_60d IS NOT NULL "
                "          THEN 1 ELSE 0 END) AS verified, "
                " SUM(CASE WHEN upside_pct IS NOT NULL AND ret_20d IS NOT NULL "
                "           AND upside_pct <> 0 AND ret_20d <> 0 "
                "           AND SIGN(upside_pct) = SIGN(ret_20d) THEN 1 ELSE 0 END) AS hit20, "
                " SUM(CASE WHEN ret_20d IS NOT NULL THEN 1 ELSE 0 END) AS dir20 "
                f"FROM ({dedup_sql}) s GROUP BY COALESCE(model,'-') ORDER BY cnt DESC", args
            )
            groups = [_serialize_row(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT CASE WHEN score >= 7 THEN 'high' WHEN score >= 4 THEN 'mid' "
                "        ELSE 'low' END AS bucket, COUNT(*) AS cnt, "
                " AVG(score) AS avg_score, "
                " AVG(ret_20d) AS avg_ret20, AVG(ret_60d) AS avg_ret60 "
                f"FROM ({dedup_sql}) s WHERE score IS NOT NULL "
                "GROUP BY bucket ORDER BY FIELD(bucket, 'low', 'mid', 'high')", args
            )
            buckets = [_serialize_row(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT id, record_id, stock_code, stock_name, model, preference, "
                " analysis_date, score, verdict, confidence, key_reason, horizon, "
                " price_at, mc_at, val_low, val_mid, val_high, upside_pct, "
                " px_20d, ret_20d, px_60d, ret_60d, ret_120d, ret_250d "
                f"FROM ({dedup_sql}) s ORDER BY analysis_date DESC, id DESC LIMIT %s",
                tuple(args) + (limit,)
            )
            records = [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()

    import datetime as _dt
    today = _dt.date.today()
    for r in records:
        ad = r.get("analysis_date")
        if isinstance(ad, str):
            try:
                ad = _dt.date.fromisoformat(ad[:10])
            except ValueError:
                ad = None
        elif not isinstance(ad, _dt.date):
            ad = None
        r["days_passed"] = (today - ad).days if ad else None
        if r.get("ret_20d") is not None:
            r["watch_stage"] = "done20"
        elif r.get("ret_60d") is not None:
            r["watch_stage"] = "done60"
        elif ad:
            r["watch_stage"] = "watching"
            r["progress"] = min(100, round(r["days_passed"] / due_days["20"] * 100))
            r["days_left"] = max(0, due_days["20"] - r["days_passed"])
        else:
            r["watch_stage"] = "unknown"
            r["progress"] = 0
            r["days_left"] = None
    return {"overall": overall, "groups": groups, "buckets": buckets,
            "records": records, "due_days": due_days}

def get_latest_valuation_band(uid, ts_code):
    """取该用户对该股**最近一次**研报给出的合理估值区间（供提醒判定用）。

    为什么需要它：提醒体系里最有价值的一条是「股价跌进你研报给出的安全边际」，
    而这个阈值本来就存在 analysis_valuation.val_low 里 —— 用户不需要手填，
    系统按他自己的研报结论自动取，再拿当前收盘价比对即可（**零额外行情请求**）。

    只取「该用户」的记录：研报是个人判断，替别人估值没有意义。
    返回 {} 表示该用户还没分析过这只票（前端应提示先做研报）。
    """
    if not uid or not ts_code:
        return {}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT val_low, val_mid, val_high, score, verdict, model, "
                "       analysis_date, mc_at, price_at "
                "FROM analysis_valuation "
                "WHERE user_id=%s AND stock_code=%s "
                "  AND val_low IS NOT NULL AND val_low > 0 "
                "ORDER BY analysis_date DESC, id DESC LIMIT 1",
                (uid, ts_code),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _serialize_row(row) if row else {}

def get_user_holdings_with_research(uid):
    """持仓 + 最近研报结论的联表查询（个人中心「持仓研究联动」区块用）。

    把 watchlists 的持仓字段与 analysis_valuation 的最近研报结论拼在一起：
      · 持仓股才显示（cost>0 且 quantity>0 视为有持仓）
      · 有研报的带出 评分/结论/合理区间/当前市值
      · 没有研管的照常返回，前端显示「未做研报」引导去分析

    ⚠️ 去重口径与复盘页一致：同一 (股票, 分析日, 模型, 偏好) 取最新一条。
    """
    if not uid:
        return []
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT w.id, w.ts_code, w.stock_name, w.cost, w.quantity, w.note, "
                "       w.group_name, "
                "       v.score, v.verdict, v.val_low, v.val_mid, v.val_high, "
                "       v.upside_pct, v.analysis_date, v.model "
                "FROM watchlists w "
                "LEFT JOIN ( "
                "  SELECT t.* FROM ( "
                "    SELECT x.*, ROW_NUMBER() OVER ( "
                "      PARTITION BY x.stock_code "
                "      ORDER BY x.analysis_date DESC, x.id DESC) AS rn "
                "    FROM analysis_valuation x WHERE x.user_id = %s "
                "  ) t WHERE t.rn = 1 "
                ") v ON v.stock_code = w.ts_code "
                "WHERE w.user_id = %s AND w.cost > 0 AND w.quantity > 0 "
                "ORDER BY w.ts_code",
                (uid, uid),
            )
            return [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()

def list_valuations_for_backfill(limit=200):
    """取「存在任一已到期且未回填 horizon」的记录，供回填脚本使用。

    ⚠️ 各 horizon 分别到期判断，不再一刀切 90 天：20 日收益 29 个自然日就能填，
    等到 90 天才处理会让 ret_20d 空置两个月。
    到期阈值按 A 股约 243 交易日/年折算自然日（20d≈30、60d≈90、120d≈180、250d≈376），
    每档加 ~15 天余量（节假日/停牌）。选中后数据仍未走完的，脚本侧自然跳过等下次。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, stock_code, analysis_date, price_at, mc_at "
                "FROM analysis_valuation "
                "WHERE stock_code IS NOT NULL AND stock_code<>'' "
                "  AND ( (ret_20d  IS NULL AND analysis_date <= DATE_SUB(CURDATE(), INTERVAL 45 DAY)) "
                "     OR (ret_60d  IS NULL AND analysis_date <= DATE_SUB(CURDATE(), INTERVAL 105 DAY)) "
                "     OR (ret_120d IS NULL AND analysis_date <= DATE_SUB(CURDATE(), INTERVAL 195 DAY)) "
                "     OR (ret_250d IS NULL AND analysis_date <= DATE_SUB(CURDATE(), INTERVAL 395 DAY)) ) "
                "ORDER BY analysis_date ASC LIMIT %s",
                (limit,),
            )
            return [_serialize_row(r) for r in cur.fetchall()]
    finally:
        conn.close()

def apply_valuation_backfill(rid, **fields):
    """回填某条记录的真实走势。白名单字段：px_*/ret_*。"""
    allowed = {"px_20d", "px_60d", "px_120d", "px_250d",
               "ret_20d", "ret_60d", "ret_120d", "ret_250d"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"`{k}`=%s" for k in updates)
            cur.execute(
                f"UPDATE analysis_valuation SET {sets}, backfilled_at=%s WHERE id=%s",
                list(updates.values()) + [_now(), rid],
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

_REDEEM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_REDEEM_MAX_BATCH = 500

def _gen_redeem_code(length=16):
    """生成 16 位无歧义随机码（secrets，非 random：兑换码属于凭据）。"""
    import secrets
    return "".join(secrets.choice(_REDEEM_ALPHABET) for _ in range(length))

def format_redeem_code(code):
    """展示用分组：XXXX-XXXX-XXXX-XXXX。库内存无横线原值，方便用户直接粘贴。"""
    s = str(code or "").strip().upper()
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))

def ensure_redeem_codes_table():
    """幂等：创建 redeem_codes 会员兑换码表。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `redeem_codes` (
                    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `code` VARCHAR(32) NOT NULL COMMENT '兑换码（大写，无易混字符）',
                    `batch_no` VARCHAR(24) NOT NULL COMMENT '批次号',
                    `plan_key` VARCHAR(32) NOT NULL COMMENT '绑定套餐 key（vip1/vip2/payg…）',
                    `plan_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '套餐名快照',
                    `sku_label` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '规格快照（月卡/年卡/体验包…）',
                    `level` TINYINT NOT NULL DEFAULT 0 COMMENT '会员等级 0=不改等级 1=VIP-1 2=VIP-2',
                    `days` INT NOT NULL DEFAULT 0 COMMENT '增加会员天数（0=不加天数）',
                    `bonus_normal` INT NOT NULL DEFAULT 0 COMMENT '赠送普通分析次数',
                    `bonus_deep` INT NOT NULL DEFAULT 0 COMMENT '赠送深度分析次数',
                    `status` TINYINT NOT NULL DEFAULT 0 COMMENT '0未使用 1已使用 2已作废',
                    `expire_at` DATETIME DEFAULT NULL COMMENT '码有效期（NULL=长期有效）',
                    `used_by` BIGINT DEFAULT NULL COMMENT '兑换人 uid',
                    `used_at` DATETIME DEFAULT NULL COMMENT '兑换时间',
                    `created_by` BIGINT DEFAULT NULL COMMENT '生成人（管理员 uid）',
                    `remark` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '批次备注',
                    `created_at` DATETIME NOT NULL,
                    PRIMARY KEY (`id`),
                    UNIQUE KEY `uq_code` (`code`),
                    KEY `idx_batch` (`batch_no`),
                    KEY `idx_status` (`status`),
                    KEY `idx_used_by` (`used_by`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='会员兑换码（站外渠道售卖/活动发放）'"""
            )
        conn.commit()
    finally:
        conn.close()

def create_redeem_codes(plan_key, plan_name, sku_label, level, days,
                        bonus_normal, bonus_deep, count, expire_at=None,
                        created_by=None, remark=""):
    """批量生成兑换码。返回 (batch_no, [code, ...])。

    count 已由接口层限 1~500，这里再兜一次底。
    撞码概率极低（32^16），但仍靠唯一索引兜底：冲突时重生成，最多重试 3 次。
    """
    import datetime as _dt
    count = max(1, min(int(count or 1), _REDEEM_MAX_BATCH))
    batch_no = "B" + _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    codes = []
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for _i in range(count):
                code = None
                for _try in range(3):
                    cand = _gen_redeem_code()
                    try:
                        cur.execute(
                            """INSERT INTO redeem_codes
                               (code, batch_no, plan_key, plan_name, sku_label, level, days,
                                bonus_normal, bonus_deep, status, expire_at, created_by,
                                remark, created_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s)""",
                            (cand, batch_no, str(plan_key or ""), str(plan_name or ""),
                             str(sku_label or ""), int(level or 0), int(days or 0),
                             int(bonus_normal or 0), int(bonus_deep or 0),
                             expire_at, created_by, str(remark or ""), _now()),
                        )
                        code = cand
                        break
                    except Exception:
                        continue
                if code:
                    codes.append(code)
        conn.commit()
    finally:
        conn.close()
    return batch_no, codes

def list_redeem_codes(page=1, per_page=20, batch_no=None, status=None, kw=None):
    """后台兑换码列表。status: None=全部 / 0未用 / 1已用 / 2作废；kw 匹配码或套餐名。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            where, args = [], []
            if batch_no:
                where.append("batch_no=%s")
                args.append(str(batch_no))
            if status not in (None, ""):
                where.append("status=%s")
                args.append(int(status))
            if kw:
                where.append("(code LIKE %s OR plan_name LIKE %s OR sku_label LIKE %s)")
                args += ["%%%s%%" % kw] * 3
            w = (" WHERE " + " AND ".join(where)) if where else ""
            cur.execute("SELECT COUNT(*) AS c FROM redeem_codes" + w, args)
            total = (cur.fetchone() or {}).get("c") or 0
            offset = max(0, (int(page) - 1) * int(per_page))
            cur.execute(
                """SELECT id, code, batch_no, plan_key, plan_name, sku_label, level, days,
                          bonus_normal, bonus_deep, status, expire_at, used_by, used_at,
                          created_by, remark, created_at
                   FROM redeem_codes""" + w + """
                   ORDER BY id DESC LIMIT %s OFFSET %s""",
                args + [int(per_page), offset],
            )
            return total, list(cur.fetchall())
    finally:
        conn.close()

def redeem_code_stats():
    """概览：总 / 未用 / 已用 / 作废。缺失状态一律按 0 补齐（不准返回少键的 dict）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*) AS c FROM redeem_codes GROUP BY status")
            rows = cur.fetchall() or []
        out = {0: 0, 1: 0, 2: 0}
        for r in rows:
            out[int(r["status"])] = int(r["c"])
        return {"total": sum(out.values()), "unused": out[0],
                "used": out[1], "voided": out[2]}
    finally:
        conn.close()

def void_redeem_codes(codes):
    """批量作废（仅未使用的码可被作废）。返回实际作废条数。"""
    if not codes:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            n = 0
            for c in codes:
                n += cur.execute(
                    "UPDATE redeem_codes SET status=2 WHERE code=%s AND status=0",
                    (str(c or "").strip().upper(),),
                )
        conn.commit()
        return n
    finally:
        conn.close()

def fetch_redeem_code_locked(cur, code):
    """事务内取码并加行锁（SELECT ... FOR UPDATE）。调用前必须先 conn.begin()。"""
    cur.execute("SELECT * FROM redeem_codes WHERE code=%s FOR UPDATE", (code,))
    return cur.fetchone()

def mark_redeem_code_used(cur, code, uid):
    """事务内置为已用。带 status=0 条件兜底（锁期间状态若已被改，rowcount=0）。"""
    return cur.execute(
        "UPDATE redeem_codes SET status=1, used_by=%s, used_at=%s WHERE code=%s AND status=0",
        (uid, _now(), code),
    )

def add_user_bonus(uid, normal=0, deep=0, conn=None):
    """原子增加用户的赠送分析次数（普通/深度）。

    传 conn 时复用调用方事务（不自行 commit），不传则独立连接提交。
    """
    normal, deep = int(normal or 0), int(deep or 0)
    if normal == 0 and deep == 0:
        return 0
    sets, args = [], []
    if normal:
        sets.append("bonus_normal = bonus_normal + %s")
        args.append(normal)
    if deep:
        sets.append("bonus_deep = bonus_deep + %s")
        args.append(deep)
    args.append(uid)
    own = conn is None
    conn = conn or get_conn()
    try:
        with conn.cursor() as cur:
            n = cur.execute(
                "UPDATE users SET {} WHERE id=%s".format(", ".join(sets)), args
            )
        if own:
            conn.commit()
        return n
    finally:
        if own:
            conn.close()

def ensure_notifications_table():
    """幂等：站内通知表 + 已读回执表。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `notifications` (
                    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `user_id` BIGINT DEFAULT NULL COMMENT 'NULL=全站广播；否则为指定用户',
                    `type` VARCHAR(24) NOT NULL DEFAULT 'system'
                        COMMENT 'system/redeem/membership_expire/membership_expired/feature',
                    `title` VARCHAR(120) NOT NULL,
                    `content` TEXT COMMENT '正文（纯文本，前端不解析 HTML）',
                    `link` VARCHAR(255) DEFAULT NULL COMMENT '点击跳转',
                    `level` VARCHAR(12) NOT NULL DEFAULT 'info'
                        COMMENT 'info/success/warning/danger（决定前台颜色）',
                    `dedup_key` VARCHAR(64) DEFAULT NULL COMMENT '去重键（唯一索引，防重复推送）',
                    `expire_at` DATETIME DEFAULT NULL COMMENT '展示截止时间（NULL=长期）',
                    `created_at` DATETIME NOT NULL,
                    PRIMARY KEY (`id`),
                    UNIQUE KEY `uq_dedup` (`dedup_key`),
                    KEY `idx_user` (`user_id`),
                    KEY `idx_created` (`created_at`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='站内通知（全站广播/个人消息）'"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS `notification_reads` (
                    `notification_id` BIGINT UNSIGNED NOT NULL,
                    `user_id` BIGINT NOT NULL,
                    `read_at` DATETIME NOT NULL,
                    PRIMARY KEY (`notification_id`, `user_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                  COMMENT='通知已读回执（全站广播也按人记录）'"""
            )
        conn.commit()
    finally:
        conn.close()

def create_notification(user_id, ntype, title, content=None, link=None,
                        level="info", dedup_key=None, expire_at=None):
    """发一条通知。返回 id；被 dedup_key 去重掉的返回 None（不算失败）。

    ⚠️ dedup_key 撞唯一索引时**静默返回 None**：定时扫描类通知每天都会跑到，
       重复是预期行为，抛异常反而会污染日志。调用方按返回值判断是否真发了。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """INSERT INTO notifications
                       (user_id, type, title, content, link, level, dedup_key,
                        expire_at, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (user_id, str(ntype or "system")[:24], str(title or "")[:120],
                     content or None, (str(link) if link else None),
                     str(level or "info")[:12],
                     (str(dedup_key)[:64] if dedup_key else None),
                     expire_at, _now()),
                )
                nid = cur.lastrowid
            except Exception:
                conn.rollback()
                return None
        conn.commit()
        return nid
    finally:
        conn.close()

def list_user_notifications(uid, limit=20, unread_only=False):
    """取某用户可见的通知（全站广播 + 专属），按时间倒序。

    ⚠️ 全站广播靠 LEFT JOIN notification_reads 判已读：没有回执行 = 未读。
       不能把「已读」记在 notifications 上，否则一个人点了已读，全站都跟着已读。
    """
    limit = max(1, min(int(limit or 20), 100))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT n.*, (r.notification_id IS NOT NULL) AS is_read
                   FROM notifications n
                   LEFT JOIN notification_reads r
                          ON r.notification_id = n.id AND r.user_id = %s
                   WHERE (n.user_id IS NULL OR n.user_id = %s)
                     AND (n.expire_at IS NULL OR n.expire_at > %s)
                     """ + ("AND r.notification_id IS NULL " if unread_only else "") + """
                   ORDER BY n.id DESC LIMIT %s""",
                (uid, uid, _now(), limit),
            )
            rows = list(cur.fetchall())
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])[:19]
            if r.get("expire_at"):
                r["expire_at"] = str(r["expire_at"])[:19]
        return rows
    finally:
        conn.close()

def count_unread_notifications(uid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS c FROM notifications n
                   LEFT JOIN notification_reads r
                          ON r.notification_id = n.id AND r.user_id = %s
                   WHERE (n.user_id IS NULL OR n.user_id = %s)
                     AND (n.expire_at IS NULL OR n.expire_at > %s)
                     AND r.notification_id IS NULL""",
                (uid, uid, _now()),
            )
            return int((cur.fetchone() or {}).get("c") or 0)
    finally:
        conn.close()

def notification_visible(nid, uid):
    """该通知对这个人可见吗（全站广播 user_id IS NULL，或专属他）。

    ⚠️ 标记已读接口必须过这一关：不校验的话，改一个 id 就能把别人的
       专属消息标记成已读（越权篡改他人数据）。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM notifications WHERE id=%s AND (user_id IS NULL OR user_id=%s)",
                (int(nid), int(uid)))
            return cur.fetchone() is not None
    finally:
        conn.close()

def mark_notification_read(uid, nid):
    """标记已读。返回是否新增了回执（已读过返回 False，供前端决定要不要改红点）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            n = cur.execute(
                """INSERT IGNORE INTO notification_reads
                   (notification_id, user_id, read_at) VALUES (%s,%s,%s)""",
                (int(nid), int(uid), _now()),
            )
        conn.commit()
        return n == 1
    finally:
        conn.close()

def mark_all_notifications_read(uid):
    """一键已读：把当前所有未读的补上回执。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            n = cur.execute(
                """INSERT IGNORE INTO notification_reads (notification_id, user_id, read_at)
                   SELECT n.id, %s, %s FROM notifications n
                   LEFT JOIN notification_reads r
                          ON r.notification_id = n.id AND r.user_id = %s
                   WHERE (n.user_id IS NULL OR n.user_id = %s)
                     AND (n.expire_at IS NULL OR n.expire_at > %s)
                     AND r.notification_id IS NULL""",
                (uid, _now(), uid, uid, _now()),
            )
        conn.commit()
        return n
    finally:
        conn.close()

def list_admin_notifications(page=1, per_page=20):
    """后台：通知列表（含每个通知的已读人数）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM notifications")
            total = int((cur.fetchone() or {}).get("c") or 0)
            offset = max(0, (int(page) - 1) * int(per_page))
            cur.execute(
                """SELECT n.*, (SELECT COUNT(*) FROM notification_reads r
                                WHERE r.notification_id = n.id) AS read_count
                   FROM notifications n ORDER BY n.id DESC LIMIT %s OFFSET %s""",
                (int(per_page), offset),
            )
            rows = list(cur.fetchall())
        for r in rows:
            for k in ("created_at", "expire_at"):
                if r.get(k):
                    r[k] = str(r[k])[:19]
        return total, rows
    finally:
        conn.close()

def delete_notification(nid):
    """删除通知（连带清掉已读回执，避免留下孤儿行）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM notification_reads WHERE notification_id=%s", (int(nid),))
            n = cur.execute("DELETE FROM notifications WHERE id=%s", (int(nid),))
        conn.commit()
        return n
    finally:
        conn.close()

def scan_membership_expiry(thresholds=(7, 3, 1)):
    """每日扫描：给「即将到期」和「刚到期」的会员发站内提醒。

    返回 (新建条数, 扫描到的会员数)。

    ⚠️ dedup_key 是这套逻辑的命门：定时器每天都跑，不去重用户会天天收到同一条，
       很快就被当成噪音忽略掉。key = expire:{uid}:{到期日}:{提前天数}
       —— 同一个到期日的同一档提醒只发一次；用户续费后到期日变了，
       key 自然不同，重新进入提醒窗口时会再发一次。

    ⚠️ 用「到期日 = 今天 + N 天」精确匹配而不是区间：区间会让一个人在
       N=7 和 N=3 的窗口里重复命中同一档阈值，配合 dedup 反而漏掉档位。
    """
    import datetime as _dt
    today = _dt.date.today()
    created = 0
    scanned = 0
    targets = []

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for th in thresholds:
                target = (today + _dt.timedelta(days=int(th))).isoformat()
                cur.execute(
                    "SELECT id, membership_level, membership_expiry FROM users "
                    "WHERE membership_level >= 1 AND membership_expiry = %s", (target,)
                )
                for u in cur.fetchall() or []:
                    targets.append((u["id"], int(u["membership_level"] or 0),
                                    str(u["membership_expiry"]), int(th)))
            yesterday = (today - _dt.timedelta(days=1)).isoformat()
            cur.execute(
                "SELECT id, membership_level, membership_expiry FROM users "
                "WHERE membership_level >= 1 AND membership_expiry = %s", (yesterday,)
            )
            expired = [(u["id"], int(u["membership_level"] or 0), str(u["membership_expiry"]))
                       for u in (cur.fetchall() or [])]
        scanned = len({t[0] for t in targets} | {e[0] for e in expired})
    finally:
        conn.close()

    for uid, lvl, exp, th in targets:
        nid = create_notification(
            uid, "membership_expire",
            "您的 VIP-%d 会员将在 %d 天后到期" % (lvl, th),
            "到期日 %s。到期后每日深度分析额度等会员权益将暂停。"
            "提前续费可无缝衔接 —— 未到期续费会把新天数叠加到原到期日之后，不会浪费剩余天数。" % exp,
            link="/profile#membership",
            level="danger" if th <= 1 else ("warning" if th <= 3 else "info"),
            dedup_key="expire:%s:%s:%d" % (uid, exp, th),
            expire_at=(today + _dt.timedelta(days=th + 1)).strftime("%Y-%m-%d 00:00:00"),
        )
        if nid:
            created += 1

    for uid, lvl, exp in expired:
        nid = create_notification(
            uid, "membership_expired",
            "您的 VIP-%d 会员已于 %s 到期" % (lvl, exp),
            "会员权益已暂停，账户已回落到免费版（免费版每月仍可免费体验 1 次深度分析）。"
            "随时续费即可恢复，续费从今天起算。",
            link="/pricing", level="danger",
            dedup_key="expired:%s:%s" % (uid, exp),
        )
        if nid:
            created += 1
    return created, scanned
