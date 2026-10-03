import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, ".")
from auth import _sign
import db

BASE = "http://127.0.0.1:8015"
COOKIE = "geek_session=" + _sign({"uid": 1})

P, F = 0, 0

def check(name, cond, extra=""):
    global P, F
    if cond:
        P += 1
        print("  [OK  ] %s%s" % (name, ("  ← " + extra) if extra else ""))
    else:
        F += 1
        print("  [FAIL] %s%s" % (name, ("  ← " + extra) if extra else ""))

conn = db.get_conn()
cur = conn.cursor()
cur.execute("SELECT id FROM analysis_records WHERE user_id=1 ORDER BY id DESC LIMIT 1")
row = cur.fetchone()
before_id = row["id"] if row else 0
cur.close()
conn.close()
print("跑之前最新记录 id =", before_id)

req = urllib.request.Request(
    BASE + "/api/analyze",
    data=json.dumps({"query": "600519", "model": "", "preference": "long_term_value"}).encode(),
    headers={"Content-Type": "application/json", "Cookie": COOKIE},
    method="POST",
)
with urllib.request.urlopen(req, timeout=300) as r:
    body = r.read().decode("utf-8", "replace")
print("  流式返回 %d 字节" % len(body))
check("流式响应非空", len(body) > 2000, "%d bytes" % len(body))

conn = db.get_conn()
cur = conn.cursor()
cur.execute(
    "SELECT id,status,error_msg,LENGTH(COALESCE(report_md,'')) AS rlen,report_md "
    "FROM analysis_records WHERE user_id=1 ORDER BY id DESC LIMIT 1"
)
r = cur.fetchone()
cur.close()
conn.close()

check("产生了新记录", r and r["id"] > before_id,
      "before=%s after=%s" % (before_id, r["id"] if r else None))

if r and r["id"] > before_id:
    rid = r["id"]
    print("  新记录 id=%s status=%s rlen=%s err=%s"
          % (rid, r["status"], r["rlen"], (r["error_msg"] or "")[:60]))
    check("状态为 ok（正常完成不该被判失败）", r["status"] in (None, "ok"),
          "status=%s" % r["status"])
    check("报告全文已落库（同步落库没被改坏）", r["rlen"] > 2000, "%d chars" % r["rlen"])
    md = r["report_md"] or ""
    check("落库内容经过后处理（非模型原始输出）",
          "#" in md and "<font" not in md.split("\n")[0][:200],
          "首行=%r" % md.split("\n")[0][:60])
    check("落库长度与流式长度大致一致（没丢内容）",
          abs(len(md) - len(body)) < max(2000, len(body) * 0.6),
          "db=%d stream=%d" % (len(md), len(body)))

    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM analysis_records WHERE id=%s AND user_id=1", (rid,))
    conn.commit()
    cur.close()
    conn.close()
    print("  已清理测试记录 id=%s" % rid)

print("\n----")
print("normal-path regression: PASS %d / FAIL %d" % (P, F))
sys.exit(1 if F else 0)
