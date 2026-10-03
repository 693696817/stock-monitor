import io
import os
import re
import subprocess
import sys
import urllib.request

BASE = "http://127.0.0.1:8015"
HERE = os.path.dirname(os.path.abspath(__file__))
TMP_JS = os.path.join(HERE, "_market_chart_gen.js")
NODE = os.environ.get("NODE_BIN", "node")

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _fetch_market_html():
    sys.path.insert(0, HERE)
    import auth
    op = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    req = urllib.request.Request(BASE + "/market")
    req.add_header("Cookie", "geek_session=" + auth._sign({"uid": 1}))
    r = op.open(req, timeout=90)
    if r.status != 200:
        raise RuntimeError("GET /market 返回 %s（登录态失效？）" % r.status)
    return r.read().decode("utf-8", errors="replace")

def _pick_inline_script(html):
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", html)
    blocks = [b for b in blocks if b.strip()]
    if not blocks:
        raise RuntimeError("页面里没找到内联 <script>")
    return max(blocks, key=len)

def _check_static_html(html):
    p = f = 0

    def ok(name, cond, extra=""):
        nonlocal p, f
        if cond:
            p += 1
            print("  ✅ " + name)
        else:
            f += 1
            print("  ❌ " + name + (("  → " + str(extra)) if extra else ""))

    print("\n[静态 HTML] 恐惧贪婪条与空态")
    g = re.search(r'class="fear-greed-bar"\s+style="background:\s*(linear-gradient[^;]*);?"', html)
    ok("渐变条由分档生成", bool(g), "未匹配到 fear-greed-bar 的 style")
    if g:
        stops = g.group(1).count("#")
        ok("渐变 10 个色标（5 档 × 2）", stops == 10, stops)
        ok("渐变覆盖 0%~100%", "0%" in g.group(1) and "100%" in g.group(1), g.group(1)[-40:])
    z = re.search(r'class="fear-greed-zone"\s+style="left:\s*([\d.]+)%;\s*width:\s*([\d.]+)%;?"', html)
    ok("当前档位描边已定位", bool(z), "未匹配到 fear-greed-zone")
    if z:
        left, width = float(z.group(1)), float(z.group(2))
        ok("档位描边宽度 > 0", width > 0, width)
        ok("档位描边不越界（0 ≤ left, left+width ≤ 100）",
           0 <= left and left + width <= 100.5, (left, width))
    m = re.search(r'class="fear-greed-marker"\s+style="left:\s*calc\(([\d.]+)%\s*-\s*(\d+)px\)\s*;?"', html)
    ok("marker 用 calc 做了居中修正", bool(m), "未匹配到 calc(...)，会偏移")
    if m:
        v = float(m.group(1))
        ok("marker 位置在 0~100 之间", 0 <= v <= 100, v)
    tip = re.search(r'class="fg-tip">([^<]+)</span>', html)
    ok("数值气泡有值", bool(tip and tip.group(1).strip()), tip and tip.group(1))
    scales = re.findall(r'style="left:\s*([\d.]+)%;?">(恐慌|谨慎|中性|乐观|贪婪)<', html)
    ok("5 档刻度齐全", len(scales) == 5, scales)
    if len(scales) == 5:
        pos = [float(x[0]) for x in scales]
        ok("刻度按档位中点（非三等分）",
           all(abs(a - b) > 1 for a, b in zip(pos, [10, 30, 50, 70, 90])), pos)
        ok("刻度单调递增", pos == sorted(pos), pos)
    ok("空态元素存在", 'id="sentimentEmpty"' in html, "")
    ok("无假数据占位数组 [50,50,...]", "[50,50,50" not in html, "仍有假数据 fallback")
    return p, f

def main():
    print("拉取 /market 渲染后的页面 ...")
    try:
        html = _fetch_market_html()
    except Exception as e:
        print("❌ 取不到 /market（8015 服务在跑吗？）: %s" % e)
        return 1

    code = _pick_inline_script(html)
    print("抽出内联 JS %d 字符" % len(code))

    hp, hf = _check_static_html(html)

    stubs = io.open(os.path.join(HERE, "test_market_chart_stubs.js"), encoding="utf-8").read()
    tests = io.open(os.path.join(HERE, "test_market_chart_tests.js"), encoding="utf-8").read()

    with io.open(TMP_JS, "w", encoding="utf-8") as f:
        f.write(stubs.replace("\r\n", "\n"))
        f.write("\n/* ===== 页面内联 JS（真实渲染产物） ===== */\n")
        f.write(code)
        f.write("\n/* ===== 断言 ===== */\n")
        f.write(tests.replace("\r\n", "\n"))

    try:
        rc = subprocess.call([NODE, TMP_JS], cwd=HERE)
    except OSError as e:
        print("❌ 跑不了 node（可用 NODE_BIN 指定路径）: %s" % e)
        return 1
    if rc != 0:
        print("\n❌ 页面内联 JS 执行失败（见上方 Node 报错）—— "
              "典型原因：变量在 const 声明前被访问（TDZ）、或取了不存在的 DOM 元素。")
        return rc
    if hf:
        print("\n❌ 静态 HTML 段有 %d 项失败" % hf)
        return 1
    print("\n静态 HTML 段：PASS %d / FAIL %d" % (hp, hf))
    return rc

if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try:
            if os.path.exists(TMP_JS):
                os.remove(TMP_JS)
        except OSError:
            pass
