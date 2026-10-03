import io
import os
import re
import subprocess
import sys
import urllib.request

BASE = "http://127.0.0.1:8015"
HERE = os.path.dirname(os.path.abspath(__file__))
TMP_JS = os.path.join(HERE, "_opportunities_gen.js")
NODE = os.environ.get("NODE_BIN", "node")

BANNED = ["DATAHUB", "Tushare", "tushare", "Lixinger", "lixinger",
          "AKShare", "akshare", "格隆汇", "同花顺", "伏尧", "开盘啦"]

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _fetch_html():
    sys.path.insert(0, HERE)
    import auth
    op = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    req = urllib.request.Request(BASE + "/opportunities")
    req.add_header("Cookie", "geek_session=" + auth._sign({"uid": 1}))
    r = op.open(req, timeout=120)
    if r.status != 200:
        raise RuntimeError("GET /opportunities 返回 %s（登录态失效？）" % r.status)
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
            print("  [OK] " + name)
        else:
            f += 1
            print("  [FAIL] " + name + (("  -> " + str(extra)) if extra else ""))

    print("\n[布局] 栅格不再换行留白")
    rows = re.findall(r'<div class="row g-4[^"]*">([\s\S]*?)\n    </div>', html)
    ok("页面两个主行", len(rows) >= 2, len(rows))
    if rows:
        first = rows[0]
        cols = re.findall(r'col-lg-(\d+)', first)
        ok("第一行只有 3 个卡片（旧版塞了 4 个 col-lg-4，第 4 个换行留白）",
           len(cols) == 3, cols)
        ok("第一行栅格合计 = 12（4+4+4）", sum(int(c) for c in cols) == 12, cols)
    if len(rows) >= 2:
        cols2 = re.findall(r'col-lg-(\d+)', rows[1])
        ok("第二行 题材榜 + 机会区 合计 = 12", sum(int(c) for c in cols2) == 12, cols2)
        ok("机会区（右侧主内容）不窄于题材榜",
           len(cols2) == 2 and int(cols2[1]) >= int(cols2[0]), cols2)
    ok("旧版 col-lg-9 已移除", 'col-lg-9"' not in html)

    print("\n[布局] 题材榜合并")
    ok("不再有 conceptList 容器", 'id="conceptList"' not in html)
    ok("不再有 sectorList 容器", 'id="sectorList"' not in html)
    ok("新增 themeList 容器", 'id="themeList"' in html)
    ok("新增排序 tab", 'id="themeTabs"' in html and 'data-sort="zt"' in html and 'data-sort="up"' in html)

    print("\n[情绪] 恐惧贪婪条")
    g = re.search(r'class="fear-greed-bar"\s+style="background:\s*(linear-gradient[^;]*);?"', html)
    ok("渐变由后端分档生成", bool(g), "未匹配到 fear-greed-bar")
    if g:
        ok("渐变 10 个色标（5 档 x 2）", g.group(1).count("#") == 10, g.group(1).count("#"))
        ok("渐变覆盖 0%~100%", "0%" in g.group(1) and "100%" in g.group(1))
    z = re.search(r'class="fear-greed-zone"\s+style="left:\s*([\d.]+)%;\s*width:\s*([\d.]+)%;?"', html)
    ok("当前档位描边已定位", bool(z))
    if z:
        left, width = float(z.group(1)), float(z.group(2))
        ok("档位描边不越界", width > 0 and 0 <= left and left + width <= 100.5, (left, width))
    m = re.search(r'class="fear-greed-marker"\s+style="left:\s*calc\(([\d.]+)%\s*-\s*(\d+)px\)\s*;?"', html)
    ok("marker 用 calc 居中修正", bool(m))
    scales = re.findall(r'style="left:\s*([\d.]+)%;?">(恐慌|谨慎|中性|乐观|贪婪)<', html)
    ok("5 档刻度齐全", len(scales) == 5, scales)
    if len(scales) == 5:
        pos = [float(x[0]) for x in scales]
        ok("刻度按档位中点（非三等分）",
           all(abs(a - b) > 1 for a, b in zip(pos, [10, 30, 50, 70, 90])), pos)
        ok("刻度单调递增", pos == sorted(pos), pos)
    ok("情绪分项已下发", 'senti-part' in html)
    ok("北向资金：缺失显示「未披露」，有值则显示真实亿元",
       ('未披露' in html)
       or (re.search(r'北向资金：[\s\S]{0,300}?[-+]?[\d.]+ 亿元', html) is not None),
       html[html.find('北向资金'):html.find('北向资金') + 220] if '北向资金' in html else 'missing')

    print("\n[口径] 前台禁数据源真名")
    hits = [b for b in BANNED if b in html]
    ok("渲染后 HTML 无数据源真名", not hits, hits)

    return p, f

def main():
    print("拉取 /opportunities 渲染后的页面 ...")
    try:
        html = _fetch_html()
    except Exception as e:
        print("[FAIL] 取不到 /opportunities（8015 服务在跑吗？）: %s" % e)
        return 1

    code = _pick_inline_script(html)
    print("抽出内联 JS %d 字符" % len(code))

    hp, hf = _check_static_html(html)

    stubs = io.open(os.path.join(HERE, "test_opportunities_stubs.js"), encoding="utf-8").read()
    tests = io.open(os.path.join(HERE, "test_opportunities_tests.js"), encoding="utf-8").read()

    with io.open(TMP_JS, "w", encoding="utf-8") as f:
        f.write(stubs.replace("\r\n", "\n"))
        f.write("\n/* ===== 页面内联 JS（真实渲染产物） ===== */\n")
        f.write(code)
        f.write("\n/* ===== 断言 ===== */\n")
        f.write(tests.replace("\r\n", "\n"))

    try:
        rc = subprocess.call([NODE, TMP_JS], cwd=HERE)
    except OSError as e:
        print("[FAIL] 跑不了 node（可用 NODE_BIN 指定路径）: %s" % e)
        return 1
    if rc != 0:
        print("\n[FAIL] 页面内联 JS 执行失败（见上方 Node 报错）—— "
              "典型原因：const 声明前访问（TDZ）、或取了不存在的 DOM 元素。")
        return rc
    if hf:
        print("\n[FAIL] 静态 HTML 段有 %d 项失败" % hf)
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
