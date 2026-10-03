# -*- coding: utf-8 -*-
"""生成 README 用的界面示意图（SVG）。

为什么用 SVG 而非截图：
  1. 无需登录服务器、不依赖第三方服务，任何时候都能重新生成；
  2. 矢量清晰，GitHub/Gitee 深浅主题下都不糊；
  3. 可控 —— 演示时用假数据，不泄露任何真实持仓与研报内容。
所有数值为示意，不含真实用户数据。
"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "images")
os.makedirs(OUT, exist_ok=True)

# 站点设计语言：深空观测台（与 static/css/tokens.css 保持一致）
BG = "#0d1424"
SURFACE = "#151e33"
SURFACE2 = "#1c2740"
BORDER = "rgba(255,255,255,0.10)"
BRAND = "#38bdf8"
BRAND2 = "#818cf8"
TEXT = "#f1f5f9"
TEXT2 = "#94a3b8"
TEXT3 = "#64748b"
UP = "#f87171"
DOWN = "#34d399"

FONT = "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def shell(w, h, body, title, subtitle):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="{FONT}">
<rect width="{w}" height="{h}" fill="{BG}"/>
<circle cx="{w*0.72}" cy="40" r="160" fill="{BRAND}" opacity="0.05"/>
<circle cx="{w*0.15}" cy="{h}" r="120" fill="{BRAND2}" opacity="0.04"/>
<text x="28" y="34" fill="{TEXT}" font-size="16" font-weight="600">{esc(title)}</text>
<text x="28" y="52" fill="{TEXT3}" font-size="12">{esc(subtitle)}</text>
{body}
</svg>'''


def nav_bar(x, y, w, active="首页"):
    items = ["首页", "股票分析", "大盘分析", "热门个股", "研报复盘"]
    cx = x
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="34" rx="8" fill="{SURFACE}" stroke="{BORDER}"/>']
    for it in items:
        tw = len(it) * 12 + 22
        if it == active:
            out.append(f'<rect x="{cx+4}" y="{y+5}" width="{tw-8}" height="24" rx="6" fill="{BRAND}" opacity="0.16"/>')
        col = BRAND if it == active else TEXT2
        out.append(f'<text x="{cx+tw/2}" y="{y+22}" fill="{col}" font-size="12" text-anchor="middle">{esc(it)}</text>')
        cx += tw + 6
    return "\n".join(out), cx


# ---------------------------------------------------------------- 1. 首页
def gen_home():
    W, H = 960, 620
    b = []
    nb, _ = nav_bar(28, 66, 560)
    b.append(nb)
    b.append(f'<text x="812" y="88" fill="{BRAND}" font-size="12">登录 · 注册</text>')
    # hero
    b.append(f'<rect x="28" y="122" width="904" height="176" rx="12" fill="{SURFACE}" stroke="{BORDER}"/>')
    b.append(f'<text x="56" y="176" fill="{TEXT}" font-size="24" font-weight="700">看清一家公司的真实质地</text>')
    b.append(f'<text x="56" y="206" fill="{TEXT2}" font-size="13">AI 财报解读 · 内在价值测算 · 财务排雷 · 风险提示</text>')
    b.append(f'<rect x="56" y="228" width="230" height="38" rx="8" fill="{SURFACE2}" stroke="{BORDER}"/>')
    b.append(f'<text x="72" y="252" fill="{TEXT3}" font-size="12">输入股票名称或代码</text>')
    b.append(f'<rect x="298" y="228" width="104" height="38" rx="8" fill="url(#g1)"/>')
    b.append(f'<text x="350" y="252" fill="#04121f" font-size="13" font-weight="600" text-anchor="middle">开始分析</text>')
    # 搜索联想
    b.append(f'<rect x="56" y="272" width="346" height="16" rx="4" fill="{BRAND}" opacity="0.20"/>')
    # 统计
    cards = [("覆盖个股", "5,500+"), ("分析维度", "20+"), ("研报回溯", "可验证"), ("数据源", "多源校验")]
    for i, (k, v) in enumerate(cards):
        x = 28 + i * 228
        b.append(f'<rect x="{x}" y="318" width="212" height="72" rx="10" fill="{SURFACE}" stroke="{BORDER}"/>')
        b.append(f'<text x="{x+20}" y="344" fill="{TEXT3}" font-size="11">{esc(k)}</text>')
        b.append(f'<text x="{x+20}" y="372" fill="{TEXT}" font-size="20" font-weight="700">{esc(v)}</text>')
    # 功能区标题
    b.append(f'<text x="28" y="432" fill="{TEXT}" font-size="15" font-weight="600">核心能力</text>')
    feats = [("AI 深度研报", "按长线 / 综合 / 深度三档偏好生成"), ("研报复盘", "事后回填真实涨跌，验证 AI 判断"),
             ("合理价告警", "跌破你自己的估值下限即提醒"), ("持仓联动", "持仓与研究结论并排对照")]
    for i, (t, d) in enumerate(feats):
        x = 28 + (i % 2) * 456
        y = 450 + (i // 2) * 76
        b.append(f'<rect x="{x}" y="{y}" width="440" height="64" rx="10" fill="{SURFACE}" stroke="{BORDER}"/>')
        b.append(f'<rect x="{x+16}" y="{y+18}" width="4" height="28" rx="2" fill="{BRAND}"/>')
        b.append(f'<text x="{x+32}" y="{y+28}" fill="{TEXT}" font-size="13" font-weight="600">{esc(t)}</text>')
        b.append(f'<text x="{x+32}" y="{y+48}" fill="{TEXT3}" font-size="11">{esc(d)}</text>')
    defs = (f'<defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0%" stop-color="{BRAND}"/><stop offset="100%" stop-color="{BRAND2}"/>'
            f'</linearGradient></defs>')
    return shell(W, H, defs + "\n".join(b), "A股棱镜 · 首页",
                 "界面示意图，数值为演示数据")


# ---------------------------------------------------------------- 2. 研报页
def gen_report():
    W, H = 960, 660
    b = []
    nb, _ = nav_bar(28, 66, 560, "股票分析")
    b.append(nb)
    b.append(f'<rect x="28" y="122" width="904" height="52" rx="10" fill="{SURFACE}" stroke="{BORDER}"/>')
    b.append(f'<text x="48" y="145" fill="{TEXT}" font-size="16" font-weight="700">宁德时代 300750.SZ</text>')
    b.append(f'<text x="48" y="164" fill="{TEXT2}" font-size="12">新能源 · 电池</text>')
    b.append(f'<text x="880" y="152" fill="{UP}" font-size="15" font-weight="600" text-anchor="end">+2.31%</text>')
    secs = [("一、生意本质与护城河", 2), ("二、财务质量体检", 3), ("三、估值锚定与内在价值", 4)]
    y = 194
    for title, lines in secs:
        h = 30 + lines * 22
        b.append(f'<rect x="28" y="{y}" width="904" height="{h}" rx="10" fill="{SURFACE}" stroke="{BORDER}"/>')
        b.append(f'<rect x="28" y="{y}" width="3" height="{h}" rx="1.5" fill="{BRAND}" opacity="0.7"/>')
        b.append(f'<text x="48" y="{y+26}" fill="{TEXT}" font-size="14" font-weight="600">{esc(title)}</text>')
        for k in range(lines):
            w = [820, 700, 760, 640][(k + len(title)) % 4]
            b.append(f'<rect x="48" y="{y+44+k*22}" width="{w}" height="8" rx="4" fill="{TEXT3}" opacity="0.35"/>')
        y += h + 14
    # 估值卡
    b.append(f'<rect x="28" y="{y}" width="448" height="96" rx="10" fill="{SURFACE}" stroke="{BRAND}" stroke-opacity="0.4"/>')
    b.append(f'<text x="48" y="{y+28}" fill="{BRAND}" font-size="12">合理价值区间（DCF 三情景）</text>')
    b.append(f'<text x="48" y="{y+62}" fill="{TEXT}" font-size="24" font-weight="700">186 ~ 242</text>')
    b.append(f'<text x="48" y="{y+82}" fill="{TEXT3}" font-size="11">单位：元/股 · 敏感性 ±18%</text>')
    b.append(f'<rect x="492" y="{y}" width="440" height="96" rx="10" fill="{SURFACE}" stroke="{BORDER}"/>')
    b.append(f'<text x="512" y="{y+28}" fill="{TEXT2}" font-size="12">结论</text>')
    b.append(f'<text x="512" y="{y+60}" fill="{DOWN}" font-size="20" font-weight="700">合理</text>')
    b.append(f'<text x="600" y="{y+60}" fill="{TEXT3}" font-size="12">性价比评分 6.5 / 10</text>')
    return shell(W, H, "\n".join(b), "AI 深度研报",
                 "界面示意图，数值为演示数据")


# ---------------------------------------------------------------- 3. 复盘页
def gen_review():
    W, H = 960, 600
    b = []
    nb, _ = nav_bar(28, 66, 560, "研报复盘")
    b.append(nb)
    b.append(f'<text x="28" y="128" fill="{TEXT}" font-size="17" font-weight="700">研报复盘 · 我的判断准不准</text>')
    b.append(f'<text x="28" y="148" fill="{TEXT3}" font-size="11">收益由系统每交易日收盘后自动回填</text>')
    stats = [("判断总数", "128"), ("已验证", "41"), ("观察中", "87"), ("方向命中", "61%")]
    for i, (k, v) in enumerate(stats):
        x = 28 + i * 228
        b.append(f'<rect x="{x}" y="164" width="212" height="70" rx="10" fill="{SURFACE}" stroke="{BORDER}"/>')
        b.append(f'<text x="{x+20}" y="188" fill="{TEXT3}" font-size="11">{esc(k)}</text>')
        b.append(f'<text x="{x+20}" y="216" fill="{TEXT}" font-size="20" font-weight="700">{esc(v)}</text>')
    b.append(f'<text x="28" y="266" fill="{TEXT}" font-size="14" font-weight="600">判断档案</text>')
    heads = ["股票", "分析日", "评分", "结论", "20 日", "60 日", "状态"]
    colw = [180, 110, 80, 100, 110, 110, 180]
    cx = 28
    for hd, wd in zip(heads, colw):
        b.append(f'<text x="{cx+10}" y="290" fill="{TEXT3}" font-size="11">{esc(hd)}</text>')
        cx += wd
    b.append(f'<line x1="28" y1="298" x2="932" y2="298" stroke="{BORDER}"/>')
    rows = [("贵州茅台", "10-02", "7.5", "低估", "+3.2%", "+8.9%", "已验证", DOWN, DOWN),
            ("宁德时代", "10-02", "6.5", "合理", "观察中", "—", "29 / 45 天", TEXT3, None),
            ("比亚迪", "09-28", "5.0", "合理", "观察中", "—", "12 / 45 天", TEXT3, None),
            ("中国平安", "09-28", "7.5", "低估", "观察中", "—", "12 / 45 天", TEXT3, None)]
    y = 316
    for name, d, sc, vd, r20, r60, st, c1, c2 in rows:
        cx = 28
        vals = [name, d, sc, vd, r20, r60, st]
        for i, (v, wd) in enumerate(zip(vals, colw)):
            col = TEXT
            if i == 3 and vd == "低估":
                col = UP
            if i in (4, 5) and c1 is not None and i == 4:
                col = c1
            if i == 6:
                col = TEXT2
            b.append(f'<text x="{cx+10}" y="{y+18}" fill="{col}" font-size="12">{esc(v)}</text>')
            cx += wd
        b.append(f'<line x1="28" y1="{y+32}" x2="932" y2="{y+32}" stroke="{BORDER}" opacity="0.5"/>')
        y += 44
    return shell(W, H, "\n".join(b), "研报复盘",
                 "界面示意图，数值为演示数据")


# ---------------------------------------------------------------- 4. 个股页
def gen_stock():
    W, H = 960, 620
    b = []
    nb, _ = nav_bar(28, 66, 560, "股票分析")
    b.append(nb)
    b.append(f'<rect x="28" y="122" width="904" height="70" rx="10" fill="{SURFACE}" stroke="{BORDER}"/>')
    b.append(f'<text x="48" y="152" fill="{TEXT}" font-size="18" font-weight="700">贵州茅台 600519.SH</text>')
    b.append(f'<text x="48" y="174" fill="{TEXT2}" font-size="12">食品饮料 · 白酒</text>')
    b.append(f'<text x="910" y="156" fill="{UP}" font-size="20" font-weight="700" text-anchor="end">1,682.00</text>')
    b.append(f'<text x="910" y="176" fill="{UP}" font-size="12" text-anchor="end">+1.24%</text>')
    metrics = [("市盈率 TTM", "22.4", "历史 32% 分位"), ("市净率", "8.1", "历史 28% 分位"),
               ("ROE", "30.2%", "近五年高位"), ("股息率", "3.12%", "连续 20 年分红"),
               ("总市值", "2.11 万亿", "行业第一"), ("毛利率", "91.9%", "稳定")]
    for i, (k, v, note) in enumerate(metrics):
        x = 28 + (i % 3) * 306
        y = 212 + (i // 3) * 92
        b.append(f'<rect x="{x}" y="{y}" width="290" height="80" rx="10" fill="{SURFACE}" stroke="{BORDER}"/>')
        b.append(f'<text x="{x+20}" y="{y+26}" fill="{TEXT3}" font-size="11">{esc(k)}</text>')
        b.append(f'<text x="{x+20}" y="{y+54}" fill="{TEXT}" font-size="19" font-weight="700">{esc(v)}</text>')
        b.append(f'<text x="{x+150}" y="{y+54}" fill="{TEXT3}" font-size="10">{esc(note)}</text>')
    b.append(f'<text x="28" y="404" fill="{TEXT}" font-size="14" font-weight="600">数据面板完整度</text>')
    for i, (g, pct) in enumerate([("行情速览", 100), ("技术指标", 96), ("资金流向", 100),
                                  ("估值指标", 100), ("盈利与杜邦", 92), ("成长与业绩", 88)]):
        x = 28 + (i % 3) * 306
        y = 420 + (i // 3) * 44
        bw = int(150 * pct / 100)
        col = DOWN if pct >= 95 else (BRAND if pct >= 85 else "#fbbf24")
        b.append(f'<text x="{x}" y="{y+14}" fill="{TEXT2}" font-size="11">{esc(g)}</text>')
        b.append(f'<rect x="{x+96}" y="{y+4}" width="150" height="10" rx="5" fill="{TEXT3}" opacity="0.25"/>')
        b.append(f'<rect x="{x+96}" y="{y+4}" width="{bw}" height="10" rx="5" fill="{col}"/>')
        b.append(f'<text x="{x+254}" y="{y+14}" fill="{TEXT3}" font-size="10">{pct}%</text>')
    return shell(W, H, "\n".join(b), "个股研究",
                 "界面示意图，数值为演示数据")


# ---------------------------------------------------------------- 5. 告警设置
def gen_alert():
    W, H = 760, 520
    b = []
    b.append(f'<rect x="24" y="24" width="712" height="472" rx="12" fill="{SURFACE}" stroke="{BORDER}"/>')
    b.append(f'<text x="48" y="60" fill="{TEXT}" font-size="15" font-weight="600">设置提醒</text>')
    b.append(f'<text x="48" y="80" fill="{TEXT3}" font-size="11">贵州茅台 600519.SH</text>')
    b.append(f'<text x="48" y="118" fill="{TEXT2}" font-size="12">提醒条件</text>')
    b.append(f'<rect x="48" y="130" width="300" height="38" rx="8" fill="{SURFACE2}" stroke="{BRAND}"/>')
    b.append(f'<text x="64" y="154" fill="{TEXT}" font-size="12">跌破我的研报合理价</text>')
    b.append(f'<text x="332" y="154" fill="{BRAND}" font-size="11">▾</text>')
    b.append(f'<rect x="48" y="182" width="664" height="52" rx="8" fill="{BRAND}" opacity="0.08" stroke="{BRAND}" stroke-opacity="0.3"/>')
    b.append(f'<text x="64" y="204" fill="{BRAND}" font-size="11">无需填写阈值 —— 自动取你最近一次研报给出的「合理市值下限」</text>')
    b.append(f'<text x="64" y="222" fill="{TEXT3}" font-size="10">总市值跌到它下方时提醒；该股未做过研报则不触发</text>')
    b.append(f'<text x="48" y="266" fill="{TEXT2}" font-size="12">当前设置</text>')
    b.append(f'<rect x="48" y="278" width="664" height="56" rx="8" fill="{SURFACE2}" stroke="{BORDER}"/>')
    b.append(f'<text x="64" y="300" fill="{TEXT}" font-size="12">总市值跌破我的研报合理下限</text>')
    b.append(f'<text x="64" y="320" fill="{TEXT3}" font-size="10">最近研报（10-02）合理市值下限 2,180 亿 · 当前 2,110 亿</text>')
    b.append(f'<text x="600" y="308" fill="{BRAND}" font-size="11">监测中</text>')
    b.append(f'<rect x="48" y="360" width="140" height="38" rx="8" fill="url(#g2)"/>')
    b.append(f'<text x="118" y="384" fill="#04121f" font-size="12" font-weight="600" text-anchor="middle">保存</text>')
    b.append(f'<rect x="200" y="360" width="140" height="38" rx="8" fill="none" stroke="{BORDER}"/>')
    b.append(f'<text x="270" y="384" fill="{TEXT2}" font-size="12" text-anchor="middle">取消</text>')
    b.append(f'<text x="48" y="440" fill="{TEXT3}" font-size="11">还支持：总市值 / 收盘价 / 涨跌幅 / 市盈率 / 市净率 / PB 历史分位 / 财报披露</text>')
    b.append(f'<text x="48" y="462" fill="{TEXT3}" font-size="11">提醒引擎在交易时段每小时评估一次</text>')
    defs = (f'<defs><linearGradient id="g2" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0%" stop-color="{BRAND}"/><stop offset="100%" stop-color="{BRAND2}"/>'
            f'</linearGradient></defs>')
    return shell(W, H, defs + "\n".join(b), "合理价告警设置",
                 "界面示意图，数值为演示数据")


GENS = {"home": gen_home, "report": gen_report, "review": gen_review,
        "stock": gen_stock, "alert": gen_alert}

if __name__ == "__main__":
    for name, fn in GENS.items():
        p = os.path.join(OUT, f"{name}.svg")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(fn())
        print(f"生成 {p}  ({os.path.getsize(p)//1024} KB)")