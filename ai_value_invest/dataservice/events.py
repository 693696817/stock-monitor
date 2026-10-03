import datetime
import time

import lixinger_service as lx_svc

_ANN_CACHE = {}

_HOT_LIST_CACHE = {"ts": 0.0, "rows": None}
_HOT_LIST_TTL = 600

_DRAGON_CACHE = {}

def _code6(ts_code):
    return str(ts_code or "").split(".")[0]

def _yi(v):
    if v is None or v == "":
        return None
    return v

def task_announcement(ts_code):
    try:
        now = time.time()
        hit = _ANN_CACHE.get(ts_code)
        if hit and now - hit[0] < _ANN_TTL:
            data = hit[1]
        else:
            data = lx_svc.fetch_announcement(ts_code, days=365) or []
            _ANN_CACHE[ts_code] = (now, data)
        items = [x for x in (data or [])
                 if isinstance(x, dict) and (x.get("linkText") or x.get("title"))]
        if not items:
            return {}
        items.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
        top = items[:10]
        lines = []
        for x in top:
            d = str(x.get("date") or "")[:10]
            t = str(x.get("linkText") or x.get("title") or "").strip()
            if t:
                lines.append(f"{d} {t}")
        if not lines:
            return {}
        return {
            "公告数据日期": str(top[0].get("date") or "")[:10],
            "近一年公告条数": len(items),
            "近期公告": "；".join(lines),
        }
    except Exception as e:
        print(f"⚠️ [面板] 公告采集失败（已跳过）: {type(e).__name__}: {e}")
        return {}

def _hot_list_cached():
    now = time.time()
    if _HOT_LIST_CACHE["rows"] and now - _HOT_LIST_CACHE["ts"] < _HOT_LIST_TTL:
        return _HOT_LIST_CACHE["rows"]
    try:
        import settings
        import fuyao_client
        if not settings.fuyao_enabled():
            return None
        rows, err = fuyao_client.hot_stock_list(timeout=8)
        if err or not rows:
            return None
        _HOT_LIST_CACHE["rows"] = rows
        _HOT_LIST_CACHE["ts"] = now
        return rows
    except Exception:
        return None

def task_hotrank(ts_code):
    try:
        import settings
        import fuyao_client
        if not settings.fuyao_enabled():
            return {}
        today = datetime.date.today()
        start = today - datetime.timedelta(days=14)
        pts, _err = fuyao_client.hot_stock_rank_trend(
            ts_code, start.isoformat(), today.isoformat(), timeout=8)
        pts = [p for p in (pts or [])
               if p.get("rank") is not None and p.get("date")]
        if not pts:
            return {}
        pts.sort(key=lambda p: str(p.get("date")))
        ranks = [int(p["rank"]) for p in pts]
        latest, first = ranks[-1], ranks[0]
        out = {
            "人气榜排名(最新)": f"第 {latest} 名",
            "人气榜排名日期": str(pts[-1].get("date"))[:10],
            "近14日最佳排名": f"第 {min(ranks)} 名",
            "近14日排名变化(正数=降温)": latest - first,
        }
        c6 = _code6(ts_code)
        for h in (_hot_list_cached() or []):
            if _code6(h.get("ts_code") or h.get("code")) == c6:
                out["人气榜Top30在榜"] = f"第 {h.get('rank')} 名"
                if h.get("heat") is not None:
                    out["人气热度值"] = h.get("heat")
                break
        return out
    except Exception as e:
        print(f"⚠️ [面板] 人气榜采集失败（已跳过）: {type(e).__name__}: {e}")
        return {}

def _match_dragon(rows, code6):
    for r in (rows or []):
        if _code6(r.get("stock_code") or r.get("code") or r.get("ts_code")) == code6:
            return r
    return None

def _dragon_block(rec):
    out = {}
    if rec.get("trade_date"):
        out["龙虎榜上榜日期"] = str(rec.get("trade_date"))[:10]
    if rec.get("change") not in (None, ""):
        out["龙虎榜当日涨跌幅"] = f"{rec.get('change')} %"
    if _yi(rec.get("net_total_yi")) is not None:
        out["龙虎榜净买入(亿)"] = rec.get("net_total_yi")
    if _yi(rec.get("buy_yi")) is not None:
        out["龙虎榜买入额(亿)"] = rec.get("buy_yi")
    if _yi(rec.get("sell_yi")) is not None:
        out["龙虎榜卖出额(亿)"] = rec.get("sell_yi")
    if _yi(rec.get("hot_money_yi")) is not None:
        out["龙虎榜游资净额(亿)"] = rec.get("hot_money_yi")
    if rec.get("net_rate") not in (None, ""):
        out["龙虎榜净买入占成交比"] = f"{rec.get('net_rate')} %"
    if rec.get("limit_reason"):
        out["龙虎榜上榜原因"] = rec.get("limit_reason")
    cps = rec.get("concepts") or []
    if isinstance(cps, (list, tuple)) and cps:
        out["龙虎榜涉及概念"] = "、".join(str(c) for c in cps[:6])
    if rec.get("hot_rank") not in (None, ""):
        out["上榜时人气排名"] = f"第 {rec.get('hot_rank')} 名"
    return out

def task_dragon(ts_code):
    try:
        import settings
        import fuyao_client
        if not settings.fuyao_enabled():
            return {}
        c6 = _code6(ts_code)
        now = time.time()
        hit = _DRAGON_CACHE.get(c6)
        if hit and now - hit[0] < _DRAGON_TTL:
            return dict(hit[1])

        from dataservice.market import fetch_fuyao_dragon_tiger
        rec = _match_dragon(rows, c6)

        checked, offset = 0, 0
        while rec is None and checked < 3 and offset < 8:
            offset += 1
            d = datetime.date.today() - datetime.timedelta(days=offset)
            if d.weekday() >= 5:
                continue
            r2, _e2 = fuyao_client.dragon_tiger(
                trade_date=d.strftime("%Y%m%d"), timeout=8)
            checked += 1
            rec = _match_dragon(r2, c6)

        if rec:
            out = _dragon_block(rec)
            if not out:
                out = {"龙虎榜": "近期上榜，但明细字段缺失"}
            out["近期是否上榜"] = "是"
        else:
            out = {"近期是否上榜": "否",
                   "龙虎榜": f"最近 3 个交易日（截至 "
                             f"{(datetime.date.today()).strftime('%Y-%m-%d')}）无上榜记录"}
        _DRAGON_CACHE[c6] = (now, out)
        return dict(out)
    except Exception as e:
        print(f"⚠️ [面板] 龙虎榜采集失败（已跳过）: {type(e).__name__}: {e}")
        return {}
