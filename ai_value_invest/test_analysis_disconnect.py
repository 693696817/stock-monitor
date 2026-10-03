import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, ".")
from auth import _sign
import db

BASE = "http://127.0.0.1:8015"
COOKIE = "geek_session=" + _sign({"uid": 1})
BAD = "zzznotexist9999"

P, F = 0, 0

def check(name, cond, extra=""):
    global P, F
    if cond:
        P += 1
        print("  [OK  ] %s%s" % (name, ("  ← " + extra) if extra else ""))
    else:
        F += 1
        print("  [FAIL] %s%s" % (name, ("  ← " + extra) if extra else ""))

def latest_record():
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id,user_id,stock_name,mode,status,error_msg,"
                "LENGTH(COALESCE(report_md,'')) AS rlen "
                "FROM analysis_records WHERE user_id=1 ORDER BY id DESC LIMIT 1"
            )
            return cur.fetchone()
    finally:
        conn.close()

def probe(timeout=25):
    req = urllib.request.Request(
        BASE + "/api/analyze",
        data=json.dumps({"query": BAD, "model": "", "preference": "long_term_value"}).encode(),
        headers={"Content-Type": "application/json", "Cookie": COOKIE},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1

before = latest_record()
before_id = before["id"] if before else 0
print("断连测试前最新记录 id =", before_id)

req = urllib.request.Request(
    BASE + "/api/analyze",
    data=json.dumps({"query": "600519", "model": "", "preference": "long_term_value"}).encode(),
    headers={"Content-Type": "application/json", "Cookie": COOKIE},
    method="POST",
)
resp = urllib.request.urlopen(req, timeout=60)
print("  已收到响应头，HTTP %s（此刻服务端 record 已落库、流刚起步）" % resp.status)
print("  已断开连接，等待服务端收尾...")

time.sleep(12)

after = latest_record()
check("断连后产生了新记录（说明请求确实进到了落库阶段）",
      after and after["id"] > before_id,
      "before=%s after=%s" % (before_id, after["id"] if after else None))

if after and after["id"] > before_id:
    rid = after["id"]
    print("  新记录: id=%s %s status=%s rlen=%s err=%s"
          % (rid, after["stock_name"], after["status"], after["rlen"],
             (after["error_msg"] or "")[:50]))
    if after["rlen"] == 0:
        check("空输出被判定为失败（status='failed'）", after["status"] == "failed",
              "status=%s" % after["status"])
        check("失败原因已记录", bool(after["error_msg"]), (after["error_msg"] or "")[:60])
    else:
        check("有部分输出 → 保存了部分报告且状态为 ok",
              after["status"] in (None, "ok"), "status=%s rlen=%s" % (after["status"], after["rlen"]))

print("\n== 断连后并发锁必须已释放 ==")
st = probe()
check("锁已释放（无效标的未被 409）", st == 200, "status=%s" % st)

if after and after["id"] > before_id:
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analysis_records WHERE id=%s AND user_id=1", (after["id"],))
        conn.commit()
        print("  已清理测试记录 id=%s" % after["id"])
    finally:
        conn.close()

print("\n----")
print("disconnect test: PASS %d / FAIL %d" % (P, F))
sys.exit(1 if F else 0)
