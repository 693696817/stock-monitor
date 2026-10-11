# -*- coding: utf-8 -*-
"""腾讯免费行情（qt.gtimg.cn，零鉴权、不封 IP）—— 行情兜底层。

字段索引（v_shXXXXXX="1~名称~代码~..." 按 ~ 分隔的序号）：
  [1]名称 [3]现价 [4]昨收 [5]今开 [31]涨跌 [32]涨跌幅% [33]最高 [34]最低
  [36]成交量(手) [37]成交额(万) [38]换手率% [39]PE(TTM)
  [44]流通市值(亿) [45]总市值(亿) [46]PB
  [30] YYYYMMDDHHMMSS 数据时间（盘中=当前，休市=上一交易日收盘）
单位口径：amount 是万元、volume 是手、市值是亿 —— 与理杏仁（元/股/元）不同，
换算责任在调用方。
"""
import re
import threading

import requests

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 6.0
_BATCH = 40
_lock = threading.Lock()
_fail_streak = 0
_BREAK_UNTIL = 0.0
_FAIL_LIMIT = 5
_BREAK_SECS = 120.0


def _symbol(ts_code):
    s = str(ts_code or "").strip().upper()
    m = re.match(r"^(\d{6})\.(SH|SZ|BJ)$", s)
    if m:
        code, mkt = m.group(1), m.group(2).lower()
    else:
        m2 = re.match(r"^(\d{6})$", s)
        if not m2:
            return None
        code = m2.group(1)
        if code[0] == "6":
            mkt = "sh"
        elif code[0] in ("0", "3"):
            mkt = "sz"
        elif code[0] in ("8", "4", "9"):
            mkt = "bj"
        else:
            return None
    if mkt == "sh":
        return f"sh{code}"
    if mkt == "sz":
        return f"sz{code}"
    return f"bj{code}"


def _num(fields, i):
    try:
        v = fields[i].strip()
        return float(v) if v not in ("", "-") else None
    except (IndexError, ValueError, TypeError):
        return None


def realtime(ts_codes):
    """批量实时行情 → {ts_code: 数值dict}；拉不到的为 None。"""
    global _fail_streak, _BREAK_UNTIL
    import time as _t
    out = {t: None for t in ts_codes}
    if not ts_codes:
        return out
    now = _t.time()
    if now < _BREAK_UNTIL:
        return out
    todo = [(t, _symbol(t)) for t in ts_codes]
    todo = [(t, s) for t, s in todo if s]
    for i in range(0, len(todo), _BATCH):
        chunk = todo[i:i + _BATCH]
        url = "https://qt.gtimg.cn/q=" + ",".join(s for _, s in chunk)
        try:
            r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
            text = r.content.decode("gbk", "replace")
            got = 0
            for m in re.finditer(r'v_([a-z]{2}\d{6})="([^"]*)"', text):
                sym, payload = m.group(1), m.group(2)
                f = payload.split("~")
                if len(f) < 49:
                    continue
                dt_raw = (f[30] if len(f) > 30 else "").strip()
                data_date = (f"{dt_raw[0:4]}-{dt_raw[4:6]}-{dt_raw[6:8]}"
                             if len(dt_raw) >= 8 and dt_raw[:8].isdigit() else None)
                q = {
                    "name": f[1],
                    "data_date": data_date,
                    "price": _num(f, 3),
                    "pre_close": _num(f, 4),
                    "open": _num(f, 5),
                    "change": _num(f, 31),
                    "change_pct": _num(f, 32),
                    "high": _num(f, 33),
                    "low": _num(f, 34),
                    "volume_hand": _num(f, 36),
                    "amount_wan": _num(f, 37),
                    "turnover_pct": _num(f, 38),
                    "pe_ttm": _num(f, 39),
                    "circ_mv_yi": _num(f, 44),
                    "total_mv_yi": _num(f, 45),
                    "pb": _num(f, 46),
                }
                if q["price"] is not None and q["price"] > 0:
                    got += 1
                    for t, s in chunk:
                        if s == sym:
                            out[t] = q
                            break
            with _lock:
                if got > 0:
                    _fail_streak = 0
                else:
                    _fail_streak += 1
                    if _fail_streak >= _FAIL_LIMIT:
                        _BREAK_UNTIL = _t.time() + _BREAK_SECS
                        _fail_streak = 0
        except Exception as e:
            print(f"[Tencent] realtime failed: {e}")
            with _lock:
                _fail_streak += 1
                if _fail_streak >= _FAIL_LIMIT:
                    _BREAK_UNTIL = _t.time() + _BREAK_SECS
                    _fail_streak = 0
    return out


def kline(ts_code, count=120, fq="qfq"):
    """日 K（前复权）→ [{'date','open','close','high','low','volume'}]；失败返回 []。"""
    sym = _symbol(ts_code)
    if not sym:
        return []
    fqpart = fq if fq in ("qfq", "hfq") else ""
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={sym},day,,,{int(count)},{fqpart}")
    try:
        r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
        j = r.json()
        d = (j.get("data") or {}).get(sym) or {}
        rows = d.get(f"{fq}day") or d.get("day") or []
        out = []
        for row in rows:
            if len(row) < 6:
                continue
            try:
                out.append({
                    "date": str(row[0])[:10],
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                })
            except (ValueError, TypeError):
                continue
        return out
    except Exception as e:
        print(f"[Tencent] kline failed {ts_code}: {e}")
        return []
