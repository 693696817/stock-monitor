
import os
import sys
import sqlite3
import datetime

import db

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db")
FORCE = "--force" in sys.argv

def fix_dt(v):
    if v is None:
        return None
    s = str(v)
    if "T" in s and len(s) >= 11:
        return s.replace("T", " ", 1)
    return s

def main():
    if not os.path.exists(SQLITE_PATH):
        print("未找到 SQLite 文件：", SQLITE_PATH)
        return

    sconn = sqlite3.connect(SQLITE_PATH)
    sconn.row_factory = sqlite3.Row
    mconn = db.get_conn()
    try:
        with mconn.cursor() as cur:
            cur.execute("SELECT COUNT(*) c FROM users")
            existing = cur.fetchone()["c"]
            if existing and not FORCE:
                print(f"⚠️ MySQL users 已存在 {existing} 条数据，跳过迁移（如确需重迁请加 --force）。")
                return
            if FORCE:
                print("FORCE 模式：清空目标表...")
                for t in ("invite_records", "analysis_records", "users"):
                    cur.execute(f"DELETE FROM {t}")
                mconn.commit()

            users = sconn.execute("SELECT * FROM users ORDER BY id").fetchall()
            urows = 0
            for u in users:
                u = dict(u)
                cur.execute(
                    """INSERT INTO users
                       (id, email, username, password_hash, salt, nickname,
                        membership_level, membership_expiry, points, invite_code,
                        invited_by, created_at, daily_analysis_date, daily_analysis_count)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        u["id"], u["email"], u.get("username"), u["password_hash"], u["salt"],
                        u["nickname"], u["membership_level"], fix_dt(u["membership_expiry"]),
                        u["points"], u["invite_code"], u["invited_by"], fix_dt(u["created_at"]),
                        fix_dt(u["daily_analysis_date"]), u["daily_analysis_count"],
                    ),
                )
                urows += 1
            cur.execute("SELECT COALESCE(MAX(id),0)+1 m FROM users")
            nxt = cur.fetchone()["m"]
            cur.execute(f"ALTER TABLE users AUTO_INCREMENT = {nxt}")
            print(f"  users: 迁移 {urows} 条")

            logs = sconn.execute("SELECT * FROM analysis_log ORDER BY id").fetchall()
            lrows = 0
            for r in logs:
                r = dict(r)
                cur.execute(
                    """INSERT INTO analysis_records
                       (id, user_id, stock_name, stock_code, mode, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (r["id"], r["user_id"], r["stock_name"], r["stock_code"],
                     r.get("mode") or "normal", fix_dt(r["created_at"])),
                )
                lrows += 1
            cur.execute("SELECT COALESCE(MAX(id),0)+1 m FROM analysis_records")
            nxt = cur.fetchone()["m"]
            cur.execute(f"ALTER TABLE analysis_records AUTO_INCREMENT = {nxt}")
            print(f"  analysis_records: 迁移 {lrows} 条")

            inv = sconn.execute(
                "SELECT id, invited_by, invite_code FROM users WHERE invited_by IS NOT NULL"
            ).fetchall()
            irows = 0
            for r in inv:
                r = dict(r)
                cur.execute(
                    """INSERT INTO invite_records
                       (inviter_id, invitee_id, invite_code, reward_days, reward_level, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (r["invited_by"], r["id"], r["invite_code"], 3, 1,
                     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                irows += 1
            print(f"  invite_records: 生成 {irows} 条")

            mconn.commit()
            print("✅ 迁移完成")
    finally:
        sconn.close()
        mconn.close()

if __name__ == "__main__":
    main()
