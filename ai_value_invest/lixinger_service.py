import time
import datetime
import threading
from lixinger import get_client, LixingerError

def _code6(ts_code):
    return str(ts_code).split('.')[0].strip()

def _sh_now():
    tz = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(tz)

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
        return f"{float(v) * 100:.{digits}f} %"
    except (TypeError, ValueError):
        return None

def _num(v, digits=2):
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return None

def _latest(items, date_key="date"):
    if not items:
        return None
    try:
        return sorted(items, key=lambda x: str(x.get(date_key, "")), reverse=True)[0]
    except Exception:
        return items[-1]

def _safe(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except LixingerError as e:
        return {"_lx_err": str(e)}
    except Exception as e:
        return {"_lx_err": f"{type(e).__name__}: {e}"}

def _get(path, **body):
    return get_client().get(path, **body)

_FUND_METRICS = [
    "pe_ttm", "d_pe_ttm", "pb", "pb_wo_gw", "ps_ttm", "pcf_ttm", "dyr",
    "ev_ebit_r", "ey", "peg",
    "sp", "spc", "to_r", "tv", "ta", "mc", "cmc", "ecmc",
    "shn", "ha_sh", "ha_shm", "mm_nba", "fb", "sb",
    "pe_ttm.y1.cvpos", "pe_ttm.y3.cvpos", "pe_ttm.y5.cvpos", "pe_ttm.y10.cvpos", "pe_ttm.fs.cvpos",
    "pb.y3.cvpos", "pb.y5.cvpos", "pb.y10.cvpos", "pb.fs.cvpos",
    "ps_ttm.y3.cvpos", "ps_ttm.y5.cvpos",
    "dyr.y5.cvpos", "dyr.fs.cvpos",
]

def fetch_fundamental(ts_code, metrics=None):
    code = _code6(ts_code)
    ms = list(metrics or _FUND_METRICS)
    now = _sh_now()
    start = (now - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    for i in range(0, len(ms), 30):
        chunk = ms[i:i + 30]
        data = _get("cn/company/fundamental/non_financial",
                    stockCodes=[code], startDate=start, endDate=end, metricsList=chunk)
        if not data:
            continue
        for row in data:
            d = str(row.get("date") or "")
            if not d:
                continue
            rec = merged.setdefault(d, {"date": d, "stockCode": code})
            rec.update(row)
    if not merged:
        return None
    row = _latest(list(merged.values()), "date")
    return row

_FS_METRICS = [
]

def flatten_row(obj, prefix=""):
    out = {}
    for k, v in (obj or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten_row(v, key + "."))
        else:
            out[key] = v
    return out

def fetch_financial_statements(ts_code, metrics=None, periods=8):
    code = _code6(ts_code)
    ms = metrics or _FS_METRICS
    now = _sh_now()
    start = (now - datetime.timedelta(days=110 * (periods // 4 + 2))).strftime("%Y-%m-%d")
    data = _get("cn/company/fs/non_financial",
                stockCodes=[code], startDate=start, metricsList=ms)
    if not data:
        return None
    try:
        data = sorted(data, key=lambda x: str(x.get("date") or ""), reverse=True)
    except Exception:
        pass
    return [flatten_row(r) for r in data[:periods]]

def fetch_shareholders_num(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    data = _get("cn/company/shareholders-num", stockCode=code, startDate=start)
    return _latest(data, "date") if data else None

def fetch_dividend(ts_code, years=5):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=365 * years)).strftime("%Y-%m-%d")
    data = _get("cn/company/dividend", stockCode=code, startDate=start)
    return data if data else None

def fetch_top_holders(ts_code, kind="majority"):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    path = ("cn/company/majority-shareholders" if kind == "majority"
            else "cn/company/nolimit-shareholders")
    data = _get(path, stockCode=code, startDate=start)
    if not data:
        return None
    if isinstance(data, dict):
        data = [data]
    latest_dt = max((str(x.get("date") or "") for x in data), default="")
    holders = [x for x in data if str(x.get("date") or "") == latest_dt]
    holders.sort(key=lambda x: (x.get("holdings") or 0), reverse=True)
    prev_dt = max((str(x.get("date") or "") for x in data
                   if str(x.get("date") or "") != latest_dt), default="")
    return {
        "date": _date_str(latest_dt),
        "declaration_date": _date_str((holders[0] if holders else {}).get("declarationDate")),
        "prev_date": _date_str(prev_dt),
        "period_count": len({str(x.get("date") or "")[:10] for x in data}),
        "holders": holders,
    }

def fetch_margin(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
    data = _get("cn/company/margin-trading-and-securities-lending", stockCode=code, startDate=start)
    return _latest(data, "date") if data else None

def fetch_revenue_constitution(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=800)).strftime("%Y-%m-%d")
    data = _get("cn/company/operation-revenue-constitution", stockCode=code, startDate=start)
    return _latest(data, "date") if data else None

def fetch_operating_data(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=800)).strftime("%Y-%m-%d")
    data = _get("cn/company/operating-data", stockCode=code, startDate=start)
    return _latest(data, "date") if data else None

def fetch_volatility(ts_code, days=120):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=days * 2)).strftime("%Y-%m-%d")
    data = _get("cn/company/volatility", stockCode=code, startDate=start, volatilityDays=days)
    return _latest(data, "date") if data else None

_PROFILE_CACHE = {"ts": 0, "data": None}
_PROFILE_LOCK = threading.Lock()

def fetch_profile(ts_code):
    code = _code6(ts_code)
    try:
        data = _get("cn/company/profile", stockCodes=[code])
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
    except LixingerError:
        pass
    with _PROFILE_LOCK:
        cache = _PROFILE_CACHE
        if cache["data"] is None or (time.time() - cache["ts"]) > 6 * 3600:
            try:
                data = _get("cn/company/profile", pageIndex=0, pageSize=100)
            except LixingerError:
                data = []
            cache["data"] = data or []
            cache["ts"] = time.time()
        if not cache["data"]:
            return None
        for it in cache["data"]:
            if str(it.get("stockCode")) == code:
                return it
    return None

def fetch_customers(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=800)).strftime("%Y-%m-%d")
    data = _get("cn/company/customers", stockCode=code, startDate=start)
    return _latest(data, "date") if data else None

def fetch_suppliers(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=800)).strftime("%Y-%m-%d")
    data = _get("cn/company/suppliers", stockCode=code, startDate=start)
    return _latest(data, "date") if data else None

def fetch_announcement(ts_code, days=365):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    data = _get("cn/company/announcement", stockCode=code, startDate=start)
    return data if data else None

def fetch_measures(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    data = _get("cn/company/measures", stockCode=code, startDate=start)
    return data if data else None

def fetch_inquiry(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    data = _get("cn/company/inquiry", stockCode=code, startDate=start)
    return data if data else None

def fetch_indices(ts_code):
    code = _code6(ts_code)
    data = _get("cn/company/indices", stockCode=code)
    return data if data else None

def fetch_industries(ts_code):
    code = _code6(ts_code)
    data = _get("cn/company/industries", stockCode=code)
    return data if data else None

def fetch_equity_change(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    data = _get("cn/company/equity-change", stockCode=code, startDate=start)
    return _latest(data, "date") if data else None

def fetch_pledge(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=800)).strftime("%Y-%m-%d")
    data = _get("cn/company/pledge", stockCode=code, startDate=start)
    return data if data else None

def fetch_fund_shareholders(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=500)).strftime("%Y-%m-%d")
    data = _get("cn/company/fund-shareholders", stockCode=code, startDate=start)
    return data if data else None

def fetch_fund_collection_shareholders(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=500)).strftime("%Y-%m-%d")
    data = _get("cn/company/fund-collection-shareholders", stockCode=code, startDate=start)
    return data if data else None

def fetch_allotment(ts_code):
    code = _code6(ts_code)
    now = _sh_now()
    start = (now - datetime.timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    data = _get("cn/company/allotment", stockCode=code, startDate=start)
    return data if data else None

_EVENT_PATHS = {
    "trading_abnormal": "cn/company/trading-abnormal",
    "block_deal": "cn/company/block-deal",
    "exec_change": "cn/company/senior-executive-shares-change",
    "major_change": "cn/company/major-shareholders-shares-change",
}

def fetch_recent_events(ts_code, kind, max_days=3):
    code = _code6(ts_code)
    path = _EVENT_PATHS.get(kind)
    if not path:
        return None
    now = _sh_now()
    days = max(1, int(max_days or 1))
    start = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        rows = _get(path, stockCode=code, startDate=start,
                    endDate=now.strftime("%Y-%m-%d"), pageIndex=0, pageSize=100)
    except LixingerError:
        rows = None
    if not rows:
        return None
    matched = [r for r in rows if str(r.get("stockCode")) == code]
    return matched or None

_CANDLE_FQ_TYPES = {"ex_rights", "lxr_fc_rights", "fc_rights", "bc_rights"}

def fetch_candlestick(ts_code, days=120, fq_type="lxr_fc_rights"):
    code = _code6(ts_code)
    if fq_type not in _CANDLE_FQ_TYPES:
        fq_type = "lxr_fc_rights"
    now = _sh_now()
    start = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    data = _get("cn/company/candlestick", stockCode=code, type=fq_type, startDate=start, endDate=end)
    return data if data else None

def lx_hot_raw(suffix, sort_name, sort_order="desc", page_size=30, page_index=0):
    try:
        data = _get(f"cn/company/hot/{suffix}",
                    sortName=sort_name, sortOrder=sort_order,
                    pageIndex=page_index, pageSize=max(1, min(int(page_size), 100)))
        return data or []
    except LixingerError as e:
        return [{"_lx_err": str(e)}]
    except Exception as e:
        return [{"_lx_err": f"{type(e).__name__}: {e}"}]

HOT_PRESETS = {
}

def lx_hot_preset(name, page_size=30):
    if name not in HOT_PRESETS:
        return []
    suffix, sort_name = HOT_PRESETS[name]
    return lx_hot_raw(suffix, sort_name, "desc", page_size)

def gather_lixinger(ts_code):
    display, overrides, raw = {}, {}, {}

    f = _safe(fetch_fundamental, ts_code)
    if f and "_lx_err" not in f:
        raw["fundamental"] = f
        if f.get("pe_ttm") is not None:
            overrides["PE(TTM)"] = _num(f["pe_ttm"])
        if f.get("d_pe_ttm") is not None:
            display["金融大数据·估值/PE-TTM(扣非)"] = _num(f["d_pe_ttm"])
        if f.get("pb") is not None:
            overrides["PB(市净率)"] = _num(f["pb"])
        if f.get("pb_wo_gw") is not None:
            display["金融大数据·估值/PB(剔除商誉)"] = _num(f["pb_wo_gw"])
        if f.get("ps_ttm") is not None:
            overrides["PS(市销率)"] = _num(f["ps_ttm"])
        if f.get("dyr") is not None:
            overrides["股息率(TTM)"] = _pct(f["dyr"])
        if f.get("ev_ebit_r") is not None:
            display["金融大数据·估值/EV-EBIT"] = _num(f["ev_ebit_r"])
        if f.get("ey") is not None:
            display["金融大数据·估值/公司收益率(EY)"] = _pct(f["ey"])
        if f.get("mc") is not None:
            overrides["总市值"] = _yi(f["mc"]) + " 亿"
        if f.get("cmc") is not None:
            overrides["流通市值"] = _yi(f["cmc"]) + " 亿"
        if f.get("ecmc") is not None:
            display["金融大数据·估值/自由流通市值(亿)"] = _yi(f["ecmc"])
        if f.get("to_r") is not None:
            display["金融大数据·估值/换手率"] = _pct(f["to_r"])
        if f.get("shn") is not None:
            display["金融大数据·估值/股东户数"] = f"{int(f['shn']):,}"
        if f.get("pe_ttm.y3.cvpos") is not None:
            display["金融大数据·估值/PE-TTM历史分位(3Y)"] = _pct(f["pe_ttm.y3.cvpos"])
        if f.get("pb.y5.cvpos") is not None:
            display["金融大数据·估值/PB历史分位(5Y)"] = _pct(f["pb.y5.cvpos"])
        if f.get("dyr.fs.cvpos") is not None:
            display["金融大数据·估值/股息率历史分位(上市)"] = _pct(f["dyr.fs.cvpos"])
        if f.get("ps_ttm.y3.cvpos") is not None:
            display["金融大数据·估值/PS-TTM历史分位(3Y)"] = _pct(f["ps_ttm.y3.cvpos"])
        if f.get("ha_sh") is not None:
            display["金融大数据·陆股通/持股数量(股)"] = f"{int(f['ha_sh']):,}"
        if f.get("ha_shm") is not None:
            display["金融大数据·陆股通/持仓市值(亿)"] = _yi(f["ha_shm"])
        if f.get("mm_nba") is not None:
            display["金融大数据·陆股通/当日净买入(亿)"] = _yi(f["mm_nba"])
        if f.get("fb") is not None:
            display["金融大数据·两融/融资余额(亿)"] = _yi(f["fb"])
        if f.get("sb") is not None:
            display["金融大数据·两融/融券余额(亿)"] = _yi(f["sb"])
        d = f.get("date")
        if d:
            display["金融大数据·估值/数据日期"] = _date_str(d)

    sn = _safe(fetch_shareholders_num, ts_code)
    if sn and "_lx_err" not in sn:
        raw["shareholders_num"] = sn
        if sn.get("num") is not None:
            display["金融大数据·股东人数/最新(户)"] = f"{int(sn['num']):,}"
        if sn.get("shareholdersNumberChangeRate") is not None:
            display["金融大数据·股东人数/环比变化"] = _pct(sn["shareholdersNumberChangeRate"])
        if sn.get("date"):
            display["金融大数据·股东人数/统计日"] = _date_str(sn["date"])

    dv = _safe(fetch_dividend, ts_code)
    if dv and "_lx_err" not in dv:
        raw["dividend"] = dv
        lines = []
        for it in dv[:5]:
            dt = _date_str(it.get("fsEndDate") or it.get("date"))
            div = it.get("dividend")
            bonus = it.get("bonusSharesFromProfit")
            cap = it.get("bonusSharesFromCapitalReserve")
            parts = [f"{dt}"]
            if div is not None:
                parts.append(f"每股派{div}元")
            if bonus:
                parts.append(f"送{bonus}股")
            if cap:
                parts.append(f"转增{cap}股")
            lines.append(" ".join(parts))
        if lines:
            display["金融大数据·分红/近5次方案"] = "；".join(lines)

    for kind, label in (("majority", "前十大股东"), ("nolimit", "前十大流通股东")):
        h = _safe(fetch_top_holders, ts_code, kind)
        if h and "_lx_err" not in h:
            raw[f"holders_{kind}"] = h
            dt = _date_str(h.get("date"))
            items = h.get("holders") or h.get("shareholders") or []
            top = []
            for s in items[:5]:
                nm = s.get("name", "")
                prop = s.get("proportionOfCapitalization")
                top.append(f"{nm}({_pct(prop) if prop is not None else 'N/A'})")
            if top:
                display[f"金融大数据·{label}/最新({dt})"] = "；".join(top)

    mg = _safe(fetch_margin, ts_code)
    if mg and "_lx_err" not in mg:
        raw["margin"] = mg
        if mg.get("financingBalance") is not None:
            display["金融大数据·两融/融资余额(亿)"] = _yi(mg["financingBalance"])
        if mg.get("financingNetPurchaseAmount") is not None:
            display["金融大数据·两融/当日融资净买入(亿)"] = _yi(mg["financingNetPurchaseAmount"])
        if mg.get("securitiesBalance") is not None:
            display["金融大数据·两融/融券余额(亿)"] = _yi(mg["securitiesBalance"])
        if mg.get("date"):
            display["金融大数据·两融/数据日期"] = _date_str(mg["date"])

    rc = _safe(fetch_revenue_constitution, ts_code)
    if rc and "_lx_err" not in rc:
        raw["revenue"] = rc
        dl = [x for x in (rc.get("dataList") or []) if x.get("parentItemName") in (None, "合计") and x.get("itemName") != "合计"]
        top = []
        for x in dl[:6]:
            nm = x.get("itemName")
            rp = x.get("revenuePercentage")
            gpm = x.get("grossProfitMargin")
            s = f"{nm}(占{rp:.1f} %" if isinstance(rp, (int, float)) else f"{nm}(占N/A"
            if isinstance(gpm, (int, float)):
                s += f",毛利率{_pct(gpm, 1)}"
            s += ")"
            top.append(s)
        if top:
            display["金融大数据·营收构成/产品(最新期)"] = "；".join(top)
        if rc.get("date"):
            display["金融大数据·营收构成/报告期"] = _date_str(rc["date"])

    od = _safe(fetch_operating_data, ts_code)
    if od and "_lx_err" not in od:
        raw["operating"] = od
        dl = [x for x in (od.get("dataList") or []) if x.get("value") is not None]
        top = [f"{x.get('itemName')}={_wan(x.get('value'))}万" for x in dl[:6]]
        if top:
            display["金融大数据·经营数据/分项(最新期)"] = "；".join(top)

    vol = _safe(fetch_volatility, ts_code)
    if vol and "_lx_err" not in vol:
        raw["volatility"] = vol
        if vol.get("value") is not None:
            display["金融大数据·波动率/最新"] = _pct(vol["value"])
        if vol.get("date"):
            display["金融大数据·波动率/数据日期"] = _date_str(vol["date"])

    pf = _safe(fetch_profile, ts_code)
    if pf and "_lx_err" not in pf:
        raw["profile"] = pf
        if pf.get("mainBusiness"):
            mb = str(pf["mainBusiness"]).strip()
            display["金融大数据·公司概况/主营业务"] = mb[:120]
        if pf.get("chairman"):
            display["金融大数据·公司概况/法人代表"] = pf["chairman"]
        if pf.get("establishDate"):
            display["金融大数据·公司概况/成立日期"] = _date_str(pf["establishDate"])
        if pf.get("registeredCapital"):
            display["金融大数据·公司概况/注册资本(元)"] = f"{int(pf['registeredCapital']):,}"

    cu = _safe(fetch_customers, ts_code)
    if cu and "_lx_err" not in cu:
        raw["customers"] = cu
        t5 = cu.get("top5Customer") or {}
        if t5.get("ratio") is not None:
            display["金融大数据·客户/前五大客户占比"] = _pct(t5["ratio"])
    su = _safe(fetch_suppliers, ts_code)
    if su and "_lx_err" not in su:
        raw["suppliers"] = su
        t5 = su.get("top5Supplier") or {}
        if t5.get("ratio") is not None:
            display["金融大数据·供应商/前五大供应商占比"] = _pct(t5["ratio"])

    ind = _safe(fetch_industries, ts_code)
    if ind and "_lx_err" not in ind:
        raw["industries"] = ind
        names = [x.get("name") for x in ind if x.get("name")]
        if names:
            display["金融大数据·所属行业"] = "、".join(names[:6])
    idx = _safe(fetch_indices, ts_code)
    if idx and "_lx_err" not in idx:
        raw["indices"] = idx
        names = [x.get("name") for x in idx if x.get("name")]
        if names:
            display["金融大数据·所属指数"] = "、".join(names[:6])

    ms = _safe(fetch_measures, ts_code)
    if ms and "_lx_err" not in ms:
        raw["measures"] = ms
        lines = [f"{_date_str(x.get('date'))} {x.get('displayTypeText','')}: {x.get('linkText','')}" for x in ms[:3]]
        if lines:
            display["金融大数据·监管措施/近期"] = "；".join(lines)
    iq = _safe(fetch_inquiry, ts_code)
    if iq and "_lx_err" not in iq:
        raw["inquiry"] = iq
        if iq:
            lines = [f"{_date_str(x.get('date'))} {x.get('linkText','')}" for x in iq[:3]]
            display["金融大数据·问询函/近期"] = "；".join(lines)
    an = _safe(fetch_announcement, ts_code)
    if an and "_lx_err" not in an:
        raw["announcement"] = an
        lines = [f"{_date_str(x.get('date'))} {x.get('linkText','')}" for x in an[:5]]
        if lines:
            display["金融大数据·公告/近期"] = "；".join(lines)

    pl = _safe(fetch_pledge, ts_code)
    if pl and "_lx_err" not in pl:
        raw["pledge"] = pl
        if isinstance(pl, list) and pl:
            latest = _latest(pl, "date")
            if latest:
                if latest.get("pledgeRatio") is not None:
                    display["金融大数据·股权质押/质押比例"] = _pct(latest["pledgeRatio"])
                if latest.get("pledgeCount") is not None:
                    display["金融大数据·股权质押/质押笔数"] = str(latest["pledgeCount"])
                if latest.get("date"):
                    display["金融大数据·股权质押/统计日"] = _date_str(latest["date"])

    eq = _safe(fetch_equity_change, ts_code)
    if eq and "_lx_err" not in eq:
        raw["equity_change"] = eq
        if eq.get("changeReason"):
            display["金融大数据·股本变动/最近原因"] = eq.get("changeReason")
        if eq.get("date"):
            display["金融大数据·股本变动/最近日期"] = _date_str(eq["date"])

    fs = _safe(fetch_fund_shareholders, ts_code)
    if fs and "_lx_err" not in fs:
        raw["fund_shareholders"] = fs
        if isinstance(fs, list) and fs:
            latest_dt = _latest(fs, "date").get("date")
            cnt = sum(1 for x in fs if str(x.get("date")) == str(latest_dt))
            display["金融大数据·基金持股/公募产品数(最新期)"] = str(cnt)
    fc = _safe(fetch_fund_collection_shareholders, ts_code)
    if fc and "_lx_err" not in fc:
        raw["fund_collection"] = fc
        if isinstance(fc, list) and fc:
            latest = _latest(fc, "date")
            if latest.get("name") and latest.get("proportionOfOutstandingSharesA") is not None:
                display["金融大数据·基金持股/主导聚合(占流通)"] = f"{latest.get('name')}({_pct(latest['proportionOfOutstandingSharesA'])})"

    al = _safe(fetch_allotment, ts_code)
    if al and "_lx_err" not in al:
        raw["allotment"] = al
        if isinstance(al, list) and al:
            display["金融大数据·配股/历史次数"] = str(len(al))

    ta = _safe(fetch_recent_events, ts_code, "trading_abnormal", 3)
    if ta and "_lx_err" not in ta:
        raw["trading_abnormal"] = ta
        lines = []
        for r in ta[:3]:
            reason = r.get("reasonForDisclosure", "")
            net = r.get("totalNetPurchaseAmount")
            lines.append(f"{_date_str(r.get('date'))} {reason} 净买入={_yi(net)}亿" if net is not None
                         else f"{_date_str(r.get('date'))} {reason}")
        if lines:
            display["金融大数据·近期异动/龙虎榜"] = "；".join(lines)
    bd = _safe(fetch_recent_events, ts_code, "block_deal", 3)
    if bd and "_lx_err" not in bd:
        raw["block_deal"] = bd
        lines = [f"{_date_str(r.get('date'))} 价{_num(r.get('tradingPrice'))} 量{_wan(r.get('tradingVolume'))}万 "
                 f"额{_yi(r.get('tradingAmount'))}亿 折价{_pct(r.get('discountRate'))}"
                 for r in bd[:3]]
        if lines:
            display["金融大数据·近期异动/大宗交易"] = "；".join(lines)
    ec = _safe(fetch_recent_events, ts_code, "exec_change", 3)
    if ec and "_lx_err" not in ec:
        raw["exec_change"] = ec
        lines = [f"{_date_str(r.get('date'))} {r.get('executiveName','')} {r.get('changeReason','')} "
                 f"变动{int(r['changedShares']) if r.get('changedShares') is not None else 'N/A'}股"
                 for r in ec[:3]]
        if lines:
            display["金融大数据·近期异动/高管增减持"] = "；".join(lines)
    mc = _safe(fetch_recent_events, ts_code, "major_change", 3)
    if mc and "_lx_err" not in mc:
        raw["major_change"] = mc
        lines = [f"{_date_str(r.get('date'))} {r.get('shareholderName','')} 变动"
                 f"{int(r['changedShares']) if r.get('changedShares') is not None else 'N/A'}股"
                 for r in mc[:3]]
        if lines:
            display["金融大数据·近期异动/大股东增减持"] = "；".join(lines)

    return {"display": display, "overrides": overrides, "raw": raw}

if __name__ == "__main__":
    import json
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "600519.SH"
    res = gather_lixinger(code)
    print(f"=== 理杏仁汇总 {code} ===")
    print("--- display ---")
    for k, v in res["display"].items():
        print(f"  {k}: {v}")
    print(f"--- overrides({len(res['overrides'])}) ---")
    for k, v in res["overrides"].items():
        print(f"  {k}: {v}")
