import time
from typing import Optional

import requests

import config

CODE_MSG = {
    0: "成功",
    1001: "缺少必填参数",
    1002: "参数格式错误",
    1003: "参数取值越界（如历史查询窗口超过上限）",
    1004: "参数冲突（如 start/end 与 limit 同时传）",
    2001: "未认证：X-api-key 缺失或无效",
    2003: "权限不足：该 API Key 无权调用此能力",
    3001: "标的不存在",
    3002: "数据未就绪（标的存在但暂无业务数据）",
    3004: "标的类型不支持该能力",
    4001: "频率超限（超过约定 QPS）",
    5001: "服务内部错误",
    5002: "上游服务超时",
    5003: "数据源不可用",
}

_BRAND_RE = None

def _clean_brand(text):
    global _BRAND_RE
    if not text:
        return text
    if _BRAND_RE is None:
        import re
        _BRAND_RE = re.compile(r"同花顺(?:iFinD|iFind|数据|财经|资讯)?")
    return _BRAND_RE.sub("", str(text)).strip()

def _api_key():
    try:
        import settings
        v = (settings.get_setting("FUYAO_API_KEY") or "").strip()
        if v:
            return v
    except Exception:
        pass
    return (getattr(config, "FUYAO_API_KEY", "") or "").strip()

def configured():
    return bool(_api_key())

def _request(path, params=None, timeout=None):
    key = _api_key()
    if not key:
        return None, "未配置 API Key（请在后台「金融数据源」填写，或在 .env 设置 FUYAO_API_KEY）"
    url = (getattr(config, "FUYAO_BASE_URL", "https://fuyao.aicubes.cn").rstrip("/")
           + "/" + str(path).lstrip("/"))
    tmo = timeout or getattr(config, "FUYAO_TIMEOUT", 20)
    try:
        r = requests.get(url, params=params or {}, headers={"X-api-key": key},
                         timeout=(8, tmo))
    except Exception as e:
        return None, f"请求失败：{type(e).__name__}: {e}"
    try:
        env = r.json()
    except Exception:
        return None, f"响应不是 JSON（HTTP {r.status_code}，前 120 字：{r.text[:120]}）"
    code = env.get("code")
    if code != 0:
        msg = CODE_MSG.get(code, env.get("message") or "未知错误")
        return None, f"code={code} {msg}"
    return env.get("data"), None

def _items(data, key="item"):
    if not isinstance(data, dict):
        return []
    v = data.get(key)
    return v if isinstance(v, list) else []

def _f(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None

def _pct(v, digits=2):
    f = _f(v)
    return None if f is None else f"{f * 100:.{digits}f}"

def _yi(v, digits=2):
    f = _f(v)
    return None if f is None else round(f / 1e8, digits)

def _ms_to_date(ms):
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except Exception:
        return None

def _date_to_ms(d):
    import datetime
    s = str(d or "").replace("-", "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        dt = datetime.datetime.strptime(s, "%Y%m%d").replace(hour=15, minute=0, second=0)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None

def snapshot(thscodes, timeout=None):
    if isinstance(thscodes, (list, tuple)):
        thscodes = ",".join(str(x) for x in thscodes)
    data, err = _request("/api/a-share/prices/snapshot", {"thscodes": thscodes}, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"),
            "code": it.get("ticker"),
            "price": _f(it.get("last_price")),
            "change": _pct(_f(it.get("price_change_ratio_pct")) and _f(it.get("price_change_ratio_pct")) / 100),
            "change_amount": _f(it.get("price_change")),
            "open": _f(it.get("open_price")),
            "high": _f(it.get("high_price")),
            "low": _f(it.get("low_price")),
            "prev_close": _f(it.get("prev_price")),
            "volume": _f(it.get("volume")),
            "amount": _f(it.get("turnover")),
            "timestamp": (data or {}).get("timestamp"),
        })
    return out, None

def historical(thscode, start, end, adjust="forward", interval="1d", timeout=None):
    s = start if isinstance(start, int) else _date_to_ms(start)
    e = end if isinstance(end, int) else _date_to_ms(end)
    if s is None or e is None:
        return [], "start / end 日期格式不正确（应为 YYYY-MM-DD 或 YYYYMMDD）"
    data, err = _request("/api/a-share/prices/historical", {
        "thscode": thscode, "interval": interval,
        "start": s, "end": e, "adjust": adjust,
    }, timeout)
    if err:
        return [], err
    rows = []
    for it in _items(data):
        d = _ms_to_date(it.get("date_ms"))
        if not d:
            continue
        rows.append({
            "date": d,
            "open": _f(it.get("open_price")),
            "high": _f(it.get("high_price")),
            "low": _f(it.get("low_price")),
            "close": _f(it.get("close_price")),
            "volume": _f(it.get("volume")),
            "amount": _f(it.get("turnover")),
        })
    rows.sort(key=lambda x: x["date"])
    return rows, None

def dragon_tiger(trade_date=None, board_type="all", timeout=None):
    params = {"board_type": board_type}
    if trade_date:
        params["trade_date"] = str(trade_date).replace("-", "")
    data, err = _request("/api/a-share/special-data/dragon-tiger-list", params, timeout)
    if err:
        return [], err
    if not isinstance(data, dict):
        return [], "响应结构异常"
    out = []
    for it in _items(data, "stock_items"):
        concepts = []
        for c in (it.get("concept_list") or []):
            nm = _clean_brand((c or {}).get("name"))
            if nm:
                concepts.append(nm)
        out.append({
            "ts_code": it.get("thscode"),
            "code": it.get("ticker"),
            "name": it.get("name"),
            "change": _pct(_f(it.get("change"))),
            "net_total_yi": _yi(it.get("net_value")),
            "net_rate": _pct(_f(it.get("net_rate"))),
            "buy_yi": _yi(it.get("buy_value")),
            "sell_yi": _yi(it.get("sell_value")),
            "hot_money_yi": _yi(it.get("hot_money_net_value")),
            "hot_rank": it.get("hot_rank"),
            "limit_reason": _clean_brand(it.get("limit_reason")),
            "concepts": concepts,
            "range_days": it.get("range_days"),
            "trade_date": data.get("trade_date"),
        })
    return out, None

def hot_stock_list(period="day", timeout=None):
    data, err = _request("/api/a-share/special-data/hot-stock-list", {"period": period}, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"),
            "code": it.get("ticker"),
            "name": it.get("name"),
            "rank": it.get("rank"),
            "heat": _f(it.get("heat")),
            "rank_change": it.get("rank_change"),
            "rank_trend": it.get("rank_trend"),
        })
    return out, None

def skyrocket_list(period="day", timeout=None):
    data, err = _request("/api/a-share/special-data/skyrocket-list", {"period": period}, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"), "code": it.get("ticker"), "name": it.get("name"),
            "rank": it.get("rank"), "heat": _f(it.get("heat")),
            "rank_change": it.get("rank_change"), "rank_trend": it.get("rank_trend"),
        })
    return out, None

def _norm_ymd(d):
    s = str(d or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s

def hot_stock_list_history(date, timeout=None):
    if not date:
        return [], "date 必填（格式 yyyy-MM-dd）"
    data, err = _request("/api/a-share/special-data/hot-stock-list-history",
                         {"date": _norm_ymd(date)}, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"), "code": it.get("ticker"), "name": it.get("name"),
            "rank": it.get("rank"), "date": (data or {}).get("date") or _norm_ymd(date),
        })
    return out, None

def hot_stock_rank_trend(thscode, start_date, end_date, timeout=None):
    data, err = _request("/api/a-share/special-data/hot-stock-rank-trend", {
        "thscode": thscode,
        "start_date": _norm_ymd(start_date),
        "end_date": _norm_ymd(end_date),
    }, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"), "code": it.get("ticker"),
            "date": it.get("date") or _ms_to_date(it.get("date_ms")),
            "rank": it.get("rank"),
        })
    return out, None

def anomaly_list(tag=None, timeout=None):
    params = {}
    if tag:
        params["tag"] = tag
    data, err = _request("/api/a-share/special-data/anomaly-analysis-list", params, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"), "code": it.get("ticker"), "name": it.get("name"),
            "change": _pct(_f(it.get("change"))),
            "anomaly_type": it.get("anomaly_type") or it.get("tag"),
            "reason": _clean_brand(it.get("reason") or it.get("anomaly_reason")),
            "date": it.get("date") or it.get("trade_date"),
        })
    return out, None

def anomaly_stock(thscodes, timeout=None):
    if isinstance(thscodes, (list, tuple)):
        thscodes = ",".join(str(x) for x in thscodes)
    data, err = _request("/api/a-share/special-data/anomaly-analysis-stock",
                         {"thscodes": thscodes}, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"), "code": it.get("ticker"), "name": it.get("name"),
            "change": _pct(_f(it.get("change"))),
            "anomaly_type": it.get("anomaly_type") or it.get("tag"),
            "reason": _clean_brand(it.get("reason") or it.get("anomaly_reason")),
        })
    return out, None

def limit_pool(kind="up", date=None, timeout=None):
    path = {
        "up": "/api/a-share/special-data/limit-up-pool",
        "down": "/api/a-share/special-data/limit-down-pool",
        "break": "/api/a-share/special-data/limit-break-pool",
    }.get(kind)
    if not path:
        return [], f"未知的股票池类型：{kind}"
    params = {}
    if date:
        params["trade_date"] = str(date).replace("-", "")
    data, err = _request(path, params, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"), "code": it.get("ticker"), "name": it.get("name"),
            "change": _pct(_f(it.get("change"))),
            "price": _f(it.get("last_price") or it.get("price")),
            "limit_days": it.get("limit_days") or it.get("continuous_days"),
            "first_limit_time": it.get("first_limit_time"),
            "reason": _clean_brand(it.get("reason") or it.get("limit_reason")),
            "turnover_yi": _yi(it.get("turnover")),
        })
    return out, None

def limit_up_ladder(timeout=None):
    data, err = _request("/api/a-share/special-data/limit-up-ladder", None, timeout)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "响应结构异常（非 dict）"

    window = data.get("window") or {}
    dates = [d for d in (window.get("date_list") or []) if isinstance(d, str)]
    caps = window.get("board_caps") or {}

    _TIER_NUM = {"two_board": 2, "three_board": 3, "four_board": 4,
                 "five_board": 5, "six_board": 6, "seven_over": 7}

    days = []
    for row in _items(data):
        if not isinstance(row, dict):
            continue
        boards = row.get("boards") or {}
        tiers, top, total = {}, None, 0
        for tkey, num in _TIER_NUM.items():
            lst = boards.get(tkey) or []
            if not isinstance(lst, list) or not lst:
                continue
            tiers[num] = len(lst)
            total += len(lst)
            if top is None or num > top["board"]:
                s = lst[0] if isinstance(lst[0], dict) else {}
                top = {
                    "ts_code": s.get("thscode"),
                    "code": s.get("ticker"),
                    "name": (s.get("name") or "").strip() or None,
                    "board": num,
                    "reason": _clean_brand(s.get("reason") or s.get("limit_reason")),
                }
        days.append({
            "date": row.get("date"),
            "tiers": tiers,
            "total": total,
            "max_board": max(tiers) if tiers else 0,
            "top": top,
        })

    days.sort(key=lambda x: str(x.get("date") or ""))
    return {"dates": dates, "days": days, "caps": caps,
            "window_days": window.get("length") or len(dates)}, None

def financial_indicators(thscode, report=None, timeout=None):
    params = {"thscode": thscode}
    if report:
        params["report"] = report
    data, err = _request("/api/a-share/financials/indicators", params, timeout)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "响应结构异常"
    groups = {}
    for ab in (data.get("abilities") or []):
        name = (ab or {}).get("ability")
        groups[name] = {}
        for ind in ((ab or {}).get("indicators") or []):
            groups[name][(ind or {}).get("index_id")] = (ind or {}).get("value")
    return {"thscode": data.get("thscode"), "report": data.get("report"), "groups": groups}, None

def ticker_search(q, timeout=None):
    data, err = _request("/api/meta/tickers/search", {"q": q}, timeout)
    if err:
        return [], err
    out = []
    for it in _items(data):
        out.append({
            "ts_code": it.get("thscode"), "code": it.get("ticker"), "name": it.get("name"),
            "exchange": it.get("exchange"), "asset_type": it.get("asset_type"),
            "currency": it.get("currency"),
        })
    return out, None

def calendar(timeout=None):
    data, err = _request("/api/a-share/calendar/trading-days", None, timeout)
    if err:
        return [], err
    days = []
    for it in _items(data):
        d = it.get("date") or _ms_to_date(it.get("date_ms"))
        if d:
            days.append(_norm_ymd(str(d)[:10]))
    return sorted(set(x for x in days if x)), None

def probe(timeout=15):
    t0 = time.time()
    rows, err = ticker_search("贵州茅台", timeout=timeout)
    if err:
        return False, err
    ms = int((time.time() - t0) * 1000)
    if not rows:
        return False, "接口通但无数据（Key 有效，可能无该能力权限）"
    top = rows[0]
    return True, f"连通正常 · {ms}ms · 样例 {top.get('ts_code')} {top.get('name')}"

if __name__ == "__main__":
    print("configured:", configured())
    ok, msg = probe()
    print("probe:", ok, msg)
