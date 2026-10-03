import io
import json
import os
import subprocess
import sys
import urllib.request

BASE = "http://127.0.0.1:8015"
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(HERE, "_kline_opt_gen.js")
TMP_DATA = os.path.join(HERE, "_kline_opt_gen_data.json")
NODE = os.environ.get("NODE_BIN", "node")

BLOCK_START = "// ---------- K线 + 技术指标 ----------"
BLOCK_END = "// ---------- 公司概况 + 官网解析 ----------"

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _get_json(path, timeout=90):
    op = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    r = op.open(BASE + path, timeout=timeout)
    return json.loads(r.read().decode("utf-8"))

def main():
    code = os.environ.get("PROBE_CODE", "000963.SZ")
    days = os.environ.get("PROBE_DAYS", "240")

    print("拉取真实 K 线数据 %s days=%s ..." % (code, days))
    try:
        j = _get_json("/api/stock/%s/kline?days=%s&fq=lxr" % (code, days))
    except Exception as e:
        print("❌ 取不到 K 线数据（8015 服务在跑吗？）: %s" % e)
        return 1
    if not (j.get("data") and j.get("indicators")):
        print("❌ 接口没返回 indicators，无法做结构校验：%s" % j.get("error"))
        return 1
    with io.open(TMP_DATA, "w", encoding="utf-8") as f:
        f.write(json.dumps(j, ensure_ascii=False))

    tpl = io.open(os.path.join(HERE, "templates", "stock_detail.html"), encoding="utf-8").read()
    norm = tpl.replace("\r\n", "\n")
    a = norm.index(BLOCK_START)
    b = norm.index(BLOCK_END, a)
    block = norm[a:b]

    stubs = io.open(os.path.join(HERE, "test_kline_opt_stubs.js"), encoding="utf-8").read()
    tests = io.open(os.path.join(HERE, "test_kline_opt_tests.js"), encoding="utf-8").read()
    with io.open(TMP, "w", encoding="utf-8") as f:
        f.write(stubs.replace("\r\n", "\n"))
        f.write("\n")
        f.write(block)
        f.write("\n")
        f.write(tests.replace("\r\n", "\n"))

    try:
        rc = subprocess.call([NODE, TMP], cwd=HERE)
    except OSError as e:
        print("❌ 跑不了 node（可用 NODE_BIN 指定路径）: %s" % e)
        return 1
    return rc

if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for p in (TMP, TMP_DATA):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
