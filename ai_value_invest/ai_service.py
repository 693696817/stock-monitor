from openai import AsyncOpenAI
import asyncio
import datetime
import re
import time
import config
import settings

try:
    import httpx2 as httpx
except ImportError:
    import httpx

BACKTEST_PREFERENCES = ("long_term_value", "comprehensive", "deep_value")

def _length_budget(is_deep: bool):
    return (3500, 7000) if is_deep else (1800, 4500)

def _build_format_contract(is_deep: bool) -> str:
    lo, hi = _length_budget(is_deep)
    return (
        "## 📐 输出规范（必须严格遵守，违反任一 条即视为不合格报告）\n"
        "\n"
        "1. **直接写正文，禁止一切开场白**：不要输出「好的/收到/我将为您/作为一名分析师/"
        "以下是我…」这类角色自述或过渡句；第一个字符就应是下方大纲里的一级标题"
        "（形如 `# 股票名 (代码) …报告`），标题措辞照抄大纲，不得省略或改写。\n"
        "2. **严禁输出任何思考、推理或分析过程**：不要把「我的分析思路/推理步骤/内部思维/"
        "我打算怎么做」写出来；不要出现 `<think>` 标签、`Thinking`、`Let me`、`I think`、"
        "`we need to`、`思考过程`、`推理过程` 等字样。你只需要呈现最终分析结论，"
        "过程留给自己。\n"
        "3. **章节标题必须逐字照抄大纲**：正文的二级章节标题统一按大纲给定的 "
        "`## 一、…`（可含 emoji）逐条输出，**不得新增、删减、合并或改写任何章节**；"
        "每章写完后直接进入下一章，不要额外加「小结/总结」之类大纲没有的标题。\n"
        "4. **篇幅硬上限**：全文 " + str(lo) + "~" + str(hi) + " 个汉字，**"
        + str(hi) + " 字是硬上限，超过即判为不合格报告**。"
        "宁精勿水：只写你的判断与依据，**不要大段复述数据面板里已有的原始数字**"
        "（面板数据已完整给你，复述一遍等于注水）；不要为每个条目都配一段解释；"
        "不要为凑字数堆砌内容。写完大纲最后一个章节即停笔，"
        "不要再加「总结/展望/结语/写在最后」之类大纲上没有的收尾段落。"
        "如果预估写不完，就**压缩每章的展开深度**（每章抓最关键的 2~3 个判断），"
        "而不是突破上限；但任何情况下都不得省略大纲里的章节。\n"
        "5. **Markdown 卫生**：整篇报告不要用 ``` 代码块包裹；表格仅用于关键数据/指标对比；"
        "除大纲标题自带的 emoji 外不要额外堆砌图标；不要使用自定义颜色或 CSS。\n"
        "6. **全程简体中文**：正文一律用简体中文撰写，除 PE/PB/ROE/MA/BOLL 等金融缩写、"
        "指标名与数值外，不得出现英文句子。严禁把收到的写作要求、字数限制、章节规划、"
        "模板提示等复述或翻译成英文写进正文（不要出现 `Let me write it carefully`、"
        "`The conclusion block`、`Length: … characters`、`One sharp sentence`、`Content:` "
        "之类的英文草稿/规划话术）；也不要输出「（此处待补充/占位）」这类没写完的标记。\n"
    )

_BACKTEST_CONTRACT = """

## ⚠️ 投资结论速览（报告最后必须输出，不可省略）

报告正文全部写完后，必须在末尾另起一段，按下面的格式写一段投资结论速览。
这是后端程序解析的结构化数据，缺少它会导致回测台账数据缺失。

格式如下（用中文键值，直接写，不要用 JSON、不要用代码块、不要用表格）：

【投资结论】
合理市值区间：XXX ~ XXX 亿元
性价比评分：X.X
投资结论：低估/合理/高估/回避
置信度：X
建议持有：6m/12m/24m/36m
核心依据：一句话说明，不超过40字

字段口径：
- 合理市值区间：你测算的合理总市值区间，单位亿元，写成「下限 ~ 上限」。
- 性价比评分：0~10，可一位小数。10=极度低估且优秀，7~8=明显低估，5=合理，3~4=偏贵，0~2=严重高估或硬伤。
- 投资结论：只能填「低估」「合理」「高估」「回避」四选一。
- 置信度：1~5 的整数，5=非常高，1=拍脑袋。
- 建议持有：写成 6m / 12m / 24m / 36m 这种格式。
- 核心依据：一句话说明评分核心依据，不超过 40 个汉字。

再次提醒：报告正文写完后，必须以「【投资结论】」开头写一段上述格式的结论速览。
"""

def _resolve_model(model_key: str = None):
    return settings.resolve_ai_model(model_key)

def _siblings_of(model_entry_id: str):
    try:
        chan, m, reason = settings.locate_ai_model(model_entry_id)
        if reason or not m:
            return []
        alias = (m.get("alias") or "").strip()
        mid = (m.get("model_id") or "").strip()
        if not alias and not mid:
            return []
        out = []
        for c in settings.get_ai_model_channels():
            if not c.get("enabled"):
                continue
            for mm in c.get("models") or []:
                if not mm.get("enabled"):
                    continue
                if mm["id"] == model_entry_id:
                    continue
                same_alias = alias and (mm.get("alias") or "").strip() == alias
                same_mid = mid and (mm.get("model_id") or "").strip() == mid
                if same_alias or same_mid:
                    out.append((c, mm))
        return out
    except Exception:
        return []

def _order_candidates(channel: dict, model: dict):
    health = settings.get_model_health()
    cands = [(channel, model)]

    def _score(c, m):
        h = health.get(m.get("id")) or {}
        if h.get("ok") is True:
            return (0, h.get("ms") or 0)
        if h.get("ok") is False:
            return (2, 0)
        return (1, 0)

    sibs = sorted(_siblings_of(model.get("id")),
                  key=lambda cm: _score(cm[0], cm[1]))
    cands.extend(sibs)
    return cands

def _reason_of(delta) -> str:
    return (getattr(delta, "reasoning_content", None)
            or getattr(delta, "reasoning", None)
            or getattr(delta, "reasoning_text", None)
            or "")

def _split_delta(delta):
    return (getattr(delta, "content", None) or ""), _reason_of(delta)

def _delta_text(delta) -> str:
    return (getattr(delta, "content", None)
            or _reason_of(delta)
            or "")

def _CJK_RATIO(text: str) -> float:
    n = len(text)
    if not n:
        return 0.0
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff") / n

def _looks_like_body(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    return bool(_HEADING_RE.search(s))

_HEADING_RE = re.compile(r"(?:^|\n)#{1,6}\s*\S")
_CJK_CHARS_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_CHARS_RE = re.compile(r"[A-Za-z]")

_REASON_PREFACE_WORDS = (
    "let me", "i think", "i need", "i will", "we need", "we should", "we must",
    "we'll", "we will", "user wants", "the user", "as an ai", "first,", "firstly",
    "my thought", "thinking", "okay,", "ok,", "so,", "now,", "好了", "好的，我",
    "好的，让我们", "让我", "我来", "我将", "我需要", "我们需", "现在，我",
    "首先，我", "用户要求", "用户希望", "根据用户", "收到", "明白",
    "大纲结构", "报告结构", "结构安排", "我们来构思", "先构思", "需要设计",
    "we must produce", "need to produce", "need output", "user asks",
)

_SENT_END = ("。", "！", "？", "；", "…", ".", "!", "?", "”", "’", "」", "）", ")", '"', "'")

def _looks_like_reason_preface(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if len(t) <= 120:
        return True if not t.endswith(_SENT_END) else any(
            k in t.lower() for k in _REASON_PREFACE_WORDS)
    if len(t) > 3000:
        return False
    low = t.lower()
    return any(k in low for k in _REASON_PREFACE_WORDS)

def _strip_think_blocks(text: str) -> str:
    if not text or "<think" not in (text or "").lower():
        return text
    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = re.sub(r"<think\b[^>]*>.*?</think>", "", cur, flags=re.I | re.S)
    cur = re.sub(r"<think\b[^>]*>[\s\S]*$", "", cur, flags=re.I)
    return cur

def _sanitize_reason_passage(text: str) -> str:
    if not text:
        return text
    t = _strip_think_blocks(text)
    m = _HEADING_RE.search(t)
    if m and m.start() > 0:
        head = t[:m.start()]
        if _looks_like_reason_preface(head):
            return t[m.start():]
    return t

class _ThinkFilter:

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self):
        self._in_think = False
        self._tail = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._tail += text
        out = []
        while self._tail:
            if self._in_think:
                i = self._tail.find(self._CLOSE)
                if i < 0:
                    k = len(self._CLOSE) - 1
                    if len(self._tail) > k:
                        self._tail = self._tail[-k:]
                    break
                self._tail = self._tail[i + len(self._CLOSE):]
                self._in_think = False
            else:
                i = self._tail.find(self._OPEN)
                if i < 0:
                    k = len(self._OPEN) - 1
                    if len(self._tail) > k:
                        out.append(self._tail[:-k])
                        self._tail = self._tail[-k:]
                    break
                out.append(self._tail[:i])
                self._tail = self._tail[i + len(self._OPEN):]
                self._in_think = True
        return "".join(out)

    def peek(self, text: str) -> str:
        saved = (self._in_think, self._tail)
        try:
            return self.feed(text)
        finally:
            self._in_think, self._tail = saved

    def flush(self) -> str:
        rest = "" if self._in_think else self._tail
        self._tail = ""
        return rest

_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")
_THINK_PHRASES = ("let me", "hmm", "actually", "alternatively", "i should", "i need to",
                  "i'll use", "i will use", "let me finalize", "double-check", "wait,",
                  "let me think", "recompute", "sanity check", "to be consistent")

def _is_english_think(para: str) -> bool:
    s = (para or "").strip()
    if len(s) < 60:
        return False
    words = len(_LATIN_WORD_RE.findall(s))
    if words < 6:
        return False
    cjk = len(_CJK_CHARS_RE.findall(s))
    if cjk < len(s) * 0.12 and words >= 6:
        return True
    if words >= 8 and words >= cjk * 1.5:
        return True
    low = s.lower()
    return any(k in low for k in _THINK_PHRASES)

class _EnglishThinkFilter:

    def __init__(self):
        self._buf = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buf += text
        out = []
        while "\n\n" in self._buf:
            para, self._buf = self._buf.split("\n\n", 1)
            if not _is_english_think(para):
                out.append(para + "\n\n")
        return "".join(out)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        if rest.strip() and not _is_english_think(rest):
            return rest
        return ""

def _is_local_url(url: str) -> bool:
    return bool(re.match(r"^https?://(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:\d+)?",
                         (url or "").strip(), re.I))

def _is_local_channel(channel: dict) -> bool:
    return _is_local_url((channel or {}).get("base_url"))

def _volc_client(channel: dict = None):
    chan = channel
    if not chan:
        chan, _m = _resolve_model()
    if not chan:
        raise RuntimeError("未配置可用的 AI 模型渠道：请在后台「设置中心」添加并启用一个模型渠道。")

    base = (chan.get("base_url") or "")
    if _is_local_channel(chan):
        return AsyncOpenAI(base_url=base, api_key=chan.get("api_key"),
                           http_client=httpx.AsyncClient(proxy=None))
    return AsyncOpenAI(
        base_url=base,
        api_key=chan.get("api_key"),
    )

def _profile_temp(m) -> float:
    prof = (m or {}).get("profile")
    if not isinstance(prof, dict):
        return 0.0
    try:
        t = float(prof.get("temperature") or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(t, 2)

def _build_temp_ladder(profile_temp) -> list:
    try:
        first = round(float(profile_temp or 0), 2)
    except (TypeError, ValueError):
        first = 0.0
    if 0 < first <= 2:
        return list(dict.fromkeys([first, 0.6, 0.3, 1.0]))
    return [0.6, 0.3, 1.0]

_CHANNEL_FAILS: dict = {}
_CHANNEL_TRIP: dict = {}
_CHANNEL_TRIP_AFTER = 3
_CHANNEL_TRIP_SECS = 1800.0

def _channel_key(ch) -> str:
    return str((ch or {}).get("id") or (ch or {}).get("name") or "?")

def _channel_tripped(ch) -> bool:
    until = _CHANNEL_TRIP.get(_channel_key(ch))
    return bool(until and until > time.time())

def _note_channel_ok(ch):
    k = _channel_key(ch)
    _CHANNEL_FAILS.pop(k, None)
    _CHANNEL_TRIP.pop(k, None)

def _note_channel_fail(ch):
    k = _channel_key(ch)
    n = _CHANNEL_FAILS.get(k, 0) + 1
    _CHANNEL_FAILS[k] = n
    if n >= _CHANNEL_TRIP_AFTER:
        _CHANNEL_TRIP[k] = time.time() + _CHANNEL_TRIP_SECS
        _CHANNEL_FAILS.pop(k, None)

async def probe_endpoint(base_url: str, api_key: str, model_id: str,
                         alias: str = "", channel: str = "",
                         timeout: float = 45.0, extra: dict = None,
                         temperature: float = None):
    base_url = (base_url or "").strip()
    model_id = (model_id or "").strip()
    if not base_url:
        return {"ok": False, "ms": 0, "error": "未填写接口地址",
                "alias": alias, "model_id": model_id, "channel": channel}
    if not model_id:
        return {"ok": False, "ms": 0, "error": "未填写模型 ID",
                "alias": alias, "model_id": "", "channel": channel}
    if not (api_key or "").strip():
        return {"ok": False, "ms": 0, "error": "未填写 API Key",
                "alias": alias, "model_id": model_id, "channel": channel}

    t0 = time.time()
    try:
        _kw = dict(base_url=base_url, api_key=api_key, timeout=timeout)
        if _is_local_url(base_url):
            _kw["http_client"] = httpx.AsyncClient(proxy=None)
        client = AsyncOpenAI(**_kw)
        _temps = []
        try:
            _tp = float(temperature or 0)
        except (TypeError, ValueError):
            _tp = 0.0
        if 0 < _tp <= 2:
            _temps.append(round(_tp, 2))
        _temps.extend([0.0, 1.0])
        _temps = list(dict.fromkeys(_temps))
        resp = None
        for _ti, _t in enumerate(_temps):
            try:
                resp = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model_id,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=8,
                        temperature=_t,
                        stream=False,
                    ),
                    timeout=timeout,
                )
                break
            except Exception as _e:
                if "temperature" in str(_e).lower() and _ti + 1 < len(_temps):
                    continue
                raise
        ms = int((time.time() - t0) * 1000)
        if not getattr(resp, "choices", None):
            return {"ok": False, "ms": ms, "error": "接口无响应内容",
                    "alias": alias, "model_id": model_id, "channel": channel}
        out = {"ok": True, "ms": ms, "error": "",
               "alias": alias, "model_id": model_id, "channel": channel}
    except asyncio.TimeoutError:
        out = {"ok": False, "ms": int((time.time() - t0) * 1000),
               "error": f"上游响应超时（>{timeout:.0f}s，排队或限流）；地址与密钥正常，"
                        f"不代表模型不可用，可稍后重试",
               "alias": alias, "model_id": model_id, "channel": channel,
               "timeout_only": True}
    except Exception as e:
        out = {"ok": False, "ms": int((time.time() - t0) * 1000),
               "error": _short_err(e),
               "alias": alias, "model_id": model_id, "channel": channel}
    if extra:
        out.update(extra)
    return out

async def probe_model(model_id: str = None, timeout: float = 45.0, strict: bool = True):
    if strict:
        chan, m, reason = settings.locate_ai_model(model_id)
        if reason:
            return {"ok": False, "ms": 0,
                    "error": settings.describe_model_unavailable(reason),
                    "alias": (m or {}).get("alias", ""),
                    "model_id": (m or {}).get("model_id", "") or (model_id or ""),
                    "channel": (chan or {}).get("name", ""),
                    "reason": reason}
        return await probe_endpoint(chan.get("base_url"), chan.get("api_key"),
                                    m.get("model_id"), alias=m.get("alias", ""),
                                    channel=chan.get("name", ""), timeout=timeout,
                                    temperature=_profile_temp(m))

    chan, m = _resolve_model(model_id)
    if not chan or not m:
        return {"ok": False, "ms": 0, "error": "未找到该模型配置",
                "alias": "", "model_id": model_id or "", "channel": ""}
    return await probe_endpoint(chan.get("base_url"), chan.get("api_key"),
                                m.get("model_id"), alias=m.get("alias", ""),
                                channel=chan.get("name", ""), timeout=timeout,
                                temperature=_profile_temp(m))

def _short_err(e) -> str:
    msg = str(e)
    import re as _re
    m = _re.search(r"'code':\s*'([^']+)'", msg)
    m2 = _re.search(r"'message':\s*'([^']+)'", msg)
    if m or m2:
        parts = [p for p in ((m.group(1) if m else ""), (m2.group(1) if m2 else "")) if p]
        return " / ".join(parts)[:120]
    return msg.strip()[:120] or e.__class__.__name__

_RATE_LIMIT_MARKERS = (
    "429", "rate_limit", "rate limit", "rate-limit", "too many requests",
    "resources are currently busy", "model resources are currently busy",
    "insufficient_quota", "busy",
)

def _is_rate_limit_err(e) -> bool:
    sc = getattr(e, "status_code", None)
    if sc is not None and int(sc) == 429:
        return True
    msg = str(e).lower()
    return any(k in msg for k in _RATE_LIMIT_MARKERS)

def _get_preference(preference_id: str):
    prefs = settings.get_analysis_preferences()
    pref = next((p for p in prefs if p.get("id") == preference_id), None)
    if not pref:
        pref = next((p for p in prefs if p.get("id") == "long_term_value"), None) or {}
    return pref

async def analyze_stock_stream(stock_name: str, stock_code: str, data_summary: str,
                                model_id: str = None, preference_id: str = "long_term_value",
                                allow_vip: bool = False):
    pref = _get_preference(preference_id)
    FIRST_TOKEN_TIMEOUT = 150 if (pref and pref.get("is_deep")) else 100
    current_date = datetime.datetime.now().strftime("%Y年%m月%d日")

    if (model_id or "").strip():
        channel, model, reason = settings.locate_ai_model(model_id)
        if reason:
            why = settings.describe_model_unavailable(reason)
            yield f"\n\n**[系统错误] 所选模型不可用：{why}。请在页面上方换一个模型后重试，本次不扣次数。**"
            return
    else:
        channel, model = _resolve_model(None)
    if not channel or not model:
        yield "\n\n**[系统错误] 未配置可用的 AI 模型，请联系管理员在后台「系统设置 → AI 大模型」中添加并启用模型。**"
        return

    if _is_local_channel(channel):
        FIRST_TOKEN_TIMEOUT = max(FIRST_TOKEN_TIMEOUT, 300)

    pref = _get_preference(preference_id)
    system_prompt_template = pref.get("system_prompt") or _get_preference("long_term_value").get("system_prompt", "")

    system_prompt = system_prompt_template.format(
        stock_name=stock_name,
        stock_code=stock_code,
        current_date=current_date,
    )

    _lo, _hi = _length_budget(bool(pref and pref.get("is_deep")))
    user_prompt = (
        f"请根据以下详尽的数据面板撰写报告。\n"
        f"篇幅要求：全文 {_lo}~{_hi} 个汉字，{_hi} 字是硬上限，超过即不合格；"
        f"面板里的原始数据已给足，正文中不要逐条复述数字，只写你的判断与依据。\n\n"
        f"{data_summary}"
    )

    system_prompt = _build_format_contract(bool(pref and pref.get("is_deep"))) + "\n\n" + system_prompt.rstrip()
    if (pref.get("id") or "") in BACKTEST_PREFERENCES:
        system_prompt = system_prompt.rstrip() + "\n\n" + _BACKTEST_CONTRACT
        user_prompt += "\n\n⚠️ 报告正文写完后，必须在末尾以「【投资结论】」开头写一段投资结论速览（合理市值区间/评分/结论/置信度/持有期/核心依据），格式见系统提示。"

    async def _iter_with_first_timeout(stream, thinker=None):
        deadline = asyncio.get_event_loop().time() + FIRST_TOKEN_TIMEOUT
        t_start = asyncio.get_event_loop().time()
        hard_deadline = t_start + FIRST_TOKEN_TIMEOUT * 3
        saw_thinking = False
        first_chunk = None
        _skipped = []
        try:
            while True:
                now = asyncio.get_event_loop().time()
                remaining = deadline - now
                if remaining <= 0:
                    if saw_thinking and now < hard_deadline:
                        deadline = now + FIRST_TOKEN_TIMEOUT
                        remaining = FIRST_TOKEN_TIMEOUT
                    else:
                        raise asyncio.TimeoutError()
                chunk = await asyncio.wait_for(stream.__anext__(), timeout=remaining)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) or ""
                reason = _reason_of(delta)
                if not text and not reason:
                    continue
                if text and thinker is not None:
                    text = thinker.peek(text)
                    if not text.strip():
                        saw_thinking = True
                        _skipped.append(chunk)
                        continue
                if not text.strip() and not reason.strip():
                    continue
                first_chunk = chunk
                break
        except asyncio.TimeoutError:
            try:
                await stream.close()
            except Exception:
                pass
            raise
        except StopAsyncIteration:
            return
        for _c in _skipped:
            yield _c
        yield first_chunk
        async for chunk in stream:
            yield chunk

    state = {"last_err": None, "produced": False, "chan_names": []}

    async def _run_candidates(cands):
        for _ch, _m in cands:
            if _channel_tripped(_ch):
                print(f"⚡ [AI] 渠道「{_ch.get('name') or '?'}」处于熔断期"
                      f"（{int(_CHANNEL_TRIP_SECS // 60)} 分钟内连续失败 "
                      f"{_CHANNEL_TRIP_AFTER} 次），本次分析已跳过")
                continue
            produced = False
            channel_name = _ch.get("name") or "?"
            try:
                client = _volc_client(_ch)
                real_model = _m.get("model_id") or config.VOLC_MODEL_ID
                _is_deep = bool(pref and pref.get("is_deep"))
                _prof = _m.get("profile")
                _prof = _prof if isinstance(_prof, dict) else {}
                _prof_tokens = _prof.get("tokens")
                _prof_tokens = _prof_tokens if isinstance(_prof_tokens, dict) else {}
                _mode_key = "deep" if (pref and pref.get("is_deep")) else "normal"
                try:
                    _base_tok = int(_prof_tokens.get(_mode_key) or 0)
                except (TypeError, ValueError):
                    _base_tok = 0
                _MAX_TOKENS = _base_tok or (24000 if (pref and pref.get("is_deep")) else 16000)
                try:
                    _max_out = int(_prof.get("max_out") or 0)
                except (TypeError, ValueError):
                    _max_out = 0
                if _max_out > 0 and _MAX_TOKENS > _max_out:
                    _MAX_TOKENS = max(_max_out, 4096)
                if _is_deep and _MAX_TOKENS < 12288:
                    raise RuntimeError(
                        f"渠道「{channel_name}」输出上限仅 {_MAX_TOKENS} token，"
                        f"不足以完成深度研报，已跳过该渠道")
                _TEMPS = _build_temp_ladder(_prof.get("temperature"))
                _instr = str(_prof.get("instruction") or "").strip()

                _extra_body = _prof.get("extra_body")
                if not isinstance(_extra_body, dict):
                    _extra_body = None
                if _extra_body is None:
                    _base_l = (_ch.get("base_url") or "").lower()
                    if "volces.com" in _base_l:
                        _extra_body = {"thinking": {"type": "disabled"}}
                    elif "maas.aliyuncs.com" in _base_l:
                        _extra_body = {"enable_thinking": False}
                    elif "api.deepseek.com" in _base_l:
                        _extra_body = {"thinking": {"type": "disabled"}}

                async def _mk_stream(temp, max_tok):
                    sys_text = system_prompt
                    if _instr:
                        sys_text = system_prompt.rstrip() + "\n\n" + _instr
                    kw = dict(
                        model=real_model,
                        messages=[
                            {"role": "system", "content": sys_text},
                            {"role": "user", "content": user_prompt},
                        ],
                        stream=True,
                        temperature=temp,
                        max_tokens=max_tok,
                    )
                    if _extra_body:
                        kw["extra_body"] = _extra_body
                    return await client.chat.completions.create(**kw)

                stream = None
                _last_err = None

                async def _establish() -> bool:
                    nonlocal stream, _last_err
                    _is_deep = bool(pref and pref.get("is_deep"))
                    _floor_tok = 12288 if _is_deep else 8192
                    _mid_steps = (20000, 16000) if _is_deep else (10000,)
                    _tok_list = [_MAX_TOKENS]
                    for _step in _mid_steps:
                        if _floor_tok <= _step < _MAX_TOKENS:
                            _tok_list.append(_step)
                    if _MAX_TOKENS > _floor_tok:
                        _tok_list.append(_floor_tok)
                    _tok_list = list(dict.fromkeys(_tok_list))
                    for _tok in _tok_list:
                        for _ti, _t in enumerate(_TEMPS):
                            try:
                                stream = await _mk_stream(_t, _tok)
                                return True
                            except Exception as _e:
                                _last_err = _e
                                _msg = str(_e).lower()
                                if (_ti + 1 < len(_TEMPS)
                                        and any(k in _msg for k in ("temperature", "top_p", "topp"))):
                                    continue
                                if _tok > _floor_tok and any(
                                        k in _msg for k in
                                        ("max_tokens", "max tokens", "too large", "context", "length")):
                                    break
                                if _is_rate_limit_err(_e):
                                    return False
                                raise
                    return False

                for _attempt in range(3):
                    if await _establish():
                        break
                    if not _is_rate_limit_err(_last_err):
                        break
                    await asyncio.sleep(6.0 * (_attempt + 1))
                if stream is None:
                    raise _last_err

                _REASON_PROBE_LIMIT = 1200
                _REASON_GIVEUP = 30000
                _REASON_GIVEUP_SECS = 240.0 if _is_local_channel(_ch) else 180.0
                _BODY_MIN_CHARS = 3000 if _is_deep else 1500
                _MIN_HEADINGS = 4 if _is_deep else 3
                _SOFT_CAP_CHARS = 14000 if _is_deep else 8000
                _REASON_FLUSH_SECS = 2.5
                reason_buf = []
                saw_content = False
                reason_as_body = False
                _dropped_reason = 0
                _body_chars = 0
                _heading_count = 0
                _body_cjk = 0
                _body_latin = 0
                _english_drift = False
                _think_runaway = False
                _t_start = None
                _t_flush = time.time()
                thinker = _ThinkFilter()
                eng_filt = _EnglishThinkFilter()

                def _take(s):
                    nonlocal _body_chars, _heading_count, _body_cjk, _body_latin
                    if s:
                        _body_chars += len(s)
                        _heading_count += len(_HEADING_RE.findall(s))
                        _body_cjk += len(_CJK_CHARS_RE.findall(s))
                        _body_latin += len(_LATIN_CHARS_RE.findall(s))
                    return s

                _finish_reason = None
                async for chunk in _iter_with_first_timeout(stream, thinker):
                    if not chunk.choices:
                        continue
                    _fr = getattr(chunk.choices[0], "finish_reason", None)
                    if _fr:
                        _finish_reason = _fr
                    delta = chunk.choices[0].delta
                    text, reason = _split_delta(delta)
                    if text:
                        text = thinker.feed(text)
                        if not text:
                            continue
                        text = eng_filt.feed(text)
                        if not text:
                            continue
                        if not saw_content:
                            saw_content = True
                            reason_buf.clear()
                        produced = True
                        yield _take(text)
                        if _body_chars > _SOFT_CAP_CHARS:
                            print(f"✂️ [AI] 正文已达 {_body_chars} 字（软上限 "
                                  f"{_SOFT_CAP_CHARS}），主动收尾以节省时间")
                            break
                    elif reason and not saw_content:
                        if reason_as_body:
                            produced = True
                            yield _take(_sanitize_reason_passage(reason))
                            continue
                        reason_buf.append(reason)
                        if (sum(len(x) for x in reason_buf) < _REASON_PROBE_LIMIT
                                and (time.time() - _t_flush) < _REASON_FLUSH_SECS):
                            continue
                        blob = "".join(reason_buf)
                        reason_buf.clear()
                        _t_flush = time.time()
                        if not blob.strip():
                            continue
                        if not _looks_like_body(blob):
                            _dropped_reason += len(blob)
                            if _t_start is None:
                                _t_start = time.time()
                            if (_dropped_reason > _REASON_GIVEUP
                                    or (time.time() - _t_start) > _REASON_GIVEUP_SECS):
                                _think_runaway = True
                                break
                            continue
                        reason_as_body = True
                        produced = True
                        yield _take(_sanitize_reason_passage(blob))
                if not saw_content and not reason_as_body and reason_buf:
                    blob = "".join(reason_buf)
                    reason_buf.clear()
                    if blob.strip() and _looks_like_body(blob):
                        produced = True
                        yield _take(_sanitize_reason_passage(blob))
                _rest = eng_filt.feed(thinker.flush()) + eng_filt.flush()
                if _rest.strip():
                    produced = True
                    yield _take(_rest)
                _truncated_by_budget = bool(produced and _finish_reason == "length")
                _letters = _body_cjk + _body_latin
                _en_ratio = (_body_latin / _letters) if _letters else 0.0
                _english_drift = bool(produced and _letters >= 200 and _en_ratio > 0.40)
                if produced and (_body_chars < _BODY_MIN_CHARS
                                 or _heading_count < _MIN_HEADINGS
                                 or _dropped_reason > _body_chars * 6):
                    produced = False
                    _think_runaway = True
                if _truncated_by_budget:
                    produced = False
                if _english_drift:
                    produced = False
                if produced:
                    _note_channel_ok(_ch)
                    state["produced"] = True
                    return
                if _truncated_by_budget:
                    state["last_err"] = (
                        f"输出被模型长度上限截断（正文只写了 {_body_chars} 字就没预算了，"
                        f"渠道：{channel_name}）。这是该渠道输出额度不够写完深度报告，"
                        f"换一个模型即可；本次不扣次数。")
                elif _english_drift:
                    state["last_err"] = (
                        f"正文以英文为主、中文字母占比仅 {1.0 - _en_ratio:.0%}，"
                        f"疑似模型跑偏或英文思考泄漏，报告不可用；"
                        f"建议换一个模型重试，本次不扣次数。")
                elif _think_runaway:
                    state["last_err"] = (
                        f"该模型只顾思考、正文不完整（思考 {_dropped_reason} 字 / "
                        f"正文 {_body_chars} 字）")
                else:
                    state["last_err"] = "接口返回空内容"
                _note_channel_fail(_ch)
            except asyncio.TimeoutError:
                if _is_local_channel(_ch):
                    state["last_err"] = (
                        f"本地模型响应超时：等待首个字节超过 {FIRST_TOKEN_TIMEOUT} 秒"
                        f"（渠道：{channel_name}）。本地模型受本机算力限制，"
                        f"处理这么长的提示词可能确实力不从心，建议换一个云端模型；"
                        f"本次不扣次数。"
                    )
                else:
                    state["last_err"] = (
                        f"模型响应超时：等待首个字节超过 {FIRST_TOKEN_TIMEOUT} 秒"
                        f"（渠道：{channel_name}）。这是上游大模型排队或限流导致的，"
                        f"与股票代码无关，建议稍后重试或换一个模型；本次不扣次数。"
                    )
                _note_channel_fail(_ch)
            except Exception as e:
                if _is_rate_limit_err(e):
                    state["last_err"] = (
                        "上游模型资源繁忙（限流），通常 1~2 分钟内自行恢复，"
                        "可稍后重试或先换一个模型，本次不扣次数。" + str(e))
                else:
                    state["last_err"] = str(e)
                _note_channel_fail(_ch)
            state["chan_names"].append(channel_name)

    async for chunk in _run_candidates(_order_candidates(channel, model)):
        yield chunk
    if state["produced"]:
        return

    chan_names = "、".join(state["chan_names"]) or (channel.get("name") or "?")
    yield f"\n\n**[系统错误] AI 推理中断**（已尝试渠道：{chan_names}）：{state['last_err']}"
