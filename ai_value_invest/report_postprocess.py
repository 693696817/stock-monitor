
import re
import json

UP_RED = "#f87171"
DOWN_GREEN = "#34d399"
AMBER = "#fbbf24"
GRAY = "#94a3b8"
BLUE = "#38bdf8"

_SEMANTIC_COLOR_MAP = [
    (r'^(red|darkred|firebrick|crimson|#e74c3c|#dc143c|#ff0000|#f00|#c0392b|#d32f2f|#ef4444|#ff4d4f)$', UP_RED),
    (r'^(green|darkgreen|seagreen|#2ecc71|#27ae60|#00ff00|#0f0|#4caf50|#22c55e|#00b050)$', DOWN_GREEN),
    (r'^(orange|darkorange|gold|#ffa500|#f39c12|#ff9800|#f59e0b|#ffc107)$', AMBER),
    (r'^(gray|grey|dimgray|dimgrey|silver|#808080|#95a5a6|#999999|#888888|#666666|#999|#888|#666)$', GRAY),
    (r'^(blue|dodgerblue|royalblue|#1e90ff|#007bff|#2196f3|#0066cc|#0d6efd)$', BLUE),
]

_HEX_RE = re.compile(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')
_RGB_RE = re.compile(r'^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$')
_NAMED_LIGHT = {
    "white": (255, 255, 255), "whitesmoke": (245, 245, 245), "snow": (255, 250, 250),
    "ivory": (255, 255, 240), "floralwhite": (255, 250, 240), "ghostwhite": (248, 248, 255),
    "azure": (240, 255, 255), "mintcream": (245, 255, 250), "lightcyan": (224, 255, 255),
    "lightyellow": (255, 255, 224), "beige": (245, 245, 220), "oldlace": (253, 245, 230),
    "linen": (250, 240, 230), "seashell": (255, 245, 238), "honeydew": (240, 255, 240),
}

def _parse_rgb(val: str):
    v = (val or "").strip().lower()
    m = _HEX_RE.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            r, g, b = (int(c * 2, 16) for c in h)
        else:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return r, g, b, 1.0
    m = _RGB_RE.match(v)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return r, g, b, a
    if v in _NAMED_LIGHT:
        r, g, b = _NAMED_LIGHT[v]
        return r, g, b, 1.0
    return None

def _is_light(val: str) -> bool:
    p = _parse_rgb(val)
    if not p:
        return False
    r, g, b, a = p
    if a < 0.5:
        return False
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return lum > 0.68

_OPENER_MARKERS = (
    "好的", "收到您的指令", "收到指令", "明白", "了解您的需求", "当然可以",
    "身为一名", "作为一名", "作为一个", "我将严格", "我将基于", "我会基于",
    "为您呈现", "为您提供", "为你呈现", "为你提供", "生成一份", "撰写一份",
    "以下是我", "下面我将", "遵照您的", "遵循你的纪律", "遵循您的纪律",
)

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.I | re.S)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>[\s\S]*$", re.I)

_REASON_PREFACE_WORDS = (
    "let me", "i think", "i need", "i will", "we need", "we should", "we must",
    "we'll", "we will", "user wants", "the user", "as an ai", "first,", "firstly",
    "my thought", "thinking process", "okay,", "ok,", "now,", "好了，",
    "好的，我", "好的，让我们", "让我", "我来", "我将", "我需要", "我们需",
    "现在，我", "首先，我", "用户要求", "用户希望", "根据用户", "我们要",
    "我们需", "我的思考", "思考过程",
    "大纲结构", "报告结构", "结构安排", "我们来构思", "先构思", "需要设计",
    "we must produce", "need to produce", "need output", "user asks",
)
_HEADING_LINE_RE = re.compile(r"^#{1,6}\s*\S", re.M)
_SENT_END = ("。", "！", "？", "；", "…", ".", "!", "?", "”", "’", "」", "）", ")", '"', "'")

def remove_think_blocks(md: str) -> str:
    if not md or "<think" not in md.lower():
        return md
    prev, cur = None, md
    while prev != cur:
        prev = cur
        cur = _THINK_BLOCK_RE.sub("", cur)
    return _THINK_OPEN_RE.sub("", cur)

def _is_reason_preface(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if len(t) <= 120:
        return True if not t.endswith(_SENT_END) else any(
            k in t.lower() for k in _REASON_PREFACE_WORDS)
    if len(t) > 6000:
        return False
    low = t.lower()
    return any(k in low for k in _REASON_PREFACE_WORDS)

def strip_reasoning_opener(md: str) -> str:
    if not md:
        return md
    m = _HEADING_LINE_RE.search(md)
    if not m:
        return md
    head, rest = md[:m.start()], md[m.start():]
    if not head.strip():
        return md
    if _is_reason_preface(head):
        return rest.lstrip("\n")
    return md

_ECHO_LABEL_RE = re.compile(
    r'^\s*(?:[-*•]\s*)?(?:Table|Content|Description of the run|Position judgment|'
    r'Trade plan|One sharp sentence|The conclusion block|Scenario [A-C]|Output)\s*:\s*',
    re.I,
)
_ECHO_META_LINE_RE = re.compile(
    r'^\s*(?:[-*•]\s*)?(?:'
    r'Length:\s*\d[\d\s\-~,，、]*\s*(?:Chinese characters|汉字|中文字符|字符)\.?'
    r'|Let me write it carefully\.?'
    r'|The conclusion block:?\.?'
    r'|One sharp sentence:?\.?'
    r')\s*$',
    re.I,
)
_ECHO_LENGTH_PREFIX_RE = re.compile(
    r'^Length:\s*\d[\d\s\-~,，、]*\s*(?:Chinese characters|汉字|中文字符|字符)', re.I)
_PLAN_PHRASE_NO_CJK_RE = re.compile(
    r'(let me write it carefully|the conclusion block|one sharp sentence)', re.I)

def _is_echo_line(t: str) -> bool:
    low = (t or "").strip()
    if not low:
        return False
    if _ECHO_META_LINE_RE.match(low):
        return True
    if _ECHO_LENGTH_PREFIX_RE.match(low):
        return True
    if _PLAN_PHRASE_NO_CJK_RE.search(low) and not re.search(r'[\u4e00-\u9fff]', low):
        return True
    return False

def strip_planning_echo(md: str) -> str:
    if not md:
        return md
    lines = md.split("\n")
    out = []
    for ln in lines:
        t = _ECHO_LABEL_RE.sub("", ln)
        if _is_echo_line(t):
            continue
        out.append(t)
    return "\n".join(out)

def _looks_like_opener(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 600:
        return False
    if not any(k in t for k in _OPENER_MARKERS):
        return False
    return bool(re.search(r'(我将|我会|让我|我来|身为|作为[一名一个]|为您|为你|呈现|提供)', t))

def strip_ai_opener(md: str) -> str:
    if not md:
        return md
    m = re.search(r'^#{1,6}\s+\S', md, re.M)
    if not m:
        return md
    head, rest = md[:m.start()], md[m.start():]
    if not head.strip():
        return md
    if _looks_like_opener(head):
        return rest.lstrip("\n")
    return md

_SIGNED_NUM_RE = re.compile(r'^\s*([+\-−＋－])\s*\d')

_STYLE_SPAN_RE = re.compile(
    r'<(?P<tag>span|font|b|strong|i|em)\b(?P<attrs>[^>]*)>(?P<inner>.*?)</(?P=tag)>',
    re.I | re.S)
_COLOR_DECL_RE = re.compile(r'(color\s*:\s*)([^;"\']+)', re.I)

def _map_color(val: str, inner_text: str) -> str:
    raw = (val or "").strip()
    plain = re.sub(r'[*`\s]', '', inner_text or "")
    m = _SIGNED_NUM_RE.match(plain)
    if m and re.match(r'^[+\-−＋－]?\s*[\d.,]+\s*[%％]?$', plain):
        sign = m.group(1)
        return DOWN_GREEN if sign in "-−－" else UP_RED
    key = raw.lower()
    for pat, target in _SEMANTIC_COLOR_MAP:
        if re.match(pat, key):
            return target
    return raw

def normalize_inline_colors(md: str) -> str:
    if not md or "color" not in md.lower():
        return md

    def _repl(m):
        tag, attrs, inner = m.group("tag"), m.group("attrs"), m.group("inner")
        if not _COLOR_DECL_RE.search(attrs):
            return m.group(0)

        def _c(dm):
            return dm.group(1) + _map_color(dm.group(2), inner)

        new_attrs = _COLOR_DECL_RE.sub(_c, attrs)
        return f"<{tag}{new_attrs}>{inner}</{tag}>"

    prev, cur = None, md
    for _ in range(3):
        prev, cur = cur, _STYLE_SPAN_RE.sub(_repl, cur)
        if prev == cur:
            break
    return cur

_BG_DECL_RE = re.compile(
    r'((?:background|background-color)\s*:\s*)([^;"\']+)', re.I)
_BORDER_DECL_RE = re.compile(
    r'(border(?:-top|-right|-bottom|-left)?\s*:\s*)([^;"\']+)', re.I)
_COLOR_TOKEN_RE = re.compile(
    r'#[0-9a-fA-F]{3,6}|rgba?\([^)]*\)|'
    r'\b(?:red|green|blue|white|black|gray|grey|silver|orange|yellow|gold|pink|purple|'
    r'navy|teal|maroon|olive|lime|aqua|fuchsia|crimson|salmon|tomato|khaki|plum|'
    r'ivory|beige|snow|linen|azure|mintcream|honeydew|seashell|oldlace|floralwhite|'
    r'ghostwhite|whitesmoke|lightcyan|lightyellow|lightgray|lightgrey|'
    r'darkred|darkgreen|darkblue|darkorange|dimgray|dimgrey|dodgerblue|royalblue|'
    r'firebrick|seagreen|goldenrod|steelblue|cornflowerblue)\b',
    re.I)

_DARK_BG = "rgba(255,255,255,0.04)"
_DARK_BORDER = "rgba(255,255,255,0.14)"

def harden_for_dark_theme(md: str) -> str:
    if not md:
        return md

    def _bg(dm):
        return dm.group(1) + (_DARK_BG if _is_light(dm.group(2)) else dm.group(2))

    out = _BG_DECL_RE.sub(_bg, md)

    def _bd(dm):
        body = dm.group(2)
        new_body = _COLOR_TOKEN_RE.sub(
            lambda cm: _DARK_BORDER if _is_light(cm.group(0)) else cm.group(0), body)
        return dm.group(1) + new_body

    return _BORDER_DECL_RE.sub(_bd, out)

_TRUNC_EMPTY_ITEM_RE = re.compile(r'^\s*(?:\d+\.|[-*+])\s*$')
_TERMINAL_PUNCT = "。！？!?；;：:）)】」】”’…"

def detect_truncation(md: str) -> bool:
    if not md:
        return False
    lines = [ln for ln in md.splitlines() if ln.strip()]
    if not lines:
        return False
    last = lines[-1].strip()
    if _TRUNC_EMPTY_ITEM_RE.match(last):
        return True
    if last.startswith(("|", "#", ">", "*", "-", "+", "<")):
        return False
    if any(last.endswith(p) for p in _TERMINAL_PUNCT):
        return False
    return len(last) > 25

_TRUNC_NOTE = (
    "\n\n> ⚠️ **注意**：本报告在生成过程中被截断（疑似触及模型输出长度上限），"
    "结尾内容不完整，结论可能未完结，请谨慎参考或重新生成。"
)

_FLAG_MARK = "本报告由人工智能模型自动生成"
_DISCLAIM_MARK = "免责声明"

_AI_FLAG_BLOCK = (
    "> ⚠️ **AI 生成内容｜本报告由人工智能模型自动生成**\n"
    "> 全文由「A股棱镜」的 AI 模型基于公开数据与量化指标自动推演，"
    "未经持牌证券分析师审阅，不构成投资建议；文中数据以交易所及上市公司公告为准。\n"
)

_DISCLAIMER_BLOCK = (
    "\n\n---\n\n"
    "> **免责声明**\n"
    ">\n"
    "> 一、本报告由「A股棱镜」的 AI 模型自动生成，属于公开信息的整理与算法推演结果，"
    "不构成证券投资建议、买卖要约或收益承诺，亦不构成针对任何个人的投资顾问服务。\n"
    "> 二、报告引用数据来自第三方公开渠道，本平台不对其准确性、完整性、时效性作出保证；"
    "数据可能存在延迟或口径差异，请以交易所及上市公司公告等官方披露为准。\n"
    "> 三、人工智能生成内容可能存在事实偏差、逻辑疏漏或表述不当，请自行核实并独立判断。\n"
    "> 四、股市有风险，入市需谨慎。据此操作，风险自担。\n"
)

_BYLINE_RE = re.compile(r"分析师\s*[：:]\s*(?:A股棱镜|极客\s*AI|极客|AI[^\s|、，,）)]{0,6})")

def normalize_byline(md: str, site_name: str = "A股棱镜") -> str:
    if not md or "分析师" not in md:
        return md
    head, rest = md[:600], md[600:]
    new_head, n = _BYLINE_RE.subn(f"生成引擎：{site_name} AI 模型", head, count=1)
    return (new_head + rest) if n else md

def inject_compliance(md: str, site_name: str = "A股棱镜") -> str:
    if not md or not md.strip():
        return md
    out = md
    if _FLAG_MARK not in out:
        flag = _AI_FLAG_BLOCK.replace("A股棱镜", site_name)
        out = flag + "\n" + out.lstrip("\n")
    if _DISCLAIM_MARK not in out:
        disc = _DISCLAIMER_BLOCK.replace("A股棱镜", site_name)
        out = out.rstrip() + "\n" + disc
    return out

def tidy_markdown(md: str) -> str:
    if not md:
        return md
    out = re.sub(r'\n{4,}', '\n\n\n', md)
    out = "\n".join(ln.rstrip() for ln in out.split("\n"))
    return out.rstrip() + "\n"

def postprocess_report(md: str, note_truncation: bool = True,
                       add_compliance: bool = True, site_name: str = "A股棱镜") -> str:
    if not md or not md.strip():
        return md
    out = remove_think_blocks(md)
    out = strip_reasoning_opener(out)
    out = strip_planning_echo(out)
    out = strip_ai_opener(out)
    out = normalize_inline_colors(out)
    out = harden_for_dark_theme(out)
    out = tidy_markdown(out)
    if note_truncation and detect_truncation(out) and "生成过程中被截断" not in out:
        out = out.rstrip() + _TRUNC_NOTE + "\n"
    if add_compliance:
        out = normalize_byline(out, site_name=site_name)
        out = inject_compliance(out, site_name=site_name)
    return out

BT_MARKER = "<!--BACKTEST-->"

_BT_MARKER_RE = re.compile(r"<!--\s*BACKTEST\s*-->", re.I)

def backtest_block_end(rest: str):
    if not rest:
        return None
    if re.search(r"```(?:json|JSON)?", rest):
        m = re.search(r"```(?:json|JSON)?\s*\{[\s\S]*?\}\s*```", rest)
        return m.end() if m else None
    s = rest.find("{")
    if s < 0:
        return None
    depth = 0
    for i in range(s, len(rest)):
        ch = rest[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None

def _extract_json_candidate(rest: str):
    if not rest:
        return None
    m = re.search(r"```(?:json|JSON)?\s*(\{[\s\S]*?\})\s*```", rest)
    if m:
        return m.group(1)
    m = re.search(r"```(?:json|JSON)?\s*(\{[\s\S]*)$", rest)
    if m:
        return m.group(1)
    end = backtest_block_end(rest)
    s = rest.find("{")
    if s >= 0 and end:
        return rest[s:end]
    return None

def split_backtest_block(md: str):
    if not md or BT_MARKER.lower() not in md.lower():
        return md, None
    m = _BT_MARKER_RE.search(md)
    if not m:
        return md, None
    rest = md[m.end():]
    end = backtest_block_end(rest)
    if end is None:
        if "{" in rest:
            return md[:m.start()], None
        return md[:m.start()] + rest, None
    return md[:m.start()] + rest[end:], _extract_json_candidate(rest)

def _loads_lenient(src: str):
    if not src:
        return None
    s = src.strip().lstrip("\ufeff")
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    s = re.sub(r"^\s*//.*$", "", s, flags=re.M)
    s = re.sub(r"'([^'\n]*)'(?=\s*[,}\]])", r'"\1"', s)
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    try:
        return json.loads(s)
    except Exception:
        return None

def _num(v, lo=None, hi=None):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        s = str(v).strip().replace(",", "").replace("，", "")
        s = re.sub(r"(亿元|亿|万元|万|元|%|％|倍|人民币|CNY|¥)", "", s)
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        x = float(m.group(0))
    if lo is not None and x < lo:
        return None
    if hi is not None and x > hi:
        return None
    return x

def extract_backtest_json(md: str):
    body, src = split_backtest_block(md)
    if not src:
        return body, None
    obj = _loads_lenient(src)
    if not isinstance(obj, dict):
        return body, None
    return body, _normalize_backtest(obj, src)

def _normalize_backtest(obj: dict, src: str = None):
    low = _num(obj.get("valuation_low"))
    high = _num(obj.get("valuation_high"))
    if low is not None and high is not None and low > high:
        low, high = high, low

    mid = _num(obj.get("valuation_mid"))
    if mid is None and low is not None and high is not None:
        mid = round((low + high) / 2.0, 2)

    score = _num(obj.get("score"), 0, 10)
    conf = _num(obj.get("confidence"), 1, 5)
    mc_now = _num(obj.get("mc_now"))

    upside = None
    if mid is not None and mc_now not in (None, 0):
        upside = round((mid - mc_now) / abs(mc_now) * 100.0, 2)

    if low is None and high is None and score is None:
        return None

    return {
        "valuation_low": low,
        "valuation_high": high,
        "valuation_mid": mid,
        "score": round(score, 1) if score is not None else None,
        "confidence": int(conf) if conf is not None else None,
        "verdict": str(obj.get("verdict") or "").strip()[:16] or None,
        "horizon": str(obj.get("horizon") or "").strip()[:16] or None,
        "key_reason": str(obj.get("key_reason") or "").strip()[:255] or None,
        "mc_now": mc_now,
        "price_now": _num(obj.get("price_now")),
        "pe_ttm_now": _num(obj.get("pe_ttm_now")),
        "pb_now": _num(obj.get("pb_now")),
        "upside_pct": upside,
        "raw": (src or "")[:4000] or None,
    }

def parse_backtest_json(md: str):
    return extract_backtest_json(md)[1]
