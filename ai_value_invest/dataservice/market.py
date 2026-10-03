
import datetime
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import db
import lixinger_service as lx_svc
from data_source import fetch_datahub, fetch_news_datahub
from dataservice import common as dscommon
from dataservice.common import SENTIMENT_ZONES, _CACHE_DIR, _WATCH_FUND_METRICS, _WATCH_KLINE_DAYS, _fetch_safe, _get_stock_list_safe, _guess_exchange, _latest_trade_date_datahub, _lookup_name_from_cache, _lx_name, _lx_rows, _lx_yi, _now_shanghai, _pulse_pick, _safe_float, analyze_sentiment_keywords, is_trading_time, pro
from lixinger import LixingerError, get_client

_BREADTH_CACHE = {"key": None, "data": None, "ts": 0}
_BREADTH_TTL = 300
_AK_BREADTH_CACHE = {"data": None, "ts": 0}
_AK_BREADTH_TTL = 180

def _breadth_from_pulse(trade_date):
    try:
        dfp = _market_pulse(trade_date)
        if dfp is None or dfp.empty or "pct_chg" not in dfp.columns:
            return None
        pct = pd.to_numeric(dfp["pct_chg"], errors="coerce").dropna()
        if pct.empty:
            return None
        up = int((pct > 0).sum())
        down = int((pct < 0).sum())
        flat = int(len(pct) - up - down)
        return {
            "up_count": f"{up:,}", "down_count": f"{down:,}", "flat_count": f"{flat:,}",
            "up": up, "down": down, "flat": flat, "total": f"{len(pct):,}",
            "up_ratio": f"{up / len(pct) * 100:.1f}%",
            "date": trade_date, "source": "pulse", "volume": None,
        }
    except Exception as e:
        print(f"⚠️ [Breadth] 主源(全市场脉搏)异常: {e}")
        return None

def _breadth_from_akshare():
    global _AK_BREADTH_CACHE
    now = time.time()
    if _AK_BREADTH_CACHE["data"] and (now - _AK_BREADTH_CACHE["ts"] < _AK_BREADTH_TTL):
        return _AK_BREADTH_CACHE["data"]
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        pct = pd.to_numeric(df["涨跌幅"], errors="coerce").dropna()
        if pct.empty:
            return _AK_BREADTH_CACHE["data"]
        up = int((pct > 0).sum()); down = int((pct < 0).sum()); flat = int(len(pct) - up - down)
        data = {
            "up_count": f"{up:,}", "down_count": f"{down:,}", "flat_count": f"{flat:,}",
            "up": up, "down": down, "flat": flat, "total": f"{len(pct):,}",
            "up_ratio": f"{up / len(pct) * 100:.1f}%",
            "date": datetime.datetime.now().strftime("%Y%m%d"), "source": "akshare",
            "volume": f"{pd.to_numeric(df['成交额'], errors='coerce').sum() / 1e8:,.0f}",
        }
        _AK_BREADTH_CACHE.update({"data": data, "ts": now})
        return data
    except Exception as e:
        print(f"⚠️ [Breadth] 备源(AKShare)异常: {e}")
        return _AK_BREADTH_CACHE["data"]

def get_market_breadth(trade_date=None):
    global _BREADTH_CACHE
    trade_date = trade_date or _latest_trade_date_datahub()
    now = time.time()
    if _BREADTH_CACHE["data"] and _BREADTH_CACHE["key"] == trade_date \
            and (now - _BREADTH_CACHE["ts"] < _BREADTH_TTL):
        return _BREADTH_CACHE["data"]

    data = _breadth_from_pulse(trade_date) or _breadth_from_akshare()
    if data:
        _BREADTH_CACHE.update({"key": trade_date, "data": data, "ts": now})
    return data

def _empty_index(name):
    return {"name": name, "price": "--", "change_pct": "--",
            "change_val": "--", "is_up": None, "history": []}

def get_market_overview_datahub(include_fuyao=False):
    trade_date = _latest_trade_date_datahub()
    end = trade_date
    start = (datetime.datetime.strptime(trade_date, "%Y%m%d") - datetime.timedelta(days=45)).strftime("%Y%m%d")

    result = {
        "sh": _empty_index("上证指数"), "sz": _empty_index("深证成指"), "cy": _empty_index("创业板指"),
        "north_fund": "--", "north_is_up": None, "north_date": None,
        "up_count": "-", "down_count": "-", "flat_count": "-", "volume": "-",
        "breadth_total": "-", "breadth_date": None, "breadth_up": 0, "breadth_down": 0,
        "breadth_flat": 0, "breadth_pct": None,
        "sh_amount": "-", "sz_amount": "-", "limit_count": "-",
        "sh_hist": [], "north_hist": [],
        "ladder": None, "pools": None, "hot_rank": None, "sentiment_parts": [],
        "sentiment_zones": SENTIMENT_ZONES, "sentiment_zone": None,
        "sentiment": 50, "sentiment_label": "中性",
        "provider": "金融大数据", "trade_date": trade_date,
        "update_time": datetime.datetime.now().strftime("%H:%M"),
    }

    indices = [("sh", "000001.SH", "上证指数"), ("sz", "399001.SZ", "深证成指"), ("cy", "399006.SZ", "创业板指")]
    sh_amt = sz_amt = None
    rates = []
    for key, code, name in indices:
        df, st = fetch_datahub("index_daily", {"ts_code": code, "start_date": start, "end_date": end, "limit": 45})
        if df is not None and not df.empty:
            df = df.sort_values("trade_date")
            latest = df.iloc[-1]
            pre = float(latest["pre_close"]); close = float(latest["close"])
            pct = float(latest["pct_chg"]); chg = close - pre
            result[key] = {
                "name": name, "price": f"{close:.2f}", "change_pct": f"{pct:.2f}",
                "change_val": f"{chg:.2f}", "is_up": chg >= 0,
                "history": [round(float(x), 2) for x in df["close"].tolist()],
            }
            rates.append(pct)
            if code == "000001.SH":
                sh_amt = float(latest["amount"])
            elif code == "399001.SZ":
                sz_amt = float(latest["amount"])

    if sh_amt is not None:
        result["sh_amount"] = f"{sh_amt / 1e5:,.0f}"
    if sz_amt is not None:
        result["sz_amount"] = f"{sz_amt / 1e5:,.0f}"
    if sh_amt is not None and sz_amt is not None:
        result["volume"] = f"{(sh_amt + sz_amt) / 1e5:,.0f}"

    if time.time() < _HSGT_STATE["dead_until"]:
        dfn = None
    else:
        dfn, stn = fetch_datahub("moneyflow_hsgt", {
            "start_date": (datetime.datetime.strptime(end, "%Y%m%d") - datetime.timedelta(days=20)).strftime("%Y%m%d"),
            "end_date": end,
            "limit": 30,
        })
        if dfn is None or getattr(dfn, "empty", True):
            _HSGT_STATE["dead_until"] = time.time() + 3600
            print("ℹ️ [Market] 北向接口不可用（供应商下架 + 交易所停止披露），北向卡片显示 --")
    if dfn is not None and not dfn.empty:
        try:
            dfn = dfn.sort_values("trade_date")
            row = dfn.iloc[-1]
            north_yi = float(row.get("north_money") or 0) / 1e4
            result["north_fund"] = f"{north_yi:+.2f}亿"
            result["north_is_up"] = north_yi >= 0
            result["north_date"] = str(row.get("trade_date") or "")
            hgt = float(row.get("hgt") or 0) / 1e4
            sgt = float(row.get("sgt") or 0) / 1e4
            result["north_hist"] = [round(hgt, 2), round(sgt, 2), round(north_yi, 2)]
            if result["north_date"] and result["north_date"] != end:
                print(f"ℹ️ [Market] 北向资金 {end} 尚未落地（沪深港通 T+1），已回退到 {result['north_date']}")
        except Exception as e:
            print(f"⚠️ [Market] 北向资金解析异常: {e}")

    breadth = get_market_breadth(trade_date)
    if breadth:
        result.update({
            "up_count": breadth["up_count"],
            "down_count": breadth["down_count"],
            "flat_count": breadth["flat_count"],
            "breadth_total": breadth["total"],
            "breadth_date": breadth["date"],
            "breadth_up": breadth["up"], "breadth_down": breadth["down"], "breadth_flat": breadth["flat"],
            "breadth_pct": [breadth["up"] / max(breadth["up"] + breadth["down"] + breadth["flat"], 1) * 100,
                            breadth["flat"] / max(breadth["up"] + breadth["down"] + breadth["flat"], 1) * 100,
                            breadth["down"] / max(breadth["up"] + breadth["down"] + breadth["flat"], 1) * 100],
        })
        if breadth.get("volume") and result["volume"] == "-":
            result["volume"] = breadth["volume"]

    rows_top, _lhb_src = get_dragon_tiger_cached("desc", limit=100)
    if rows_top:
        result["limit_count"] = str(len(rows_top))

    if include_fuyao:
        _attach_fuyao_sentiment(result)

    _compute_sentiment(result, rows_top)

    result["sh_hist"] = result["sh"].get("history", [])[-30:]
    return result

def _attach_fuyao_sentiment(result):
    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_lim = ex.submit(get_market_limit_stats)
            f_hot = ex.submit(get_market_hot_rank)
            lim, hot = f_lim.result(), f_hot.result()
    except Exception as e:
        print(f"⚠️ [Market] 伏尧情绪增强失败（已降级）：{type(e).__name__}: {e}")
        return
    if isinstance(lim, dict):
        result["ladder"] = lim.get("ladder")
        result["pools"] = lim.get("pools")
    if isinstance(hot, dict):
        result["hot_rank"] = hot

def _sentiment_zone(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    for i, z in enumerate(SENTIMENT_ZONES):
        if z["min"] <= v < z["max"]:
            return dict(z, index=i)
    last = SENTIMENT_ZONES[-1]
    return dict(last, index=len(SENTIMENT_ZONES) - 1)

def _compute_sentiment(result, rows_top):
    bias = 0.0
    parts = []

    if rows_top:
        try:
            nets = [float(r.get("net_total_yi") or 0) for r in rows_top]
            if nets:
                up_top = sum(1 for n in nets if n > 0)
                b = (up_top / len(nets) - 0.5) * 38
                bias += b
                parts.append(f"龙虎榜{up_top}/{len(nets)}净买入 {b:+.1f}")
        except Exception as e:
            print(f"⚠️ [Market] 龙虎榜情绪分项异常: {e}")

    nup = result.get("north_is_up")
    if nup is not None:
        b = 8 if nup else -8
        bias += b
        parts.append(f"北向{'流入' if nup else '流出'} {b:+.1f}")

    ladder = result.get("ladder")
    if isinstance(ladder, dict):
        mb = ladder.get("max_board")
        if isinstance(mb, (int, float)):
            b = max(-1.0, min(1.0, (mb - 4) / 4)) * 12
            bias += b
            parts.append(f"最高{int(mb)}板 {b:+.1f}")

    pools = result.get("pools")
    if isinstance(pools, dict):
        up_n = pools.get("up") or 0
        dn_n = pools.get("down") or 0
        if up_n + dn_n:
            b = (up_n / (up_n + dn_n) - 0.5) * 24
            bias += b
            parts.append(f"涨停跌停比 {up_n}:{dn_n} {b:+.1f}")

    senti = max(2, min(98, 50 + bias))
    result["sentiment"] = round(senti, 1)
    result["sentiment_label"] = ("贪婪" if senti >= 70 else "乐观" if senti >= 58 else
                                 "中性" if senti >= 45 else "谨慎" if senti >= 30 else "恐慌")
    result["sentiment_parts"] = parts
    result["sentiment_zones"] = SENTIMENT_ZONES
    result["sentiment_zone"] = _sentiment_zone(senti)

def _enrich_rank_quotes(items):
    def _one(it):
        code = it.get("code")
        if not code:
            return
        ex = _guess_exchange(code) or "SH"
        ts_code = f"{code}.{ex}"
        try:
            df, st = fetch_datahub("daily", {"ts_code": ts_code, "limit": 1}, timeout=15)
            if df is not None and not getattr(df, "empty", True):
                r = df.iloc[-1]
                try:
                    close = float(r.get("close"))
                    it["price"] = f"{close:.2f}"
                except Exception:
                    pass
                try:
                    pct = float(r.get("pct_chg"))
                    it["change"] = f"{pct:.2f}"
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ [Rank] 行情补全失败 {ts_code}: {type(e).__name__}: {e}")

    if not items:
        return
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(_one, items))

def fetch_lixinger_top_list(sort_field="tatnpa_last", limit=20, sort_order="desc", timeout=30):
    try:
        rows = get_client().get("cn/company/hot/t_a",
                                sortName=sort_field, sortOrder=sort_order,
                                pageIndex=1, pageSize=max(1, min(int(limit), 100)))
    except LixingerError as e:
        print(f"⚠️ [Lixinger] 龙虎榜请求失败: {e}")
        return None, "error"
    if not rows:
        return None, "empty"
    return rows, "ok"

LIXINGER_TOP_FETCH_LIMIT = 100

def get_lixinger_top_list_cached(sort_field="tatnpa_last", sort_order="desc", limit=100):
    sort_key = f"{sort_field}:{sort_order}"
    snap = _now_shanghai().strftime("%Y-%m-%d")
    try:
        from db import (list_lixinger_top_list, upsert_lixinger_top_list,
                        ensure_lixinger_top_list_table)
        ensure_lixinger_top_list_table()
        cached = list_lixinger_top_list(snap, sort_key, LIXINGER_TOP_FETCH_LIMIT)
    except Exception as e:
        print(f"⚠️ [LixingerTop] 读缓存异常: {type(e).__name__}: {e}")
        cached = None
    if cached:
        return cached[:limit], "ok"

    api_rows, st = fetch_lixinger_top_list(sort_field, limit=LIXINGER_TOP_FETCH_LIMIT,
                                           sort_order=sort_order)
    if api_rows and st == "ok":
        norm = []
        for it in api_rows:
            code = str(it.get("stockCode", "")).strip()
            if not code or not code.isdigit():
                continue
            norm.append({
                "stock_code": code,
                "net_total_yi": float(it.get("tatnpa_last") or 0) / 1e8,
                "net_org_yi": float(it.get("tainpa_last") or 0) / 1e8,
                "last_data_date": str(it.get("last_data_date") or "")[:10],
            })
        try:
            ensure_lixinger_top_list_table()
            upsert_lixinger_top_list(norm, snap, sort_key)
        except Exception as e:
            print(f"⚠️ [LixingerTop] 写缓存异常: {type(e).__name__}: {e}")
        return norm[:limit], "ok"
    return None, st or "error"

_FUYAO_LHB_CACHE = {"ts": 0.0, "rows": None}
_FUYAO_LHB_TTL = 3 * 3600

def fetch_fuyao_dragon_tiger(force=False):
    if not force and _FUYAO_LHB_CACHE["rows"] and (time.time() - _FUYAO_LHB_CACHE["ts"]) < _FUYAO_LHB_TTL:
        return _FUYAO_LHB_CACHE["rows"], None
    try:
        import settings
        import fuyao_client
        if not settings.fuyao_enabled():
            return None, "伏尧数据源未启用或未配置 Key"
        rows, err = fuyao_client.dragon_tiger()
        if err or not rows:
            return None, err or "伏尧龙虎榜返回空"
        norm = []
        for r in rows:
            r = dict(r)
            r.setdefault("stock_code", r.get("code") or "")
            norm.append(r)
        _FUYAO_LHB_CACHE["rows"] = norm
        _FUYAO_LHB_CACHE["ts"] = time.time()
        return norm, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def get_dragon_tiger_cached(sort_order="desc", limit=100):
    limit = max(1, min(int(limit or 100), 200))
    rows, err = fetch_fuyao_dragon_tiger()
    if rows:
        rev = (sort_order != "asc")
        ordered = sorted(rows, key=lambda r: float(r.get("net_total_yi") or 0), reverse=rev)
        return ordered[:limit], "伏尧"
    if err:
        print(f"⚠️ [龙虎榜] 伏尧源不可用（{err}），回落理杏仁")
    old, _st = get_lixinger_top_list_cached("tatnpa_last", sort_order, limit=limit)
    return (old or []), ("理杏仁" if old else "")

_KPL_CACHE = {"date": None, "df": None, "status": None, "ts": 0}
def _fetch_kpl_concept_datahub(trade_date, timeout=30):
    now = time.time()
    if (_KPL_CACHE["date"] == trade_date and _KPL_CACHE["df"] is not None
            and (now - _KPL_CACHE["ts"] < 600)):
        return _KPL_CACHE["df"], _KPL_CACHE["status"]
    df, st = fetch_datahub("kpl_concept", {"trade_date": trade_date, "limit": 50}, timeout=timeout)
    _KPL_CACHE["date"] = trade_date
    _KPL_CACHE["df"] = df
    _KPL_CACHE["status"] = st
    _KPL_CACHE["ts"] = now
    return df, st

_HSGT_TOP10_CACHE = {"date": None, "df": None, "status": None, "ts": 0}
def _fetch_hsgt_top10_datahub(trade_date, timeout=30):
    now = time.time()
    if (_HSGT_TOP10_CACHE["date"] == trade_date and _HSGT_TOP10_CACHE["df"] is not None
            and (now - _HSGT_TOP10_CACHE["ts"] < 600)):
        return _HSGT_TOP10_CACHE["df"], _HSGT_TOP10_CACHE["status"]
    df, st = fetch_datahub("hsgt_top10", {"trade_date": trade_date, "limit": 10}, timeout=timeout)
    _HSGT_TOP10_CACHE["date"] = trade_date
    _HSGT_TOP10_CACHE["df"] = df
    _HSGT_TOP10_CACHE["status"] = st
    _HSGT_TOP10_CACHE["ts"] = now
    return df, st

_PAGE_TTL_TRADING = 300
_PAGE_TTL_CLOSED = 1800

OPP_CACHE = {"key": None, "data": None, "ts": 0}
RISK_CACHE = {"key": None, "data": None, "ts": 0}
WATCH_QUOTE_CACHE = {}
_WATCH_TTL_TRADING = 120
_WATCH_TTL_CLOSED = 900

def _page_ttl(trading_ttl, closed_ttl):
    try:
        return trading_ttl if is_trading_time() else closed_ttl
    except Exception:
        return closed_ttl

def _page_cache_get(cache, trade_date, trading_ttl=_PAGE_TTL_TRADING,
                    closed_ttl=_PAGE_TTL_CLOSED):
    if cache.get("data") is None:
        return None
    if cache.get("key") != trade_date:
        return None
    if time.time() - cache.get("ts", 0) >= _page_ttl(trading_ttl, closed_ttl):
        return None
    return cache["data"]

def _page_cache_set(cache, trade_date, data):
    cache["key"] = trade_date
    cache["data"] = data
    cache["ts"] = time.time()
    return data

_PULSE_CACHE = {"date": None, "data": None, "ts": 0}
_PULSE_TTL = 900
_PULSE_BUILDING = False
_PULSE_LOCK = threading.Lock()

def _pulse_file(trade_date):
    return os.path.join(_CACHE_DIR, f"pulse_{trade_date}.json")

def _pulse_build(trade_date, days_back=5):
    for delta in range(0, days_back + 1):
        d = datetime.datetime.strptime(str(trade_date), "%Y%m%d").date() \
            - datetime.timedelta(days=delta)
        td = d.strftime("%Y%m%d")
        df = _pulse_build_one(td)
        if df is not None and not df.empty:
            if delta:
                print(f"[pulse] {trade_date} 行情数据未落地，已回退到 {td}")
            return df
    return None

def _pulse_build_one(trade_date):
    d_daily = dscommon._fetch_all_pages(
        pro.daily, "daily", trade_date=trade_date,
        fields='ts_code,close,pre_close,pct_chg,vol,amount')
    if d_daily is None or d_daily.empty:
        return None
    d_basic = dscommon._fetch_all_pages(
        pro.daily_basic, "daily_basic", trade_date=trade_date,
        fields='ts_code,pe_ttm,pb,dv_ttm,total_mv,turnover_rate')
    d_flow = dscommon._fetch_all_pages(pro.moneyflow, "moneyflow", trade_date=trade_date)
    if d_basic is None or d_basic.empty:
        return None

    df = d_daily.copy()
    df["ts_code"] = df["ts_code"].astype(str)
    df = df.set_index("ts_code")

    b = d_basic.copy()
    b["ts_code"] = b["ts_code"].astype(str)
    b = b.set_index("ts_code")
    for col in ("pe_ttm", "pb", "dv_ttm", "total_mv", "turnover_rate"):
        if col in b.columns:
            df[col] = pd.to_numeric(b[col], errors="coerce")

    if d_flow is not None and not d_flow.empty:
        f = d_flow.copy()
        f["ts_code"] = f["ts_code"].astype(str)
        f = f.set_index("ts_code")
        if "net_mf_amount" in f.columns:
            df["net_mf_yi"] = pd.to_numeric(f["net_mf_amount"], errors="coerce") / 1e4
        elif "net_amount" in f.columns:
            df["net_mf_yi"] = pd.to_numeric(f["net_amount"], errors="coerce") / 1e4

    for c in ("close", "pre_close", "pct_chg", "amount"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "amount" in df.columns:
        df["amount_yi"] = df["amount"] / 1e5

    return df

def _pulse_file_ttl():
    if is_trading_time():
        return 900
    now = _now_shanghai()
    if now.weekday() < 5 and datetime.time(15, 0) < now.time() <= datetime.time(20, 0):
        return 1800
    return 6 * 3600

def _market_pulse(trade_date):
    global _PULSE_BUILDING
    now = time.time()
    if _PULSE_CACHE["data"] is not None and _PULSE_CACHE["date"] == trade_date \
            and now - _PULSE_CACHE["ts"] < _PULSE_TTL:
        return _PULSE_CACHE["data"]

    fp = _pulse_file(trade_date)
    if os.path.exists(fp):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                obj = json.load(f)
            df = pd.DataFrame(obj["rows"]).set_index("ts_code")
            _PULSE_CACHE.update({"date": trade_date, "data": df, "ts": now})
            built_at = float(obj.get("built_at") or 0)
            if time.time() - built_at < _pulse_file_ttl():
                return df
            print(f"[pulse] 脉搏缓存已过期（{int(time.time() - built_at)}s），后台重建中，本次先用旧数据")
        except Exception as e:
            print(f"[pulse] 本地缓存读取失败: {e}")

    def _build_async():
        global _PULSE_BUILDING
        try:
            df = _pulse_build(trade_date)
            if df is None or df.empty:
                print("[pulse] 全市场脉搏构建失败（本次不缓存，稍后可重试）")
                return
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                with open(fp, 'w', encoding='utf-8') as f:
                    json.dump({"trade_date": trade_date,
                               "built_at": time.time(),
                               "rows": df.reset_index().to_dict("records")},
                              f, ensure_ascii=False, default=str)
            except Exception as e:
                print(f"[pulse] 脉搏落盘失败（不影响使用）: {e}")
            _PULSE_CACHE.update({"date": trade_date, "data": df, "ts": time.time()})
            print(f"[pulse] 全市场脉搏构建完成：{len(df)} 只")
        except Exception as e:
            print(f"[pulse] 构建异常: {e}")
        finally:
            _PULSE_BUILDING = False

    with _PULSE_LOCK:
        if not _PULSE_BUILDING:
            _PULSE_BUILDING = True
            threading.Thread(target=_build_async, daemon=True).start()
            print("[pulse] 全市场脉搏首次后台构建中，本次机会/风险页先降级")
    return None

_HSGT_STATE = {"dead_until": 0.0}

def _north_money_yi(trade_date, limit=5):
    if time.time() < _HSGT_STATE["dead_until"]:
        return None
    try:
        dfn, _ = fetch_datahub("moneyflow_hsgt", {"trade_date": trade_date, "limit": limit})
    except Exception as e:
        print(f"⚠️ [North] 北向资金异常: {e}")
        return None
    if dfn is None or getattr(dfn, "empty", True):
        _HSGT_STATE["dead_until"] = time.time() + 3600
        return None
    try:
        v = dfn.iloc[0].get("north_money")
    except Exception:
        return None
    if v is None or pd.isna(v):
        return None
    try:
        return float(v) / 1e4
    except (TypeError, ValueError):
        return None

def _build_theme_list(df_kpl, limit=8):
    if df_kpl is None or getattr(df_kpl, "empty", True):
        return []
    df = df_kpl.copy()
    for src, dst in (("z_t_num", "zt_num"), ("up_num", "up_num")):
        df[dst] = pd.to_numeric(df[src], errors="coerce") if src in df.columns else pd.NA
    df = df[df["zt_num"].notna() | df["up_num"].notna()]
    if df.empty:
        return []
    df = df.sort_values(["zt_num", "up_num"], ascending=[False, False],
                        na_position="last").head(limit)

    def _as_int(v):
        if v is None or pd.isna(v):
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    items = []
    for _, r in df.iterrows():
        nm = r.get("name")
        if nm is None or pd.isna(nm):
            continue
        nm = str(nm).strip()
        if not nm:
            continue
        items.append({"name": nm, "zt_num": _as_int(r.get("zt_num")),
                      "up_num": _as_int(r.get("up_num"))})
    return items

def get_opportunities_data_sync():
    now = time.time()
    trade_date = _latest_trade_date_datahub()

    _hit = _page_cache_get(OPP_CACHE, trade_date)
    if _hit is not None:
        return _hit

    out = {
        "sentiment": 50, "sentiment_label": "中性",
        "theme_list": [], "opportunities": [],
        "provider": "金融大数据", "trade_date": trade_date,
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if dscommon.STOCK_LIST_CACHE is None or dscommon.STOCK_LIST_CACHE.empty:
        _get_stock_list_safe()

    rows_top, _lhb_src = get_dragon_tiger_cached("desc", limit=100)

    north_yi = _north_money_yi(trade_date)
    out["north_money_yi"] = north_yi
    out["north_is_up"] = None if north_yi is None else (north_yi >= 0)

    _compute_sentiment(out, rows_top)

    if rows_top:
        by_net = sorted([r for r in rows_top if float(r.get("net_total_yi") or 0) > 0],
                        key=lambda r: float(r.get("net_total_yi") or 0), reverse=True)[:2]
        name_map, pct_map, missing = {}, {}, []
        for r in by_net:
            code = r["stock_code"]
            if r.get("name"):
                name_map[code] = r["name"]
            if r.get("change") not in (None, "", "--"):
                pct_map[code] = r["change"]
            else:
                missing.append({"code": code})
        if missing:
            _enrich_rank_quotes(missing)
            for it in missing:
                if it.get("change") not in (None, "", "--"):
                    pct_map[it["code"]] = it["change"]
        for r in by_net:
            net = float(r.get("net_total_yi") or 0)
            code = r["stock_code"]
            ex = _guess_exchange(code) or "SH"
            name = name_map.get(code) or _lookup_name_from_cache(code, ex) or code
            pct = pct_map.get(code)
            has_pct = pct not in (None, "", "--")
            pct_txt = f"当日涨 {pct}%" if has_pct else "（收盘价涨跌以最新日线计）"
            reason = (r.get("limit_reason") or "").strip()
            reason_txt = f"上榜原因：{reason}。" if reason else ""
            out["opportunities"].append({
                "tag": "龙虎榜抢筹",
                "cat": "capital",
                "title": f"龙虎榜主力净买入居前：{name}",
                "confidence": "高确信度" if net >= 2 else "中确信度",
                "level": "high" if net >= 2 else "mid",
                "summary": f"龙虎榜累计净买入居前，获主力净买入 {net:.2f} 亿元，{pct_txt}。"
                           f"{reason_txt}资金抢筹迹象明显（口径：金融大数据龙虎榜汇总）。",
                "evidence": f"龙虎榜净买入 {net:.2f} 亿元"
                            + (f" · 涨跌 {pct}%" if has_pct else ""),
                "stocks": [{"code": code, "name": name}],
            })

    df_kpl, _ = _fetch_kpl_concept_datahub(trade_date)
    themes = _build_theme_list(df_kpl)
    out["theme_list"] = themes
    if themes:
        top_c = themes[0]
        zt_n, up_n = top_c["zt_num"], top_c["up_num"]
        if zt_n is not None and up_n is not None:
            hot_txt = f"当日涨停 {zt_n} 家、板块内上涨 {up_n} 家"
            evi_txt = f"板块涨停 {zt_n} 家 · 上涨 {up_n} 家"
        elif up_n is not None:
            hot_txt = f"当日板块内上涨 {up_n} 家（涨停数未披露）"
            evi_txt = f"板块上涨 {up_n} 家 · 涨停数未披露"
        elif zt_n is not None:
            hot_txt = f"当日涨停 {zt_n} 家（上涨家数未披露）"
            evi_txt = f"板块涨停 {zt_n} 家 · 上涨家数未披露"
        else:
            hot_txt = evi_txt = None
        if zt_n:
            out["opportunities"].append({
                "tag": "题材风口",
                "cat": "theme",
                "title": f"最强风口题材：{top_c['name']}",
                "confidence": "中确信度",
                "level": "mid",
                "summary": f"概念人气榜显示「{top_c['name']}」{hot_txt}，"
                           f"题材热度居前，资金关注度较高。",
                "evidence": evi_txt,
                "stocks": [],
            })

    df_h, _ = _fetch_hsgt_top10_datahub(trade_date)
    if df_h is not None and not df_h.empty:
        df_h = df_h.copy()
        df_h["amt"] = pd.to_numeric(df_h.get("amount"), errors="coerce")
        df_h["chg"] = pd.to_numeric(df_h.get("change"), errors="coerce")
        top_h = df_h.dropna(subset=["amt"]).sort_values("amt", ascending=False).head(1)
        if not top_h.empty:
            r = top_h.iloc[0]
            code = str(r["ts_code"]).split(".")[0]
            name = str(r["name"])
            chg = r["chg"]
            has_chg = pd.notna(chg)
            out["opportunities"].append({
                "tag": "北向重点",
                "cat": "capital",
                "title": f"北向资金十大成交活跃：{name}",
                "confidence": "中确信度",
                "level": "mid",
                "summary": f"入选陆股通十大成交股，当日成交额 {float(r['amt']) / 1e8:.2f} 亿元"
                           + (f"、收盘涨 {float(chg):.2f}%" if has_chg else "（当日涨跌幅未披露）")
                           + "，为外资重点成交标的。",
                "evidence": f"陆股通成交额 {float(r['amt']) / 1e8:.2f} 亿元"
                            + (f" · 涨跌 {float(chg):+.2f}%" if has_chg else " · 涨跌幅未披露"),
                "stocks": [{"code": code, "name": name}],
            })

    dfp = _market_pulse(trade_date)
    if dfp is not None and not getattr(dfp, "empty", True):
        picks = _pulse_pick(dfp, "net_mf_yi", ascending=False, n=3,
                            where=lambda d: d["net_mf_yi"] > 0)
        if picks:
            top = picks[0]
            names = "、".join(p["name"] for p in picks[:3])
            out["opportunities"].append({
                "tag": "主力净流入",
                "cat": "capital",
                "title": f"主力资金净流入居前：{top['name']} 等 {len(picks)} 只",
                "confidence": "高确信度",
                "level": "high",
                "summary": f"全市场当日主力资金净流入排行中，{names} 位列前列。"
                           f"其中 {top['name']} 净流入 {top['net_mf_yi']} 亿元，当日收盘 {top['pct_chg']}%。"
                           f"主力资金持续净流入通常反映机构资金在主动建仓。",
                "evidence": " · ".join(f"{p['name']} {p['net_mf_yi']}亿" for p in picks[:3]),
                "stocks": picks,
            })

        picks = _pulse_pick(dfp, "amount_yi", ascending=False, n=3,
                            where=lambda d: d["pct_chg"] > 0)
        if picks:
            top = picks[0]
            out["opportunities"].append({
                "tag": "放量上涨",
                "cat": "tech",
                "title": f"放量上涨：{top['name']} 等 {len(picks)} 只",
                "confidence": "中确信度",
                "level": "mid",
                "summary": f"当日成交额居前且收涨的个股中，{top['name']} 成交 {top['amount_yi']} 亿元、"
                           f"涨幅 {top['pct_chg']}%、换手率 {top['turnover']}。"
                           f"放量上涨代表资金关注度显著提升。",
                "evidence": " · ".join(f"{p['name']} {p['amount_yi']}亿/{p['pct_chg']}" for p in picks[:3]),
                "stocks": picks,
            })

        picks = _pulse_pick(dfp, "turnover_rate", ascending=False, n=3,
                            where=lambda d: d["pct_chg"] > 0)
        if picks:
            top = picks[0]
            out["opportunities"].append({
                "tag": "高换手活跃",
                "cat": "tech",
                "title": f"高换手活跃：{top['name']} 等 {len(picks)} 只",
                "confidence": "中确信度",
                "level": "mid",
                "summary": f"{top['name']} 当日换手率 {top['turnover']}、涨幅 {top['pct_chg']}、"
                           f"成交 {top['amount_yi']} 亿元，筹码交换活跃。"
                           f"高换手既可能是资金接力，也可能是分歧加剧，需结合位置判断。",
                "evidence": " · ".join(f"{p['name']} 换手{p['turnover']}" for p in picks[:3]),
                "stocks": picks,
            })

        picks = _pulse_pick(dfp, "dv_ttm", ascending=False, n=3,
                            where=lambda d: (d["dv_ttm"] > 3) & (d["dv_ttm"] < 12) & (d["pe_ttm"] > 0))
        if picks:
            top = picks[0]
            out["opportunities"].append({
                "tag": "高股息",
                "cat": "fundamental",
                "title": f"高股息标的：{top['name']} 等 {len(picks)} 只",
                "confidence": "中确信度",
                "level": "mid",
                "summary": f"按 TTM 股息率排序，{top['name']} 股息率 {top['dv_ttm']}、PE {top['pe_ttm']}、"
                           f"PB {top['pb']}，且为盈利状态（PE 为正）。高股息通常出现在现金流稳定的成熟企业。",
                "evidence": " · ".join(f"{p['name']} 股息{p['dv_ttm']}/PE{p['pe_ttm']}" for p in picks[:3]),
                "stocks": picks,
            })

        picks = _pulse_pick(dfp, "pe_ttm", ascending=True, n=3,
                            where=lambda d: (d["pe_ttm"] > 3) & (d["pe_ttm"] < 15)
                                            & (d["pb"] > 0.3) & (d["pb"] < 1.5)
                                            & (d["total_mv"] > 500000))
        if picks:
            top = picks[0]
            out["opportunities"].append({
                "tag": "低估值",
                "cat": "fundamental",
                "title": f"低估值标的：{top['name']} 等 {len(picks)} 只",
                "confidence": "中确信度",
                "level": "mid",
                "summary": f"{top['name']} PE(TTM) {top['pe_ttm']}、PB {top['pb']}，"
                           f"在全市场盈利个股中处于低位区间。低估值不等于低估，"
                           f"需结合行业景气度与盈利质量进一步判断是否存在「价值陷阱」。",
                "evidence": " · ".join(f"{p['name']} PE{p['pe_ttm']}/PB{p['pb']}" for p in picks[:3]),
                "stocks": picks,
            })

        try:
            up_n = int((dfp["pct_chg"] > 0).sum())
            down_n = int((dfp["pct_chg"] < 0).sum())
            out["breadth"] = {
                "up": up_n, "down": down_n,
                "flat": int(len(dfp) - up_n - down_n),
                "total": int(len(dfp)),
                "up_ratio": f"{up_n / max(len(dfp), 1) * 100:.1f}%",
                "median_pct": f"{dfp['pct_chg'].median():+.2f}%",
            }
        except Exception as e:
            print(f"⚠️ [Opp] 涨跌统计异常: {e}")
    else:
        out["pulse_pending"] = True

    try:
        _lx_append_opportunities(out)
    except Exception as e:
        print(f"⚠️ [Opp] 理杏仁热度扩展失败(已跳过): {e}")

    print(f"💡 [Opp] 数据源=金融大数据, 交易日={trade_date}, 情绪={out['sentiment']}, "
          f"题材={len(out['theme_list'])}条, 机会卡={len(out['opportunities'])}张")
    return _page_cache_set(OPP_CACHE, trade_date, out)

def get_risk_data_sync():
    trade_date = _latest_trade_date_datahub()

    _hit = _page_cache_get(RISK_CACHE, trade_date)
    if _hit is not None:
        return _hit

    out = {
        "counts": {"stock": 0, "industry": 0, "policy": 0, "total": 0,
                   "capital": 0, "price": 0, "valuation": 0},
        "risks": [],
        "provider": "金融大数据", "trade_date": trade_date,
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    risks = []

    rows_top, _lhb_src = get_dragon_tiger_cached("asc", limit=100)
    if rows_top:
        if dscommon.STOCK_LIST_CACHE is None or dscommon.STOCK_LIST_CACHE.empty:
            _get_stock_list_safe()
        sell = sorted([r for r in rows_top if float(r.get("net_total_yi") or 0) < 0],
                      key=lambda r: float(r.get("net_total_yi") or 0))[:6]
        for r in sell:
            net = float(r.get("net_total_yi") or 0)
            if net >= 0:
                continue
            code = r["stock_code"]
            ex = _guess_exchange(code) or "SH"
            name = r.get("name") or _lookup_name_from_cache(code, ex) or code
            lvl = "high" if net <= -1 else "mid"
            risks.append({
                "type": "stock", "cat": "capital", "level": lvl,
                "target": f"{name} ({code})",
                "time": trade_date,
                "title": f"龙虎榜主力净卖出 {abs(net):.2f} 亿",
                "summary": f"龙虎榜累计净卖出居前，机构/游资主力净卖出 {abs(net):.2f} 亿元，"
                           f"资金出逃迹象明显（净卖出口径为金融大数据龙虎榜汇总）。",
                "ai_insight": f"该股龙虎榜主力资金净流出 {abs(net):.2f} 亿元（已发生事实）。"
                              "主力净卖出常与短线抛压相关，后续走势请结合大盘环境与个股基本面独立判断。",
            })

    df_h, _ = _fetch_hsgt_top10_datahub(trade_date)
    if df_h is not None and not df_h.empty:
        df_h = df_h.copy()
        df_h["chg"] = pd.to_numeric(df_h.get("change"), errors="coerce")
        df_h["amt"] = pd.to_numeric(df_h.get("amount"), errors="coerce")
        for _, r in df_h[df_h["chg"] < 0].sort_values("chg").head(4).iterrows():
            chg = float(r["chg"])
            code = str(r["ts_code"]).split(".")[0]
            name = str(r["name"])
            risks.append({
                "type": "stock", "cat": "capital", "level": "info" if chg > -3 else "mid",
                "target": f"{name} ({code})",
                "time": trade_date,
                "title": f"北向十大成交股当日跌 {chg:.2f}%",
                "summary": f"入选陆股通十大成交股，当日下跌 {chg:.2f}%，北向资金面承压。",
                "ai_insight": f"该股为陆股通十大成交股之一，当日下跌 {chg:.2f}%（已发生事实）。"
                              "北向活跃标的的后续表现请结合外资持仓变化与行业景气度独立判断。",
            })

    try:
        mkt = get_market_overview_datahub()
        out["counts"]["industry"] = sum(1 for k in ("sh", "sz", "cy") if not mkt[k].get("is_up", True))
    except Exception as e:
        print(f"⚠️ [Risk] 行业趋势计算异常: {e}")
        out["counts"]["industry"] = 0

    policy_n = 0
    try:
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=3)
        dfn, stn = fetch_news_datahub(
            "major_news", "all",
            start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), limit=15)
        if dfn is not None and not dfn.empty:
            for _, row in dfn.iterrows():
                text = f"{row.get('title', '')} {row.get('content', '')}"
                if analyze_sentiment_keywords(text) == "bear":
                    dt = str(row.get("datetime", ""))
                    risks.append({
                        "type": "policy", "cat": "policy", "level": "info",
                        "target": "政策/合规动态",
                        "time": dt[:16] if dt else trade_date,
                        "title": str(row.get("title", ""))[:40],
                        "summary": str(row.get("content", ""))[:120],
                        "ai_insight": "该条新闻经本地关键词判定为负面（监管收紧/业绩下滑类词汇）。"
                                      "是否影响相关行业请以官方政策原文为准。",
                    })
                    policy_n += 1
                    if policy_n >= 3:
                        break
    except Exception as e:
        print(f"⚠️ [Risk] major_news 负面读取异常: {e}")

    dfp = _market_pulse(trade_date)
    if dfp is not None and not getattr(dfp, "empty", True):
        picks = _pulse_pick(dfp, "net_mf_yi", ascending=True, n=3,
                            where=lambda d: d["net_mf_yi"] < 0)
        if picks:
            top = picks[0]
            risks.append({
                "type": "stock", "cat": "capital",
                "level": "high" if float(top["net_mf_yi"]) <= -2 else "mid",
                "target": f"{top['name']} ({top['code']})",
                "time": trade_date,
                "title": f"主力资金净流出 {top['net_mf_yi']} 亿",
                "summary": f"全市场主力资金净流出排行居前："
                           + "、".join(f"{p['name']}（{p['net_mf_yi']} 亿元）" for p in picks)
                           + "。主力持续净流出通常对应机构减仓。",
                "ai_insight": "以上为当日主力资金净流出的客观统计（已发生事实）。"
                              "资金流出≠股价必跌，请结合公司基本面与行业趋势独立判断。",
            })

        picks = _pulse_pick(dfp, "pct_chg", ascending=True, n=3,
                            where=lambda d: d["pct_chg"] < -5)
        if picks:
            top = picks[0]
            risks.append({
                "type": "stock", "cat": "price",
                "level": "high" if float(top["pct_chg"]) <= -9 else "mid",
                "target": f"{top['name']} ({top['code']})",
                "time": trade_date,
                "title": f"单日暴跌 {top['pct_chg']}%",
                "summary": f"全市场跌幅榜居前："
                           + "、".join(f"{p['name']}（{p['pct_chg']}%）" for p in picks)
                           + f"。其中 {top['name']} 当日成交 {top['amount_yi']} 亿元、换手率 {top['turnover']}。",
                "ai_insight": "以上为当日跌幅的客观统计（已发生事实）。"
                              "单日大跌不等于趋势反转，请结合公司公告与行业基本面独立判断。",
            })

        picks = _pulse_pick(dfp, "amount_yi", ascending=False, n=3,
                            where=lambda d: d["pct_chg"] < -3)
        if picks:
            top = picks[0]
            risks.append({
                "type": "stock", "cat": "price", "level": "mid",
                "target": f"{top['name']} ({top['code']})",
                "time": trade_date,
                "title": f"放量下跌：{top['name']} 跌 {top['pct_chg']}%",
                "summary": f"{top['name']} 当日下跌 {top['pct_chg']}%，成交额 {top['amount_yi']} 亿元、"
                           f"换手率 {top['turnover']}，属于「放量下跌」。"
                           f"放量下跌相对缩量下跌更能反映真实抛压。",
                "ai_insight": "该股当日呈放量下跌形态（已发生事实）。"
                              "放量下跌常伴随分歧加剧，后续走势请结合基本面独立判断。",
            })

        picks = _pulse_pick(dfp, "pe_ttm", ascending=False, n=3,
                            where=lambda d: (d["pe_ttm"] > 100) & (d["pe_ttm"] < 1000)
                                            & (d["total_mv"] > 500000))
        if picks:
            top = picks[0]
            risks.append({
                "type": "stock", "cat": "valuation", "level": "info",
                "target": f"{top['name']} ({top['code']})",
                "time": trade_date,
                "title": f"估值处于高位：PE {top['pe_ttm']}",
                "summary": f"按 PE(TTM) 排序，全市场估值最高的一批为："
                           + "、".join(f"{p['name']}（PE {p['pe_ttm']}、PB {p['pb']}）" for p in picks)
                           + "。高估值对业绩兑现的容错率更低。",
                "ai_insight": "以上为 PE(TTM) 的客观排序（已发生事实）。"
                              "高估值不等于马上回调，成长股高 PE 可能是市场对其增速的定价，请结合行业空间判断。",
            })

        try:
            no_pe = int(len(dfp) - dfp["pe_ttm"].notna().sum())
            out["counts"]["valuation"] = no_pe
            if no_pe > 0:
                risks.append({
                    "type": "market", "cat": "valuation", "level": "info",
                    "target": "全市场盈利质量",
                    "time": trade_date,
                    "title": f"全市场 {no_pe} 只个股无有效 PE(TTM)",
                    "summary": f"当前 {len(dfp)} 只股票中，有 {no_pe} 只（{no_pe / len(dfp) * 100:.1f}%）"
                               f"未返回 PE(TTM)。该指标缺失通常意味着最近 12 个月净利润为负，"
                               f"也可能是新上市或数据尚未覆盖——两者在本文中均按「无有效 PE」统计，未做区分。",
                    "ai_insight": "该数字为 PE(TTM) 缺失的个股计数（客观统计）。"
                                  "无 PE 不等同于确认亏损，如需判断具体个股请用本页的个股分析功能查看财报。",
                })
        except Exception as e:
            print(f"⚠️ [Risk] 无 PE 统计异常: {e}")

        try:
            up_n = int((dfp["pct_chg"] > 0).sum())
            down_n = int((dfp["pct_chg"] < 0).sum())
            out["breadth"] = {
                "up": up_n, "down": down_n,
                "flat": int(len(dfp) - up_n - down_n),
                "total": int(len(dfp)),
                "down_ratio": f"{down_n / max(len(dfp), 1) * 100:.1f}%",
                "limit_down": int((dfp["pct_chg"] <= -9.8).sum()),
            }
        except Exception as e:
            print(f"⚠️ [Risk] 涨跌统计异常: {e}")
    else:
        out["pulse_pending"] = True

    try:
        _lx_append_risks(out, risks, trade_date)
    except Exception as e:
        print(f"⚠️ [Risk] 理杏仁热度扩展失败(已跳过): {e}")

    out["risks"] = risks
    out["counts"]["policy"] = policy_n
    out["counts"]["stock"] = sum(1 for x in risks if x["type"] == "stock" and x["level"] == "high")
    out["counts"]["capital"] = sum(1 for x in risks if x.get("cat") == "capital")
    out["counts"]["price"] = sum(1 for x in risks if x.get("cat") == "price")
    out["counts"]["total"] = len(risks)
    print(f"🛡️ [Risk] 数据源=金融大数据, 交易日={trade_date}, 风险事件={len(risks)}条, "
          f"个股高危={out['counts']['stock']}, 资金={out['counts']['capital']}, "
          f"价格={out['counts']['price']}, 行业下行={out['counts']['industry']}, 政策={policy_n}")
    return _page_cache_set(RISK_CACHE, trade_date, out)

def _lx_pct(v):
    try:
        return f"{float(v) * 100:.1f}"
    except (TypeError, ValueError):
        return "NA"

def _lx_append_opportunities(out):
    rows = _lx_rows("mutual_netbuy", "desc", 15)
    pos = [r for r in rows if isinstance(r.get("mm_sh_nba_d20"), (int, float)) and r["mm_sh_nba_d20"] > 0][:3]
    if pos:
        stocks = [{"code": str(r["stockCode"]), "name": _lx_name(str(r["stockCode"]))} for r in pos]
        ev = " · ".join(f"{s['name']} 净买{_lx_yi([r for r in pos if str(r['stockCode'])==s['code']][0]['mm_sh_nba_d20'])}亿" for s in stocks)
        out["opportunities"].append({
            "tag": "北向加仓", "cat": "capital",
            "title": f"陆股通近20日净买入居前：{stocks[0]['name']} 等",
            "confidence": "中确信度", "level": "mid",
            "summary": "金融大数据数据显示，以下个股近 20 日获陆股通（北向）资金净买入居前，"
                       "外资连续增持通常反映中长期配置意愿与基本面认可。",
            "evidence": ev, "stocks": stocks,
        })
    rows = _lx_rows("margin_netbuy", "desc", 15)
    pos = [r for r in rows if isinstance(r.get("npa_o_f_d20"), (int, float)) and r["npa_o_f_d20"] > 0][:3]
    if pos:
        stocks = [{"code": str(r["stockCode"]), "name": _lx_name(str(r["stockCode"]))} for r in pos]
        ev = " · ".join(f"{s['name']} 净买{_lx_yi([r for r in pos if str(r['stockCode'])==s['code']][0]['npa_o_f_d20'])}亿" for s in stocks)
        out["opportunities"].append({
            "tag": "融资加仓", "cat": "capital",
            "title": f"融资余额近20日净增居前：{stocks[0]['name']} 等",
            "confidence": "中确信度", "level": "mid",
            "summary": "金融大数据两融数据显示，以下个股近 20 日融资净买入居前，"
                       "杠杆资金流入往往伴随做多情绪升温，但需警惕追高风险。",
            "evidence": ev, "stocks": stocks,
        })
    rows = _lx_rows("shareholder_down", "asc", 15)
    conv = [r for r in rows if isinstance(r.get("shnc_y1"), (int, float)) and r["shnc_y1"] < -0.05][:3]
    if conv:
        stocks = [{"code": str(r["stockCode"]), "name": _lx_name(str(r["stockCode"]))} for r in conv]
        ev = " · ".join(f"{s['name']} 户数{_lx_pct([r for r in conv if str(r['stockCode'])==s['code']][0]['shnc_y1'])}%" for s in stocks)
        out["opportunities"].append({
            "tag": "筹码集中", "cat": "capital",
            "title": f"股东户数同比降幅居前：{stocks[0]['name']} 等",
            "confidence": "中确信度", "level": "mid",
            "summary": "金融大数据股东人数数据显示，以下个股近一年股东户数明显下降，"
                       "筹码趋于集中，通常对应机构收集或关注度提升。",
            "evidence": ev, "stocks": stocks,
        })
    rows = _lx_rows("percapita_profit", "desc", 15)
    good = [r for r in rows if isinstance(r.get("stn_np_pc"), (int, float)) and r["stn_np_pc"] > 0][:3]
    if good:
        stocks = [{"code": str(r["stockCode"]), "name": _lx_name(str(r["stockCode"]))} for r in good]
        ev = " · ".join(f"{s['name']} 人均净利{_lx_yi([r for r in good if str(r['stockCode'])==s['code']][0]['stn_np_pc'])}亿" for s in stocks)
        out["opportunities"].append({
            "tag": "盈利质量", "cat": "fundamental",
            "title": f"人均净利润居前：{stocks[0]['name']} 等",
            "confidence": "中确信度", "level": "mid",
            "summary": "金融大数据人均指标显示，以下个股人均净利润居前，"
                       "反映极高的经营效率与盈利含金量，是价值投资看重的「印钞机」特征。",
            "evidence": ev, "stocks": stocks,
        })

def _lx_append_risks(out, risks, trade_date):
    rows = _lx_rows("unlock", "desc", 15)
    big = [r for r in rows if isinstance(r.get("elr_mc_y1"), (int, float)) and r["elr_mc_y1"] > 0][:3]
    if big:
        targets = "、".join(f"{_lx_name(str(r['stockCode']))}（解禁{_lx_yi(r['elr_mc_y1'])}亿）" for r in big)
        risks.append({
            "type": "stock", "cat": "price", "level": "high", "target": targets, "time": trade_date,
            "title": f"未来一年限售股解禁压力居前：{_lx_name(str(big[0]['stockCode']))} 等",
            "summary": f"金融大数据解禁数据显示，以下个股未来一年待解禁市值居前：{targets}。"
                       f"大额解禁会增加流通供给、形成潜在抛压，解禁前需关注。",
            "ai_insight": "以上为金融大数据限售解禁市值的客观排序（已发生事实）。"
                          "解禁不等于必然下跌，若公司基本面扎实、估值合理，抛压往往被承接。",
        })
    rows = _lx_rows("pledge", "desc", 15)
    high = [r for r in rows if isinstance(r.get("ps_sc_r"), (int, float)) and r["ps_sc_r"] > 0.3][:3]
    if high:
        targets = "、".join(f"{_lx_name(str(r['stockCode']))}（质押{_lx_pct(r['ps_sc_r'])}%）" for r in high)
        risks.append({
            "type": "stock", "cat": "valuation", "level": "mid", "target": targets, "time": trade_date,
            "title": f"股权质押比例居前：{_lx_name(str(high[0]['stockCode']))} 等",
            "summary": f"金融大数据质押数据显示，以下个股股权质押比例居前：{targets}。"
                       f"高质押在股价下跌时易触发平仓连锁反应，是排雷重点。",
            "ai_insight": "以上为金融大数据股权质押比例的客观排序。高质押放大了下跌时的强制平仓风险，"
                          "需结合股价距平仓线安全垫综合判断。",
        })
    rows = _lx_rows("major_change", "asc", 15)
    cut = [r for r in rows if isinstance(r.get("mssca_y1"), (int, float)) and r["mssca_y1"] < -1e7][:3]
    if cut:
        targets = "、".join(f"{_lx_name(str(r['stockCode']))}（减{_lx_yi(abs(r['mssca_y1']))}亿）" for r in cut)
        risks.append({
            "type": "stock", "cat": "capital", "level": "mid", "target": targets, "time": trade_date,
            "title": f"大股东年内减持居前：{_lx_name(str(cut[0]['stockCode']))} 等",
            "summary": f"金融大数据大股东增减持数据显示，以下个股年内大股东净减持居前：{targets}。"
                       f"重要股东减持通常释放对公司短期估值或前景的谨慎信号。",
            "ai_insight": "以上为金融大数据大股东增减持金额的客观排序。减持原因多样（个人资金安排、一级退出等），"
                          "需结合减持比例与基本面综合判断，不宜过度解读单笔。",
        })
    rows = _lx_rows("mutual_netbuy", "asc", 15)
    out_flow = [r for r in rows if isinstance(r.get("mm_sh_nba_d20"), (int, float)) and r["mm_sh_nba_d20"] < -1e7][:3]
    if out_flow:
        targets = "、".join(f"{_lx_name(str(r['stockCode']))}（净卖{_lx_yi(abs(r['mm_sh_nba_d20']))}亿）" for r in out_flow)
        risks.append({
            "type": "stock", "cat": "capital", "level": "info", "target": targets, "time": trade_date,
            "title": f"陆股通近20日净卖出居前：{_lx_name(str(out_flow[0]['stockCode']))} 等",
            "summary": f"金融大数据陆股通数据显示，以下个股近 20 日北向资金净卖出居前：{targets}。"
                       f"外资持续撤离可能反映全球配置调仓或基本面担忧。",
            "ai_insight": "以上为金融大数据陆股通净买入金额的客观排序。北向流向受多重因素影响，"
                          "短期净卖出不等于公司基本面恶化。",
        })
    rows = _lx_rows("turnover", "desc", 15)
    hot = [r for r in rows if isinstance(r.get("tr_d20"), (int, float)) and r["tr_d20"] > 1.5][:3]
    if hot:
        targets = "、".join(f"{_lx_name(str(r['stockCode']))}（换手{_lx_pct(r['tr_d20'])}%）" for r in hot)
        risks.append({
            "type": "stock", "cat": "price", "level": "info", "target": targets, "time": trade_date,
            "title": f"近20日换手率居前：{_lx_name(str(hot[0]['stockCode']))} 等",
            "summary": f"金融大数据换手率数据显示，以下个股近 20 日换手率居前：{targets}。"
                       f"异常高换手常伴随筹码快速交换与情绪极端化，波动风险上升。",
            "ai_insight": "以上为金融大数据换手率（近20日累计）的客观排序。高换手可能是题材炒作也可能是出货，"
                          "需结合价格位置与基本面甄别。",
        })

_VAL_TIER_LOW = 25.0
_VAL_TIER_HIGH = 70.0
WATCH_VAL_CACHE = {}
_WATCH_VAL_TTL = 1800
_WATCH_BATCH_LIMIT = 50

def _fmt_amount_yuan(v):
    if v is None:
        return "--"
    if v >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if v >= 1e4:
        return f"{v / 1e4:.0f}万"
    return f"{v:.0f}"

def _fmt_vol_shares(v):
    if v is None:
        return "--"
    if v >= 1e6:
        return f"{v / 1e6:.2f}万手"
    if v >= 100:
        return f"{v / 100:.0f}手"
    return f"{v:.0f}股"

def _fmt_mv_yuan(v):
    if v is None or v <= 0:
        return "--"
    if v >= 1e8:
        return f"{v / 1e8:.0f}亿"
    if v >= 1e4:
        return f"{v / 1e4:.0f}万"
    return f"{v:.0f}"

def _valuation_tier(raw):
    parts = [raw.get(k) for k in ("pe_pos5y", "pb_pos5y", "ps_pos5y")]
    if raw.get("pe_ttm") is None:
        parts = [raw.get(k) for k in ("pb_pos5y", "ps_pos5y")]
    parts = [p for p in parts if p is not None]
    if not parts:
        return None, None
    score = sum(parts) / len(parts)
    if score < _VAL_TIER_LOW:
        tier = "低估"
    elif score <= _VAL_TIER_HIGH:
        tier = "合理"
    else:
        tier = "高估"
    return tier, round(score, 1)

def _history_too_short(raw):
    vals = [raw.get(k) for k in ("pe_pos3y", "pe_pos5y", "pe_pos10y")]
    if any(v is None for v in vals):
        return False
    return abs(vals[0] - vals[1]) < 0.05 and abs(vals[1] - vals[2]) < 0.05

def _fetch_watch_valuation(tsc):
    now = time.time()
    c = WATCH_VAL_CACHE.get(tsc)
    if c is not None and (now - c.get("ts", 0) < _WATCH_VAL_TTL):
        return {**(c.get("v") or {}), "_raw": c.get("raw") or {}}
    try:
        r = lx_svc.fetch_fundamental(tsc, metrics=_WATCH_FUND_METRICS)
    except Exception as e:
        print(f"⚠️ [Watch] 估值拉取失败 {tsc}: {type(e).__name__}: {e}")
        if c:
            return {**(c.get("v") or {}), "_raw": c.get("raw") or {}}
        return {}

    def _ratio(x):
        x = _safe_float(x)
        return f"{x:.2f}" if (x is not None and x > 0) else "--"

    def _pos(x):
        x = _safe_float(x)
        return f"{x * 100:.1f}%" if x is not None else "--"

    v = {}
    raw = {}
    if r:
        pe = _safe_float(r.get("pe_ttm"))
        pb = _safe_float(r.get("pb"))
        ps = _safe_float(r.get("ps_ttm"))
        pcf = _safe_float(r.get("pcf_ttm"))
        pbwg = _safe_float(r.get("pb_wo_gw"))
        dpe = _safe_float(r.get("d_pe_ttm"))
        dyr = _safe_float(r.get("dyr"))
        mc = _safe_float(r.get("mc"))
        cmc = _safe_float(r.get("cmc"))
        ecmc = _safe_float(r.get("ecmc"))
        shn = _safe_float(r.get("shn"))

        v["pe_ttm"] = _ratio(pe)
        v["d_pe_ttm"] = _ratio(dpe)
        v["pb"] = _ratio(pb)
        v["pb_wo_gw"] = _ratio(pbwg)
        v["ps_ttm"] = _ratio(ps)
        v["pcf_ttm"] = _ratio(pcf)
        v["dyr"] = (f"{dyr * 100:.2f}%" if dyr is not None else "--")
        v["total_mv"] = _fmt_mv_yuan(mc)
        v["circ_mv"] = _fmt_mv_yuan(cmc)
        v["free_mv"] = _fmt_mv_yuan(ecmc)
        v["shn"] = (f"{int(shn):,}" if shn is not None else "--")

        v["pe_pos3y"] = _pos(r.get("pe_ttm.y3.cvpos"))
        v["pe_pos5y"] = _pos(r.get("pe_ttm.y5.cvpos"))
        v["pe_pos10y"] = _pos(r.get("pe_ttm.y10.cvpos"))
        v["pb_pos5y"] = _pos(r.get("pb.y5.cvpos"))
        v["ps_pos5y"] = _pos(r.get("ps_ttm.y5.cvpos"))
        v["dyr_pos5y"] = _pos(r.get("dyr.y5.cvpos"))

        if r.get("date"):
            v["metric_date"] = str(r["date"])[:10]

        def _pos_raw(x):
            x = _safe_float(x)
            return x * 100 if x is not None else None

        raw["pe_ttm"] = pe if (pe is not None and pe > 0) else None
        raw["d_pe_ttm"] = dpe if (dpe is not None and dpe > 0) else None
        raw["pb"] = pb if (pb is not None and pb > 0) else None
        raw["pb_wo_gw"] = pbwg if (pbwg is not None and pbwg > 0) else None
        raw["ps_ttm"] = ps if (ps is not None and ps > 0) else None
        raw["pcf_ttm"] = pcf if (pcf is not None and pcf > 0) else None
        raw["dyr"] = (dyr * 100) if dyr is not None else None
        raw["total_mv"] = (mc / 1e8) if mc is not None else None
        raw["circ_mv"] = (cmc / 1e8) if cmc is not None else None
        raw["free_mv"] = (ecmc / 1e8) if ecmc is not None else None
        raw["shn"] = int(shn) if shn is not None else None
        raw["pe_pos3y"] = _pos_raw(r.get("pe_ttm.y3.cvpos"))
        raw["pe_pos5y"] = _pos_raw(r.get("pe_ttm.y5.cvpos"))
        raw["pe_pos10y"] = _pos_raw(r.get("pe_ttm.y10.cvpos"))
        raw["pb_pos5y"] = _pos_raw(r.get("pb.y5.cvpos"))
        raw["ps_pos5y"] = _pos_raw(r.get("ps_ttm.y5.cvpos"))
        raw["dyr_pos5y"] = _pos_raw(r.get("dyr.y5.cvpos"))

        if _history_too_short(raw):
            v["val_tier"] = "数据不足"
            v["val_score"] = "--"
            v["pos_warn"] = "上市不足 3 年，历史分位参考价值有限"
            raw["val_tier"] = None
            raw["val_score"] = None
        else:
            tier, score = _valuation_tier(raw)
            v["val_tier"] = tier or "待估值"
            v["val_score"] = (f"{score:.1f}%" if score is not None else "--")
            v["pos_warn"] = ""
            raw["val_tier"] = tier
            raw["val_score"] = score

    if r:
        WATCH_VAL_CACHE[tsc] = {"v": v, "raw": raw, "ts": now}
    return {**v, "_raw": raw}

def fetch_watch_quotes_sync(ts_codes):
    result = {}
    if not ts_codes:
        return result

    ttl = _page_ttl(_WATCH_TTL_TRADING, _WATCH_TTL_CLOSED)
    now = time.time()
    todo = []
    for tsc in ts_codes:
        c = WATCH_QUOTE_CACHE.get(tsc)
        if c is not None and (now - c.get("ts", 0) < ttl):
            result[tsc] = dict(c.get("q") or {})
        else:
            todo.append(tsc)

    if not todo:
        return result

    if len(todo) > _WATCH_BATCH_LIMIT:
        print(f"⚠️ [Watch] 待刷新 {len(todo)} 只，超出单批上限 {_WATCH_BATCH_LIMIT}，本次只处理前 {_WATCH_BATCH_LIMIT} 只")
        todo = todo[:_WATCH_BATCH_LIMIT]

    def _one(tsc):
        try:
            rows = lx_svc.fetch_candlestick(tsc, days=_WATCH_KLINE_DAYS, fq_type="lxr_fc_rights")
            if not rows:
                result[tsc] = None
                return
            rows = sorted(rows, key=lambda r: str(r.get("date") or ""))
            last = rows[-1]
            prev_close = _safe_float(rows[-2].get("close")) if len(rows) >= 2 else None

            close = _safe_float(last.get("close"))
            chg = _safe_float(last.get("change"))
            amt = _safe_float(last.get("amount"))
            vol = _safe_float(last.get("volume"))
            to_r = _safe_float(last.get("to_r"))

            q = {
                "trade_date": str(last.get("date") or "")[:10],
                "close": f"{close:.2f}" if close is not None else "--",
                "pct_chg": (f"{chg * 100:+.2f}" if chg is not None else "--"),
                "is_up": (chg is not None and chg >= 0),
                "open": (f"{_safe_float(last.get('open')):.2f}" if _safe_float(last.get("open")) is not None else "--"),
                "high": (f"{_safe_float(last.get('high')):.2f}" if _safe_float(last.get("high")) is not None else "--"),
                "low": (f"{_safe_float(last.get('low')):.2f}" if _safe_float(last.get("low")) is not None else "--"),
                "pre_close": f"{prev_close:.2f}" if prev_close is not None else "--",
                "amount": _fmt_amount_yuan(amt),
                "vol": _fmt_vol_shares(vol),
                "turnover": (f"{to_r * 100:.2f}%" if to_r is not None else "--"),
            }
            val = _fetch_watch_valuation(tsc)
            val_raw = val.pop("_raw", None) or {}
            q.update(val)
            for k in ("pe_ttm", "d_pe_ttm", "pb", "pb_wo_gw", "ps_ttm", "pcf_ttm", "dyr",
                      "total_mv", "circ_mv", "free_mv", "shn",
                      "pe_pos3y", "pe_pos5y", "pe_pos10y", "pb_pos5y", "ps_pos5y", "dyr_pos5y",
                      "val_tier", "val_score"):
                q.setdefault(k, "--")
            q.setdefault("pos_warn", "")

            raw = {**val_raw, "price": close, "pct_chg": (chg * 100) if chg is not None else None}

            result[tsc] = dict(q)
            WATCH_QUOTE_CACHE[tsc] = {"q": q, "raw": raw, "ts": time.time()}
        except Exception as e:
            print(f"⚠️ [Watch] 行情拉取失败 {tsc}: {type(e).__name__}: {e}")
            result[tsc] = None

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(_one, todo))
    return result

_METRIC_META = {
    "total_mv": ("总市值", "亿"),
    "price": ("价格", "元"),
    "pct_chg": ("涨跌幅", "%"),
    "pe_ttm": ("市盈率", "倍"),
}
_OP_TXT = {"gte": "≥", "lte": "≤", "between": "介于"}
_GOAL_NEAR_PCT = 5.0

def get_watch_metric_values(ts_codes):
    out = {}
    if not ts_codes:
        return out
    todo = []
    for tsc in ts_codes:
        c = WATCH_QUOTE_CACHE.get(tsc)
        if c is not None and c.get("raw"):
            out[tsc] = c["raw"]
        else:
            todo.append(tsc)
    if todo:
        fetch_watch_quotes_sync(todo)
        for tsc in todo:
            c = WATCH_QUOTE_CACHE.get(tsc)
            out[tsc] = (c.get("raw") if c else None) or {}
    return out

def _goal_state(op, thr, thr2, cur, near_pct=_GOAL_NEAR_PCT):
    if cur is None:
        return "unknown", None
    if op == "between" and thr2 is not None:
        lo, hi = min(thr, thr2), max(thr, thr2)
        if lo <= cur <= hi:
            return "hit", 0.0
        if cur < lo:
            gap = (lo - cur) / (abs(lo) or 1) * 100
        else:
            gap = (cur - hi) / (abs(hi) or 1) * 100
        return ("near" if gap <= near_pct else "ok"), round(gap, 2)
    if op == "gte":
        if cur >= thr:
            return "hit", 0.0
        gap = (thr - cur) / (abs(thr) or 1) * 100
        return ("near" if gap <= near_pct else "ok"), round(gap, 2)
    if op == "lte":
        if cur <= thr:
            return "hit", 0.0
        gap = (cur - thr) / (abs(thr) or 1) * 100
        return ("near" if gap <= near_pct else "ok"), round(gap, 2)
    return "unknown", None

def evaluate_watch_goals(uid, ts_codes=None):
    empty = {"goals": {}, "summary": {"total": 0, "hit": 0, "near": 0}}
    try:
        alerts = db.list_alerts(uid) or []
    except Exception as e:
        print(f"⚠️ [Goals] 读取提醒规则失败: {type(e).__name__}: {e}")
        return empty
    if ts_codes is not None:
        wanted = set(ts_codes)
        alerts = [a for a in alerts if a.get("ts_code") in wanted]
    if not alerts:
        return empty

    codes = sorted({a["ts_code"] for a in alerts if a.get("ts_code")})
    vals = get_watch_metric_values(codes)

    goals = {}
    summary = {"total": 0, "hit": 0, "near": 0}
    for a in alerts:
        tsc = a.get("ts_code")
        metric = a.get("metric")
        if not tsc or metric not in _METRIC_META:
            continue
        thr = _safe_float(a.get("threshold"))
        if thr is None:
            continue
        cur = (vals.get(tsc) or {}).get(metric)
        op = a.get("operator") or "gte"
        state, gap = _goal_state(op, thr, _safe_float(a.get("threshold2")), cur)
        label, unit = _METRIC_META[metric]
        goals.setdefault(tsc, []).append({
            "id": a.get("id"),
            "metric": metric,
            "metric_label": label,
            "unit": unit,
            "operator": op,
            "op_label": _OP_TXT.get(op, op),
            "threshold": thr,
            "threshold2": _safe_float(a.get("threshold2")),
            "current": (round(cur, 4) if cur is not None else None),
            "state": state,
            "gap_pct": gap,
            "enabled": bool(a.get("enabled")),
            "triggered": bool(a.get("triggered")),
        })
        if not a.get("enabled"):
            continue
        summary["total"] += 1
        if state == "hit":
            summary["hit"] += 1
        elif state == "near":
            summary["near"] += 1
    return {"goals": goals, "summary": summary}
_FUYAO_LADDER_CACHE = {"ts": 0.0, "data": None, "empty_ts": 0.0}
_FUYAO_LADDER_TTL = 30 * 60

_FUYAO_HOT_CACHE = {"ts": 0.0, "data": None, "empty_ts": 0.0}
_FUYAO_HOT_TTL = 10 * 60

_FUYAO_POOL_CACHE = {"ts": 0.0, "data": None, "empty_ts": 0.0}
_FUYAO_POOL_TTL = 5 * 60

def _fuyao_ready():
    try:
        import settings
        import fuyao_client
    except Exception as e:
        return None, f"伏尧客户端不可用：{type(e).__name__}: {e}"
    if not settings.fuyao_enabled():
        return None, "伏尧数据源未启用或未配置 Key"
    return fuyao_client, None

def _fuyao_cached(cache, ttl, empty_ttl, fetcher, force=False, stale_grace=6 * 3600):
    now = time.time()
    if not force:
        if cache.get("data") and (now - cache.get("ts", 0)) < ttl:
            return cache["data"]
        if (not cache.get("data")) and cache.get("empty_ts") and (now - cache["empty_ts"]) < empty_ttl:
            return None
    data = fetcher()
    if data:
        cache["data"], cache["ts"] = data, now
        return data
    cache["empty_ts"] = now
    if cache.get("data") and (now - cache.get("ts", 0)) > stale_grace:
        cache["data"] = None
    return cache.get("data")

def _fetch_fuyao_limit_stats():
    fy, err = _fuyao_ready()
    if err:
        print(f"⚠️ [Market] {err}")
        return None
    out = {"provider": "金融大数据"}

    try:
        lad, lerr = fy.limit_up_ladder(timeout=8)
    except Exception as e:
        lad, lerr = None, f"{type(e).__name__}: {e}"
    if lerr:
        print(f"⚠️ [Market] 连板天梯：{lerr}")
    if lad and lad.get("days"):
        days = lad["days"]
        cur, prev = days[-1], (days[-2] if len(days) > 1 else None)
        mb = cur.get("max_board") or 0
        pmb = (prev or {}).get("max_board") or 0
        out["ladder"] = {
            "date": cur.get("date"),
            "max_board": mb,
            "prev_max_board": pmb,
            "total": cur.get("total") or 0,
            "tiers": [{"board": b, "count": n} for b, n in sorted((cur.get("tiers") or {}).items())],
            "top": cur.get("top"),
            "hist": [{"date": d.get("date"), "max_board": d.get("max_board") or 0,
                      "total": d.get("total") or 0} for d in days][-30:],
            "trend": "up" if mb > pmb else ("down" if mb < pmb else "flat"),
        }

    got = {}
    for kind in ("up", "down", "break"):
        try:
            rows, perr = fy.limit_pool(kind, timeout=8)
        except Exception as e:
            rows, perr = None, f"{type(e).__name__}: {e}"
        if perr:
            print(f"⚠️ [Market] 股票池({kind})：{perr}")
            rows = None
        got[kind] = rows or []
    if got["up"] or got["down"] or got["break"]:
        up_n, brk_n = len(got["up"]), len(got["break"])
        first = (got["up"] or got["down"] or got["break"])[0]
        out["pools"] = {
            "up": up_n, "down": len(got["down"]), "break": brk_n,
            "seal_rate": round(up_n / (up_n + brk_n) * 100, 1) if (up_n + brk_n) else None,
            "date": first.get("date"),
            "samples": [{"code": r.get("code"), "name": r.get("name"),
                         "board": r.get("limit_days"), "reason": r.get("reason")}
                        for r in sorted(got["up"], key=lambda x: -(x.get("limit_days") or 0))[:5]],
        }
    return out if (out.get("ladder") or out.get("pools")) else None

def get_market_limit_stats(force=False):
    return _fuyao_cached(_FUYAO_LADDER_CACHE, _FUYAO_LADDER_TTL, 10 * 60,
                         _fetch_fuyao_limit_stats, force)

def get_market_pools(force=False):
    return (get_market_limit_stats(force) or {}).get("pools")

def _fetch_fuyao_hot_rank():
    fy, err = _fuyao_ready()
    if err:
        print(f"⚠️ [Market] {err}")
        return None

    def _norm(rows, top=10):
        out = []
        for i, r in enumerate(rows or []):
            out.append({
                "rank": r.get("rank") or (i + 1),
                "code": r.get("code"),
                "name": r.get("name"),
                "heat": r.get("heat"),
                "change": r.get("rank_change"),
                "trend": r.get("rank_trend"),
            })
            if len(out) >= top:
                break
        return out

    try:
        hot, herr = fy.hot_stock_list(timeout=8)
    except Exception as e:
        hot, herr = None, f"{type(e).__name__}: {e}"
    if herr:
        print(f"⚠️ [Market] 人气榜：{herr}")
    try:
        sky, serr = fy.skyrocket_list(timeout=8)
    except Exception as e:
        sky, serr = None, f"{type(e).__name__}: {e}"
    if serr:
        print(f"⚠️ [Market] 飙升榜：{serr}")

    hot_n, sky_n = _norm(hot), _norm(sky)
    if not (hot_n or sky_n):
        return None
    return {"provider": "金融大数据", "hot": hot_n, "sky": sky_n,
            "as_of": datetime.datetime.now().strftime("%m-%d %H:%M")}

def get_market_hot_rank(force=False):
    return _fuyao_cached(_FUYAO_HOT_CACHE, _FUYAO_HOT_TTL, 10 * 60,
                         _fetch_fuyao_hot_rank, force)
