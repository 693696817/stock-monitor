import time
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor

from lixinger import LixingerError
import lixinger_service as lx
import website_parser
import technical_indicators
import db
from data_source import fetch_disclosure_rows
from data_service import fetch_watch_quotes_sync, _latest_trade_date_datahub

_TTL = {
    "quote": None,
    "kline": 3600,
    "profile": 7 * 86400,
    "website": 7 * 86400,
    "website_fail": 86400,
    "financials": 12 * 3600,
    "fundamental": 3600,
    "shareholders": 12 * 3600,
    "changes": 6 * 3600,
    "events": 6 * 3600,
    "pledge": 24 * 3600,
    "revenue": 24 * 3600,
    "classify": 7 * 86400,
    "announcements": 3 * 3600,
    "customers": 24 * 3600,
    "dividend": 24 * 3600,
    "heat": 3600,
    "margin": 6 * 3600,
    "mutual": 6 * 3600,
    "valuation_history": 6 * 3600,
    "disclosure": 6 * 3600,
}
_DEFAULT_TTL = 3600
_EMPTY_TTL = 900

def _ttl_seconds():
    try:
        td = _latest_trade_date_datahub()
    except Exception:
        return 900
    now = datetime.datetime.now()
    try:
        y, m, d = int(td[:4]), int(td[4:6]), int(td[6:8])
        latest = datetime.datetime(y, m, d)
    except Exception:
        return 900
    if now.date() != latest.date():
        return 900
    t = now.time()
    if (datetime.time(9, 30) <= t <= datetime.time(11, 30)) or \
       (datetime.time(13, 0) <= t <= datetime.time(15, 0)):
        return 120
    return 900

class _TTLCache:

    def __init__(self, default_ttl=60):
        self._store = {}
        self._lock = threading.Lock()
        self.default_ttl = default_ttl

    def get(self, key):
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None, False
            if time.time() - item["ts"] > item["ttl"]:
                self._store.pop(key, None)
                return None, False
            return item["val"], True

    def set(self, key, val, ttl=None):
        with self._lock:
            self._store[key] = {"val": val, "ts": time.time(), "ttl": ttl or self.default_ttl}

    def drop(self, key):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()

_MEM = _TTLCache(default_ttl=60)
_REFRESH_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sd-refresh")
_INFLIGHT = set()
_INFLIGHT_LOCK = threading.Lock()

def _is_empty_payload(val):
    if val is None:
        return True
    if isinstance(val, dict):
        if val.get("_lx_err") or val.get("_err"):
            return True
        if not val:
            return True
        return all(
            v is None or v == [] or v == {} or (isinstance(v, dict) and v.get("_lx_err"))
            for v in val.values()
        )
    if isinstance(val, (list, tuple, str)):
        return len(val) == 0
    return False

def _bg_refresh(cache_key, ttl, producer, ts_code, section):
    with _INFLIGHT_LOCK:
        if cache_key in _INFLIGHT:
            return
        _INFLIGHT.add(cache_key)

    def _job():
        try:
            val = producer()
            eff = _EMPTY_TTL if _is_empty_payload(val) else ttl
            db.set_stock_detail_cache(cache_key, val, eff, ts_code, section)
            _MEM.set(cache_key, val)
        except Exception as e:
            print(f"⚠️ [StockDetail] 后台刷新失败 {cache_key}: {e}")
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.discard(cache_key)

    try:
        _REFRESH_POOL.submit(_job)
    except Exception:
        with _INFLIGHT_LOCK:
            _INFLIGHT.discard(cache_key)

def _cached(cache_key, ttl, producer, ts_code="", section="", force=False):
    ttl = int(ttl or _DEFAULT_TTL)
    if not force:
        val, hit = _MEM.get(cache_key)
        if hit:
            return val
        try:
            rec = db.get_stock_detail_cache(cache_key)
        except Exception as e:
            print(f"⚠️ [StockDetail] 缓存读取异常 {cache_key}: {e}")
            rec = None
        if rec and rec.get("value") is not None:
            val = rec["value"]
            if rec.get("stale"):
                _bg_refresh(cache_key, ttl, producer, ts_code, section)
                _MEM.set(cache_key, val, ttl=30)
            else:
                _MEM.set(cache_key, val)
            return val
    val = producer()
    eff = _EMPTY_TTL if _is_empty_payload(val) else ttl
    try:
        db.set_stock_detail_cache(cache_key, val, eff, ts_code, section)
    except Exception as e:
        print(f"⚠️ [StockDetail] 缓存写入异常 {cache_key}: {e}")
    _MEM.set(cache_key, val)
    return val

def invalidate(ts_code=None, section=None):
    _MEM.clear()
    try:
        return db.delete_stock_detail_cache(ts_code=ts_code, section=section)
    except Exception:
        return 0

def _safe(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except LixingerError as e:
        return {"_lx_err": str(e)}
    except Exception as e:
        return {"_lx_err": f"{type(e).__name__}: {e}"}

def _ok(v):
    if not v:
        return False
    if isinstance(v, dict) and v.get("_lx_err"):
        return False
    return True

def _date_str(d):
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, datetime.datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, datetime.date):
        return d.strftime("%Y-%m-%d")
    return ""

def _yi(v):
    try:
        return f"{float(v) / 1e8:.2f}"
    except (TypeError, ValueError):
        return None

def _wan(v):
    try:
        return f"{float(v) / 1e4:.2f}"
    except (TypeError, ValueError):
        return None

def _pct(v, digits=2):
    try:
        return f"{float(v) * 100:.{digits}f}"
    except (TypeError, ValueError):
        return None

def _num(v, digits=2):
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return None

def _int(v):
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return None

def _fmt_share(n):
    try:
        n = float(n)
        if abs(n) >= 1e8:
            return f"{n/1e8:.2f}亿股"
        if abs(n) >= 1e4:
            return f"{n/1e4:.2f}万股"
        return f"{int(n):,}股"
    except Exception:
        return None

def _div(a, b):
    try:
        a, b = float(a), float(b)
        if b == 0:
            return None
        return a / b
    except (TypeError, ValueError):
        return None

def get_quote(ts_code):
    def _produce():
        q = (fetch_watch_quotes_sync([ts_code]) or {}).get(ts_code) or {}
        f = _safe(lx.fetch_fundamental, ts_code)
        if _ok(f):
            pe = f.get("pe_ttm")
            if pe is not None and pe > 0:
                q["pe_ttm"] = _num(pe)
            pb = f.get("pb")
            if pb is not None and pb > 0:
                q["pb"] = _num(pb)
            ps = f.get("ps_ttm")
            if ps is not None and ps > 0:
                q["ps_ttm"] = _num(ps)
            mc = f.get("mc")
            if mc is not None and mc > 0:
                q["total_mv"] = f"{_yi(mc)}亿"
            cmc = f.get("cmc")
            if cmc is not None and cmc > 0:
                q["circ_mv"] = f"{_yi(cmc)}亿"
            to_r = f.get("to_r")
            if to_r is not None:
                q["turnover"] = f"{_pct(to_r)}%"
            shn = f.get("shn")
            if shn is not None:
                q["shareholders"] = _int(shn)
            dyr = f.get("dyr")
            if dyr is not None:
                q["dyr"] = f"{_pct(dyr)}%"
            pos = f.get("pe_ttm.y5.cvpos")
            if pos is not None:
                q["pe_pos5y"] = f"{_pct(pos)}%"
            if f.get("date"):
                q["metric_date"] = _date_str(f["date"])
        for k in ["pe_ttm", "pb", "ps_ttm", "total_mv", "circ_mv", "turnover",
                  "shareholders", "dyr", "pe_pos5y"]:
            q.setdefault(k, "--")
        return q

    return _cached(f"quote:{ts_code}", _ttl_seconds(), _produce, ts_code, "quote")

def compute_indicators(rows):
    return technical_indicators.compute_all(rows)
_KLINE_FQ_MAP = {
    "normal": "lxr_fc_rights",
    "lxr": "lxr_fc_rights",
    "full": "lxr_fc_rights",
    "qfq": "fc_rights",
    "hfq": "bc_rights",
    "none": "ex_rights",
}
FQ_LABELS = {
    "lxr_fc_rights": "新版全复权",
    "fc_rights": "前复权",
    "bc_rights": "后复权",
    "ex_rights": "不复权",
}
FQ_HINTS = {
    "lxr_fc_rights": "以最新价为基准回溯调整，历史价含分红送股还原，适合看长期走势",
    "fc_rights": "以最新价为基准回溯调整，最新价 = 真实市价，适合看当前价位",
    "bc_rights": "以最早价为基准向前调整，最早价 = 真实历史价，适合算累计收益",
    "ex_rights": "真实成交价，未做还原，除权日会出现跳空缺口",
}

_MAX_SPAN_DAYS = 3650

PERIOD_WINDOWS = {
    "minute": [1],
    "day":    [60, 120, 240, 500],
    "week":   [365, 730, 1460, 3650],
    "month":  [730, 1460, 3650],
    "year":   [1825, 3650],
}
PERIOD_LABELS = {
    "minute": "分时", "day": "日线", "week": "周线",
    "month": "月线", "year": "年线",
}
DEFAULT_PERIOD = "day"

_KLINE_WARMUP_DAYS = 200

_PERIOD_WARMUP = {"minute": 0, "day": _KLINE_WARMUP_DAYS, "week": 1400,
                  "month": 2200, "year": 0}

def _resample(rows, period):
    if period not in ("week", "month", "year") or not rows:
        return rows

    def _key(d):
        if period == "week":
            y, w, _ = d.isocalendar()
            return (y, w)
        if period == "month":
            return (d.year, d.month)
        return (d.year,)

    buckets = []
    index = {}
    for r in rows:
        try:
            d = datetime.date.fromisoformat(str(r["date"])[:10])
        except (ValueError, TypeError):
            continue
        k = _key(d)
        if k in index:
            buckets[index[k]][1].append(r)
        else:
            index[k] = len(buckets)
            buckets.append((k, [r]))

    out = []
    prev_close = None
    for _k, grp in buckets:
        grp.sort(key=lambda x: x["date"])
        opens = [_f(x.get("open")) for x in grp]
        closes = [_f(x.get("close")) for x in grp]
        highs = [_f(x.get("high")) for x in grp]
        lows = [_f(x.get("low")) for x in grp]
        o = _firstf(opens)
        c = _firstf(closes[::-1])
        hi = _max(highs)
        lo = _min(lows)
        prev_close = c if c is not None else prev_close
        out.append({
            "date": grp[-1]["date"][:10],
            "open": _num(o), "close": _num(c), "high": _num(hi), "low": _num(lo),
            "volume": _sum(grp, "volume"),
            "amount": _sum(grp, "amount"),
            "turnover": _num(_sum(grp, "turnover"), 2),
            "change": None,
            "span_days": len(grp),
        })

    prev = None
    for r in out:
        c = _f(r.get("close"))
        if prev is not None and c is not None and prev:
            r["change"] = f"{(c / prev - 1) * 100:.2f}"
        prev = c if c is not None else prev
    return out

def _f(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None

def _firstf(seq):
    for v in seq:
        if v is not None:
            return v
    return None

def _max(seq):
    vals = [v for v in seq if v is not None]
    return max(vals) if vals else None

def _min(seq):
    vals = [v for v in seq if v is not None]
    return min(vals) if vals else None

def _sum(rows, key):
    tot = 0.0
    hit = False
    for r in rows:
        v = _f(r.get(key))
        if v is not None:
            tot += v
            hit = True
    return round(tot, 2) if hit else None

def _fetch_minute_rows(ts_code):
    from data_source import fetch_datahub
    try:
        df, st = fetch_datahub("stk_mins", {"ts_code": ts_code, "freq": "1min"}, timeout=25)
    except Exception as e:
        print(f"⚠️ [Kline] 分时取数异常 {ts_code}: {type(e).__name__}: {e}")
        return [], None
    if df is None or getattr(df, "empty", True) or "trade_time" not in df.columns:
        return [], None

    by_day = {}
    for _, r in df.iterrows():
        tt = str(r.get("trade_time") or "")
        if len(tt) < 10:
            continue
        by_day.setdefault(tt[:10], []).append(r)
    if not by_day:
        return [], None
    last_day = max(by_day)
    rows = sorted(by_day[last_day], key=lambda r: str(r.get("trade_time")))

    out = []
    for r in rows:
        out.append({
            "date": str(r.get("trade_time"))[:16],
            "open": _num(r.get("open")),
            "close": _num(r.get("close")),
            "high": _num(r.get("high")),
            "low": _num(r.get("low")),
            "volume": r.get("vol"),
            "amount": r.get("amount"),
            "change": None,
            "turnover": None,
        })
    return out, last_day

def get_kline(ts_code, fq="lxr", days=120, period="day"):
    fq = _KLINE_FQ_MAP.get(fq, fq)
    if fq not in FQ_LABELS:
        fq = "lxr_fc_rights"
    if period not in PERIOD_LABELS:
        period = DEFAULT_PERIOD
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = PERIOD_WINDOWS[period][0]
    wins = PERIOD_WINDOWS[period]
    if days not in wins:
        days = min(wins, key=lambda w: abs(w - days))

    def _produce():
        if period == "minute":
            return _produce_minute(ts_code, fq)

        warmup = _PERIOD_WARMUP.get(period, _KLINE_WARMUP_DAYS)
        raw_days = min(days + warmup, _MAX_SPAN_DAYS)
        data = _safe(lx.fetch_candlestick, ts_code, days=raw_days, fq_type=fq)
        if not _ok(data):
            data = _safe(lx.fetch_candlestick, ts_code, days=min(days, _MAX_SPAN_DAYS), fq_type=fq)
        if not _ok(data):
            return {"ok": False, "fq": fq, "fq_label": FQ_LABELS[fq],
                    "period": period, "period_label": PERIOD_LABELS[period],
                    "error": (data or {}).get("_lx_err", "无数据") if isinstance(data, dict) else "无数据",
                    "data": [], "indicators": {}}
        rows = []
        for r in data:
            dt = _date_str(r.get("date"))
            if not dt:
                continue
            rows.append({
                "date": dt,
                "open": _num(r.get("open")),
                "close": _num(r.get("close")),
                "high": _num(r.get("high")),
                "low": _num(r.get("low")),
                "volume": r.get("volume"),
                "amount": r.get("amount"),
                "change": _pct(r.get("change")),
                "turnover": _pct(r.get("to_r")),
            })
        rows.sort(key=lambda x: x["date"])
        if not rows:
            return {"ok": False, "fq": fq, "fq_label": FQ_LABELS[fq],
                    "period": period, "period_label": PERIOD_LABELS[period],
                    "error": "无数据", "data": [], "indicators": {}}

        if period in ("week", "month", "year"):
            rows = _resample(rows, period)

        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        start = 0
        for i, r in enumerate(rows):
            if r["date"] >= cutoff:
                start = i
                break
        if start >= len(rows):
            start = 0
        view = rows[start:]

        indicators = {}
        try:
            all_ind = compute_indicators(rows)
            indicators = {k: v[start:] for k, v in (all_ind or {}).items()}
        except Exception as e:
            print(f"⚠️ [Kline] 技术指标计算失败 {ts_code}: {type(e).__name__}: {e}")

        return {"ok": True, "fq": fq, "fq_label": FQ_LABELS[fq],
                "fq_hint": FQ_HINTS.get(fq, ""),
                "period": period, "period_label": PERIOD_LABELS[period],
                "count": len(view), "data": view, "indicators": indicators,
                "indicator_params": technical_indicators.PARAMS}

    return _cached(f"kline:v3:{ts_code}:{fq}:{period}:{days}", _TTL["kline"],
                   _produce, ts_code, "kline")

def _produce_minute(ts_code, fq):
    rows, last_day = _fetch_minute_rows(ts_code)
    if not rows:
        return {"ok": False, "fq": "ex_rights", "fq_label": "不复权（分时口径）",
                "fq_hint": FQ_HINTS["ex_rights"],
                "period": "minute", "period_label": PERIOD_LABELS["minute"],
                "error": "暂无分时数据（非交易时段或该标的暂不支持）",
                "data": [], "indicators": {}}

    prev_close = None
    try:
        d = _safe(lx.fetch_candlestick, ts_code, days=30, fq_type="ex_rights")
        if _ok(d):
            seq = sorted([x for x in d if x.get("date")], key=lambda x: _date_str(x.get("date")) or "")
            closes = [_f(_num(x.get("close"))) for x in seq]
            closes = [c for c in closes if c is not None]
            if len(closes) >= 2:
                prev_close = closes[-2]
    except Exception as e:
        print(f"⚠️ [Kline] 分时昨收取数失败 {ts_code}: {type(e).__name__}: {e}")

    cum_amt = 0.0
    cum_vol = 0.0
    avg = []
    for r in rows:
        a = r.get("amount")
        v = r.get("volume")
        if isinstance(a, (int, float)):
            cum_amt += a
        if isinstance(v, (int, float)):
            cum_vol += v
        avg.append(round(cum_amt / cum_vol, 3) if cum_vol else None)

    pcts = []
    for r in rows:
        c = _f(r.get("close"))
        if prev_close and c is not None:
            pcts.append(round((c / prev_close - 1) * 100, 2))
        else:
            pcts.append(None)

    return {"ok": True, "fq": "ex_rights", "fq_label": "不复权（分时口径）",
            "fq_hint": FQ_HINTS["ex_rights"],
            "period": "minute", "period_label": PERIOD_LABELS["minute"],
            "count": len(rows), "data": rows,
            "prev_close": prev_close, "avg_price": avg, "change": pcts,
            "trade_date": last_day,
            "indicators": {"vol": [r.get("volume") for r in rows]},
            "indicator_params": technical_indicators.PARAMS}

_PROFILE_FIELDS = [
    ("companyName", "公司全称", None),
    ("areaName", "所属地区", None),
    ("province", "省份", None),
    ("city", "城市", None),
    ("mainBusiness", "主营业务", None),
    ("businessScope", "经营范围", None),
    ("chairman", "董事长/法人", None),
    ("generalManager", "总经理", None),
    ("secretary", "董事会秘书", None),
    ("actualControllerName", "实际控制人", None),
    ("establishDate", "成立日期", "date"),
    ("listingDate", "上市日期", "date"),
    ("registeredCapital", "注册资本", "money"),
    ("employeeNum", "员工人数", "int"),
    ("officeAddress", "办公地址", None),
    ("registeredAddress", "注册地址", None),
    ("contactNumber", "联系电话", None),
    ("fax", "传真", None),
    ("email", "电子邮箱", None),
    ("zipCode", "邮编", None),
    ("lawFirm", "律师事务所", None),
    ("accountingFirm", "会计师事务所", None),
    ("introduction", "公司简介", None),
]

_FMT = {
    "date": lambda v: _date_str(v),
    "money": lambda v: (f"{_yi(v)} 亿元" if _yi(v) and float(v) >= 1e8 else
                        (f"{_wan(v)} 万元" if _wan(v) else None)),
    "int": lambda v: _int(v),
}

def get_website_info(url):
    if not url:
        return None
    key = f"website:{str(url).strip().lower()[:150]}"

    def _produce():
        return website_parser.parse_website(url)

    try:
        rec = db.get_stock_detail_cache(key)
    except Exception:
        rec = None
    if rec and rec.get("value") is not None and not rec.get("stale"):
        return rec["value"]
    info = _produce()
    ttl = _TTL["website"] if info.get("ok") else _TTL["website_fail"]
    try:
        db.set_stock_detail_cache(key, info, ttl, "", "website")
    except Exception:
        pass
    return info

def get_profile(ts_code, with_website=True):
    def _produce():
        pf = _safe(lx.fetch_profile, ts_code)
        ind = _safe(lx.fetch_industries, ts_code)
        idx = _safe(lx.fetch_indices, ts_code)
        pf = pf if _ok(pf) else None
        rows = []
        if pf:
            for key, label, fmt in _PROFILE_FIELDS:
                v = pf.get(key)
                if v in (None, "", []):
                    continue
                if fmt and fmt in _FMT:
                    v = _FMT[fmt](v)
                    if v is None:
                        continue
                rows.append({"label": label, "value": str(v)})
        industries = []
        if _ok(ind):
            for x in ind:
                if x.get("name"):
                    industries.append({
                        "name": x.get("name"),
                        "level": x.get("level"),
                        "source": x.get("source") or x.get("standard"),
                    })
        indices = []
        if _ok(idx):
            for x in idx:
                if x.get("name"):
                    indices.append({
                        "name": x.get("name"),
                        "code": x.get("stockCode") or x.get("indexCode"),
                        "date": _date_str(x.get("date")),
                    })
        return {
            "profile": pf,
            "profile_rows": rows,
            "website": (pf or {}).get("website"),
            "industries": industries,
            "indices": indices,
            "industry_names": [x["name"] for x in industries],
            "index_names": [x["name"] for x in indices],
        }

    res = _cached(f"profile:{ts_code}", _TTL["profile"], _produce, ts_code, "profile")
    if with_website and isinstance(res, dict) and res.get("website"):
        res = dict(res)
        res["website_info"] = get_website_info(res["website"])
    return res

_FS_LAYOUT = [
    ("资产负债表 · 流动资产", [
        ("q.bs.cabb.t", "货币资金", "yi"),
        ("q.bs.tfa.t", "交易性金融资产", "yi"),
        ("q.bs.nr.t", "应收票据", "yi"),
        ("q.bs.ar.t", "应收账款", "yi"),
        ("q.bs.or.t", "其他应收款", "yi"),
        ("q.bs.i.t", "存货", "yi"),
        ("q.bs.ca.t", "合同资产", "yi"),
        ("q.bs.oca.t", "其他流动资产", "yi"),
        ("q.bs.tca.t", "流动资产合计", "yi"),
    ]),
    ("资产负债表 · 非流动资产", [
        ("q.bs.ltei.t", "长期股权投资", "yi"),
        ("q.bs.oei.t", "其他权益工具投资", "yi"),
        ("q.bs.fa.t", "固定资产", "yi"),
        ("q.bs.cip.t", "在建工程", "yi"),
        ("q.bs.ia.t", "无形资产", "yi"),
        ("q.bs.gw.t", "商誉", "yi"),
        ("q.bs.ltpe.t", "长期待摊费用", "yi"),
        ("q.bs.dita.t", "递延所得税资产", "yi"),
        ("q.bs.tnca.t", "非流动资产合计", "yi"),
        ("q.bs.ta.t", "资产总计", "yi"),
    ]),
    ("资产负债表 · 负债", [
        ("q.bs.stl.t", "短期借款", "yi"),
        ("q.bs.np.t", "应付票据", "yi"),
        ("q.bs.ap.t", "应付账款", "yi"),
        ("q.bs.pr.t", "预收款项", "yi"),
        ("q.bs.cl.t", "合同负债", "yi"),
        ("q.bs.oap.t", "其他应付款", "yi"),
        ("q.bs.tp.t", "应交税费", "yi"),
        ("q.bs.ocl.t", "其他流动负债", "yi"),
        ("q.bs.tcl.t", "流动负债合计", "yi"),
        ("q.bs.ltl.t", "长期借款", "yi"),
        ("q.bs.bp.t", "应付债券", "yi"),
        ("q.bs.ltdi.t", "长期递延收益", "yi"),
        ("q.bs.dr.t", "递延收益", "yi"),
        ("q.bs.ditl.t", "递延所得税负债", "yi"),
        ("q.bs.tncl.t", "非流动负债合计", "yi"),
        ("q.bs.tl.t", "负债合计", "yi"),
    ]),
    ("资产负债表 · 所有者权益", [
        ("q.bs.sc.t", "股本", "share"),
        ("q.bs.tsc.t", "实收资本(股本)", "share"),
        ("q.bs.capr.t", "资本公积", "yi"),
        ("q.bs.sr.t", "盈余公积", "yi"),
        ("q.bs.toe.t", "所有者权益合计", "yi"),
    ]),
    ("利润表", [
        ("q.ps.toi.t", "营业总收入", "yi"),
        ("q.ps.oi.t", "营业收入", "yi"),
        ("q.ps.toc.t", "营业总成本", "yi"),
        ("q.ps.oc.t", "营业成本", "yi"),
        ("q.ps.tas.t", "税金及附加", "yi"),
        ("q.ps.se.t", "销售费用", "yi"),
        ("q.ps.ae.t", "管理费用", "yi"),
        ("q.ps.rade.t", "研发费用", "yi"),
        ("q.ps.fe.t", "财务费用", "yi"),
        ("q.ps.ie.t", "　其中：利息费用", "yi"),
        ("q.ps.ii.t", "投资收益", "yi"),
        ("q.ps.op.t", "营业利润", "yi"),
        ("q.ps.noi.t", "营业外收入", "yi"),
        ("q.ps.noe.t", "营业外支出", "yi"),
        ("q.ps.tp.t", "利润总额", "yi"),
        ("q.ps.ite.t", "所得税费用", "yi"),
        ("q.ps.np.t", "净利润", "yi"),
        ("q.ps.npatoshopc.t", "归属母公司净利润", "yi"),
        ("q.ps.tci.t", "综合收益总额", "yi"),
        ("q.ps.ebit.t", "EBIT", "yi"),
        ("q.ps.ebitda.t", "EBITDA", "yi"),
        ("q.ps.beps.t", "基本每股收益", "yuan"),
        ("q.ps.deps.t", "稀释每股收益", "yuan"),
        ("q.ps.gp_m.t", "毛利率", "pct"),
        ("q.ps.np_s_r.t", "净利率", "pct"),
    ]),
    ("现金流量表", [
        ("q.cfs.ncffoa.t", "经营活动现金流净额", "yi"),
        ("q.cfs.ncffia.t", "投资活动现金流净额", "yi"),
        ("q.cfs.ncfffa.t", "筹资活动现金流净额", "yi"),
    ]),
    ("核心财务指标", [
        ("q.m.roe.t", "ROE（净资产收益率）", "pct"),
        ("q.m.roa.t", "ROA（总资产收益率）", "pct"),
        ("q.m.roic.t", "ROIC（投入资本回报率）", "pct"),
        ("q.m.gp_m.t", "毛利率（指标口径）", "pct"),
    ]),
]

_REPORT_TYPE_CN = {
    "annual_report": "年报",
    "interim_report": "中报",
    "first_quarterly_report": "一季报",
    "third_quarterly_report": "三季报",
}

def _fs_fmt(v, unit):
    if v is None:
        return None
    if unit == "yi":
        return _yi(v)
    if unit == "pct":
        return _pct(v)
    if unit == "yuan":
        return _num(v, 3)
    if unit == "share":
        return _fmt_share(v)
    return _num(v)

_UNIT_CN = {"yi": "亿元", "pct": "%", "yuan": "元", "share": "股"}

def _derived_rows(rows):
    specs = [
        ("资产负债率", lambda r: _div(r.get("q.bs.tl.t"), r.get("q.bs.ta.t")), "pct"),
        ("有息负债合计", lambda r: (
            (r.get("q.bs.stl.t") or 0) + (r.get("q.bs.ltl.t") or 0) + (r.get("q.bs.bp.t") or 0)
        ), "yi"),
        ("有息负债/总资产", lambda r: _div(
            (r.get("q.bs.stl.t") or 0) + (r.get("q.bs.ltl.t") or 0) + (r.get("q.bs.bp.t") or 0),
            r.get("q.bs.ta.t")), "pct"),
        ("货币资金/有息负债", lambda r: _div(
            r.get("q.bs.cabb.t"),
            (r.get("q.bs.stl.t") or 0) + (r.get("q.bs.ltl.t") or 0) + (r.get("q.bs.bp.t") or 0)
        ), "x"),
        ("商誉/净资产", lambda r: _div(r.get("q.bs.gw.t"), r.get("q.bs.toe.t")), "pct"),
        ("存货/总资产", lambda r: _div(r.get("q.bs.i.t"), r.get("q.bs.ta.t")), "pct"),
        ("应收账款/营业总收入", lambda r: _div(r.get("q.bs.ar.t"), r.get("q.ps.toi.t")), "pct"),
        ("流动比率", lambda r: _div(r.get("q.bs.tca.t"), r.get("q.bs.tcl.t")), "x"),
        ("经营现金流/净利润", lambda r: _div(r.get("q.cfs.ncffoa.t"), r.get("q.ps.np.t")), "x"),
        ("研发费用率", lambda r: _div(r.get("q.ps.rade.t"), r.get("q.ps.toi.t")), "pct"),
        ("销售费用率", lambda r: _div(r.get("q.ps.se.t"), r.get("q.ps.toi.t")), "pct"),
        ("管理费用率", lambda r: _div(r.get("q.ps.ae.t"), r.get("q.ps.toi.t")), "pct"),
    ]
    out = []
    for label, fn, unit in specs:
        vals = []
        for r in rows:
            try:
                v = fn(r)
            except Exception:
                v = None
            if unit == "pct":
                vals.append(_pct(v))
            elif unit == "yi":
                vals.append(_yi(v))
            elif unit == "x":
                vals.append(_num(v))
            else:
                vals.append(_num(v))
        if any(v is not None for v in vals):
            out.append({"label": label, "unit": {"pct": "%", "yi": "亿元", "x": "倍"}.get(unit, ""),
                        "values": vals})
    return out

def build_financial_matrix(rows):
    if not rows:
        return None
    periods = []
    for r in rows:
        d = _date_str(r.get("date"))
        periods.append({
            "date": d,
            "label": d[:7] if d else "",
            "report_type": _REPORT_TYPE_CN.get(r.get("reportType"), r.get("reportType") or ""),
            "report_date": _date_str(r.get("reportDate")),
        })
    groups = []
    for title, fields in _FS_LAYOUT:
        g_rows = []
        for key, label, unit in fields:
            vals = [_fs_fmt(r.get(key), unit) for r in rows]
            if all(v is None for v in vals):
                continue
            g_rows.append({"label": label, "key": key,
                           "unit": _UNIT_CN.get(unit, ""), "values": vals})
        if g_rows:
            groups.append({"title": title, "rows": g_rows})
    dr = _derived_rows(rows)
    if dr:
        groups.append({"title": "派生指标（本站测算）", "rows": dr, "derived": True})
    return {
        "periods": periods,
        "currency": rows[0].get("currency") or "CNY",
        "groups": groups,
        "field_count": sum(len(g["rows"]) for g in groups),
    }

_FUND_LAYOUT = [
    ("估值指标", [
        ("pe_ttm", "PE（TTM）", "num"),
        ("d_pe_ttm", "PE（TTM，扣非）", "num"),
        ("pb", "PB（市净率）", "num"),
        ("pb_wo_gw", "PB（剔除商誉）", "num"),
        ("ps_ttm", "PS（TTM）", "num"),
        ("pcf_ttm", "PCF（TTM）", "num"),
        ("peg", "PEG", "num"),
        ("dyr", "股息率（TTM）", "pct"),
        ("ev_ebit_r", "EV/EBIT", "num"),
        ("ey", "公司收益率 EY", "pct"),
    ]),
    ("规模与成交", [
        ("mc", "总市值", "yi"),
        ("cmc", "流通市值", "yi"),
        ("ecmc", "自由流通市值", "yi"),
        ("sp", "收盘价", "num"),
        ("spc", "涨跌幅", "pct_signed"),
        ("to_r", "换手率", "pct"),
        ("tv", "成交量", "share"),
        ("ta", "成交额", "yi"),
    ]),
    ("股东与资金", [
        ("shn", "股东户数", "int"),
        ("ha_sh", "陆股通持股数", "share"),
        ("ha_shm", "陆股通持仓市值", "yi"),
        ("mm_nba", "陆股通当日净买入", "yi_signed"),
        ("fb", "融资余额", "yi"),
        ("sb", "融券余额", "yi"),
    ]),
    ("历史估值分位（当前值处于历史百分位）", [
        ("pe_ttm.y1.cvpos", "PE 近 1 年分位", "pct"),
        ("pe_ttm.y3.cvpos", "PE 近 3 年分位", "pct"),
        ("pe_ttm.y5.cvpos", "PE 近 5 年分位", "pct"),
        ("pe_ttm.y10.cvpos", "PE 近 10 年分位", "pct"),
        ("pe_ttm.fs.cvpos", "PE 上市以来分位", "pct"),
        ("pb.y3.cvpos", "PB 近 3 年分位", "pct"),
        ("pb.y5.cvpos", "PB 近 5 年分位", "pct"),
        ("pb.y10.cvpos", "PB 近 10 年分位", "pct"),
        ("pb.fs.cvpos", "PB 上市以来分位", "pct"),
        ("ps_ttm.y3.cvpos", "PS 近 3 年分位", "pct"),
        ("ps_ttm.y5.cvpos", "PS 近 5 年分位", "pct"),
        ("dyr.y5.cvpos", "股息率近 5 年分位", "pct"),
        ("dyr.fs.cvpos", "股息率上市以来分位", "pct"),
    ]),
]

def _fund_fmt(v, kind):
    if v is None:
        return None
    if kind == "pct":
        s = _pct(v)
        return f"{s} %" if s else None
    if kind == "pct_signed":
        s = _pct(v)
        if s is None:
            return None
        return f"+{s} %" if float(v) > 0 else f"{s} %"
    if kind == "yi":
        s = _yi(v)
        return f"{s} 亿" if s else None
    if kind == "yi_signed":
        s = _yi(v)
        if s is None:
            return None
        return f"+{s} 亿" if float(v) > 0 else f"{s} 亿"
    if kind == "int":
        return _int(v)
    if kind == "share":
        return _fmt_share(v)
    return _num(v)

def build_fundamental_groups(f):
    if not f:
        return None
    groups = []
    for title, fields in _FUND_LAYOUT:
        rows = []
        for key, label, kind in fields:
            v = _fund_fmt(f.get(key), kind)
            if v is None:
                continue
            rows.append({"label": label, "value": v, "key": key,
                         "raw": f.get(key)})
        if rows:
            groups.append({"title": title, "rows": rows})
    return {"date": _date_str(f.get("date")), "groups": groups,
            "field_count": sum(len(g["rows"]) for g in groups)}

_SECTION_FETCHERS = {}

def _section(name):
    def deco(fn):
        _SECTION_FETCHERS[name] = fn
        return fn
    return deco

@_section("fundamental")
def _fetch_fundamental_full(ts_code):
    f = _safe(lx.fetch_fundamental, ts_code)
    f = f if _ok(f) else None
    return {"fundamental": f, "groups": build_fundamental_groups(f)}

@_section("financials")
def _fetch_financials(ts_code):
    fs = _safe(lx.fetch_financial_statements, ts_code, periods=8)
    fs = fs if _ok(fs) else None
    return {
        "financials": fs,
        "matrix": build_financial_matrix(fs),
        "metric_count": len(lx._FS_METRICS),
    }

@_section("shareholders")
def _fetch_shareholders(ts_code):
    sn = _safe(lx.fetch_shareholders_num, ts_code)
    maj = _safe(lx.fetch_top_holders, ts_code, "majority")
    nol = _safe(lx.fetch_top_holders, ts_code, "nolimit")
    fund = _safe(lx.fetch_fund_shareholders, ts_code)
    fcoll = _safe(lx.fetch_fund_collection_shareholders, ts_code)
    fund_latest = None
    if _ok(fund) and isinstance(fund, list):
        latest_dt = max((str(x.get("date") or "") for x in fund), default="")
        items = [x for x in fund if str(x.get("date") or "") == latest_dt]
        items.sort(key=lambda x: (x.get("proportionOfOutstandingSharesA") or 0), reverse=True)
        fund_latest = {"date": _date_str(latest_dt), "count": len(items), "items": items[:20]}
    return {
        "shareholders_num": sn if _ok(sn) else None,
        "majority": maj if _ok(maj) else None,
        "nolimit": nol if _ok(nol) else None,
        "fund_products": fund_latest,
        "fund_collections": fcoll if _ok(fcoll) else None,
    }

@_section("changes")
def _fetch_changes(ts_code):
    ec = _safe(lx.fetch_recent_events, ts_code, "exec_change", 365)
    mc = _safe(lx.fetch_recent_events, ts_code, "major_change", 365)
    return {
        "executive": ec if _ok(ec) else None,
        "major": mc if _ok(mc) else None,
    }

@_section("events")
def _fetch_events(ts_code):
    ta = _safe(lx.fetch_recent_events, ts_code, "trading_abnormal", 30)
    bd = _safe(lx.fetch_recent_events, ts_code, "block_deal", 30)
    return {
        "trading_abnormal": ta if _ok(ta) else None,
        "block_deal": bd if _ok(bd) else None,
    }

@_section("pledge")
def _fetch_pledge(ts_code):
    pl = _safe(lx.fetch_pledge, ts_code)
    return {"pledge": pl if _ok(pl) else None}

@_section("revenue")
def _fetch_revenue(ts_code):
    rc = _safe(lx.fetch_revenue_constitution, ts_code)
    od = _safe(lx.fetch_operating_data, ts_code)
    return {
        "revenue_constitution": rc if _ok(rc) else None,
        "operating_data": od if _ok(od) else None,
    }

@_section("classify")
def _fetch_classify(ts_code):
    return get_profile(ts_code, with_website=False)

@_section("announcements")
def _fetch_announcements(ts_code):
    an = _safe(lx.fetch_announcement, ts_code, days=365)
    ms = _safe(lx.fetch_measures, ts_code)
    iq = _safe(lx.fetch_inquiry, ts_code)
    return {
        "announcement": an if _ok(an) else None,
        "measures": ms if _ok(ms) else None,
        "inquiry": iq if _ok(iq) else None,
    }

@_section("customers")
def _fetch_customers(ts_code):
    cu = _safe(lx.fetch_customers, ts_code)
    su = _safe(lx.fetch_suppliers, ts_code)
    return {
        "customers": cu if _ok(cu) else None,
        "suppliers": su if _ok(su) else None,
    }

@_section("dividend")
def _fetch_dividend(ts_code):
    dv = _safe(lx.fetch_dividend, ts_code, years=10)
    al = _safe(lx.fetch_allotment, ts_code)
    eq = _safe(lx.fetch_equity_change, ts_code)
    pl = _safe(lx.fetch_pledge, ts_code)
    return {
        "dividend": dv if _ok(dv) else None,
        "allotment": al if _ok(al) else None,
        "equity_change": eq if _ok(eq) else None,
        "pledge": pl if _ok(pl) else None,
    }

@_section("heat")
def _fetch_heat(ts_code):
    fund = _safe(lx.fetch_fundamental, ts_code)
    heat = {}
    if isinstance(fund, dict) and "_lx_err" not in fund:
        for k in ("to_r", "tv", "ta", "mc", "cmc", "ecmc"):
            v = fund.get(k)
            if v is not None:
                heat[k] = v
    vol = _safe(lx.fetch_volatility, ts_code)
    mg = _safe(lx.fetch_margin, ts_code)
    code6 = lx._code6(ts_code)
    now = lx._sh_now()
    start = (now - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
    mutual = _safe(lx._get, "cn/company/mutual-market", stockCode=code6, startDate=start)
    return {
        "heat": heat or None,
        "volatility": vol if _ok(vol) else None,
        "margin": mg if _ok(mg) else None,
        "mutual": mutual if _ok(mutual) else None,
    }

@_section("margin")
def _fetch_margin(ts_code):
    mg = _safe(lx.fetch_margin, ts_code)
    return {"margin": mg if _ok(mg) else None}

@_section("mutual")
def _fetch_mutual(ts_code):
    code6 = lx._code6(ts_code)
    now = lx._sh_now()
    start = (now - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
    data = _safe(lx._get, "cn/company/mutual-market", stockCode=code6, startDate=start)
    return {"mutual": data if _ok(data) else None}

_VAL_SNAPSHOT_METRICS = [
    "pe_ttm", "pb", "ps_ttm", "dyr",
    "pe_ttm.y3.cvpos", "pe_ttm.y5.cvpos", "pe_ttm.y10.cvpos", "pe_ttm.fs.cvpos",
    "pb.y3.cvpos", "pb.y5.cvpos", "pb.y10.cvpos", "pb.fs.cvpos",
    "ps_ttm.y3.cvpos", "ps_ttm.y5.cvpos",
    "dyr.y5.cvpos", "dyr.fs.cvpos",
]

@_section("valuation_history")
def _fetch_valuation_history(ts_code):
    code6 = lx._code6(ts_code)
    now = lx._sh_now()
    start = (now - datetime.timedelta(days=365 * 5 + 10)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    hist = _safe(lx._get, "cn/company/fundamental/non_financial",
                 stockCodes=[code6], startDate=start, endDate=end,
                 metricsList=["pe_ttm", "pb", "ps_ttm", "dyr"])
    rows = hist if _ok(hist) else None
    series = []
    if rows:
        def _f(v):
            try:
                return round(float(v), 4)
            except (TypeError, ValueError):
                return None
        rows = sorted(rows, key=lambda r: str(r.get("date") or ""))
        n = len(rows)
        daily_from = max(0, n - 120)
        keep = set(range(daily_from, n)) | set(range(0, daily_from, 5))
        for i, r in enumerate(rows):
            if i not in keep:
                continue
            d = str(r.get("date") or "")[:10]
            if not d:
                continue
            series.append({"date": d, "pe": _f(r.get("pe_ttm")), "pb": _f(r.get("pb")),
                           "ps": _f(r.get("ps_ttm")), "dyr": _f(r.get("dyr"))})

    snap = _safe(lx.fetch_fundamental, ts_code, metrics=_VAL_SNAPSHOT_METRICS)
    snap = snap if _ok(snap) else None

    def _pos100(key):
        v = (snap or {}).get(key)
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if 0.0 <= f <= 1.0:
            return round(f * 100, 1)
        return round(f, 1) if 0.0 < f <= 100.0 else None

    cvpos = {
        "pe_y3": _pos100("pe_ttm.y3.cvpos"), "pe_y5": _pos100("pe_ttm.y5.cvpos"),
        "pe_y10": _pos100("pe_ttm.y10.cvpos"), "pe_fs": _pos100("pe_ttm.fs.cvpos"),
        "pb_y3": _pos100("pb.y3.cvpos"), "pb_y5": _pos100("pb.y5.cvpos"),
        "pb_y10": _pos100("pb.y10.cvpos"), "pb_fs": _pos100("pb.fs.cvpos"),
        "ps_y3": _pos100("ps_ttm.y3.cvpos"), "ps_y5": _pos100("ps_ttm.y5.cvpos"),
        "dyr_y5": _pos100("dyr.y5.cvpos"), "dyr_fs": _pos100("dyr.fs.cvpos"),
    }
    if not any(v is not None for v in cvpos.values()):
        cvpos = None
    snap_date = str((snap or {}).get("date") or "")[:10] or None
    return {
        "series": series or None,
        "points": len(series),
        "cvpos": cvpos,
        "snapshot_date": snap_date,
    }

@_section("disclosure")
def _fetch_disclosure(ts_code):
    rows = fetch_disclosure_rows(ts_code=ts_code, limit=200)
    if not rows:
        return {"next": None, "history": None}
    pend = [r for r in rows if r.get("pre_date") and not r.get("actual_date")]
    nxt = min(pend, key=lambda r: r["pre_date"]) if pend else None
    hist = sorted(rows, key=lambda r: r.get("end_date") or "", reverse=True)[:4]
    return {
        "next": nxt,
        "history": hist if hist else None,
    }

def get_section(ts_code, section, force=False):
    fetcher = _SECTION_FETCHERS.get(section)
    if not fetcher:
        return {"_err": f"未知板块: {section}"}
    ttl = _TTL.get(section, _DEFAULT_TTL)
    return _cached(f"section:{ts_code}:{section}", ttl,
                   lambda: fetcher(ts_code), ts_code, section, force=force)

def list_sections():
    return list(_SECTION_FETCHERS.keys())

def cache_stats():
    try:
        return db.stock_detail_cache_stats()
    except Exception:
        return {}
