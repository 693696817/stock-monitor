
import datetime
import os
import time

import akshare as ak
import pandas as pd

import db
import lixinger_service as lx_svc
from data_source import fetch_datahub, get_pro, get_pro_bar

pro = get_pro()
pro_bar = get_pro_bar()

STOCK_LIST_CACHE = None

def _guess_exchange(code6: str):
    if not (len(code6) == 6 and code6.isdigit()):
        return None
    head = code6[0]
    if head in ("6", "9"):
        return "SH"
    if head in ("0", "3"):
        return "SZ"
    if head in ("8", "4"):
        return "BJ"
    return None

def _lookup_name_from_cache(code6: str, ex: str):
    global STOCK_LIST_CACHE
    if STOCK_LIST_CACHE is None or STOCK_LIST_CACHE.empty:
        return None
    try:
        target = f"{code6}.{ex}"
        m = STOCK_LIST_CACHE[STOCK_LIST_CACHE["ts_code"] == target]
        if not m.empty:
            return m.iloc[0].get("name")
    except Exception:
        pass
    return None

def _fetch_safe(func, label="api", **kwargs):
    try:
        return func(**kwargs)
    except Exception as e:
        print(f"[data] {label} 获取失败: {e}")
        return None

API_PAGE_SIZE = 5000
API_MAX_PAGES = 8

def _fetch_all_pages(func, label="api", page_size=API_PAGE_SIZE,
                     max_pages=API_MAX_PAGES, **kwargs):
    frames, offset = [], 0
    for _ in range(max_pages):
        df = _fetch_safe(func, label, limit=page_size, offset=offset, **kwargs)
        if df is None or getattr(df, "empty", True):
            break
        frames.append(df)
        if len(df) < page_size:
            break
        offset += page_size
    if not frames:
        return None
    if len(frames) == 1:
        return frames[0]
    try:
        return pd.concat(frames, ignore_index=True)
    except Exception:
        return frames[0]

def _to_number(val):
    import math
    if val is None:
        return None
    if isinstance(val, str) and len(val.strip()) == 8 and val.strip().isdigit():
        return None
    try:
        num = float(str(val).strip()) if isinstance(val, str) else float(val)
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    except (ValueError, TypeError):
        return None

def safe_get(row, key, default="N/A", multiplier=1, unit=""):
    try:
        val = row.get(key)
        if _is_blank(val):
            return default
        num = _to_number(val)
        if num is not None:
            result = num * multiplier
            return f"{result:.2f} {unit}" if unit else round(result, 4)
        return str(val).strip()
    except Exception:
        return default

def safe_get_multi(row, keys, default="N/A", multiplier=1, unit=""):
    try:
        for k in keys:
            v = row.get(k)
            if _is_blank(v):
                continue
            return safe_get(row, k, default=default, multiplier=multiplier, unit=unit)
    except Exception:
        pass
    return default

def _ak_symbol(ts_code):
    try:
        code6, ex = ts_code.split('.')
        return code6, ex
    except Exception:
        return ts_code.split('.')[0], 'SH'

def _yi(v):
    n = _to_number(v)
    return None if n is None else n / 1e8

def _is_num(v):
    if v is None or v == "":
        return False
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        try:
            return not pd.isna(v)
        except Exception:
            return True
    try:
        float(str(v).strip())
        return True
    except (ValueError, TypeError):
        return False

DATA_GROUPS = {
    "quote": {
        "title": "行情速览",
        "fields": ["当前价格", "今日涨跌幅", "总市值", "流通市值", "换手率", "成交额", "MA5", "MA20", "趋势信号"],
    },
    "technical": {
        "title": "技术指标（MACD / KDJ / RSI / BOLL / CCI / WR / ATR / DMI 等）",
        "fields": ["技术指标日期", "MACD-DIF", "MACD-DEA", "MACD-柱", "KDJ-K", "KDJ-D", "KDJ-J",
                   "RSI6", "RSI12", "RSI24", "BOLL上轨", "BOLL中轨", "BOLL下轨", "CCI",
                   "WR(威廉)", "BIAS(乖离率)", "ATR(真实波幅)", "PSY(心理线)", "ROC(变动率)",
                   "DMI-ADX", "MTM(动量)", "OBV(能量潮)"],
        "task": "task_technical",
    },
    "moneyflow": {
        "title": "资金流向（近 5 日，单位已换算为亿元）",
        "fields": ["资金流日期", "主力净流入", "主力资金方向", "特大单买入额", "特大单卖出额",
                   "大单买入额", "大单卖出额", "中单买入额", "中单卖出额",
                   "小单买入额", "小单卖出额", "近5日主力净额"],
        "task": "task_moneyflow",
    },
    "valuation": {
        "title": "估值指标",
        "fields": ["PE(静态)", "PE(TTM)", "PB(市净率)", "PS(市销率)", "股息率(TTM)", "股息率(静态)",
                   "PE(TTM)历史百分位", "PB历史百分位", "每股现金分红(最新)", "分红报告期"],
    },
    "profitability": {
        "title": "盈利与杜邦",
        "fields": ["财报报告期", "ROE(加权)", "ROIC", "销售毛利率", "销售净利率", "资产负债率"],
    },
    "growth": {
        "title": "成长与业绩",
        "fields": ["利润表报告期", "营业总收入", "营收同比增速", "归母净利润", "净利同比增速",
                   "扣非净利润", "研发费用"],
    },
    "cashflow": {
        "title": "现金流",
        "fields": ["现金流报告期", "经营活动现金流净额", "估算自由现金流(FCF)", "每股经营现金流"],
    },
    "multiyear": {
        "title": "多年财务趋势（近 5 期年报）",
        "fields": ["近年年报财务趋势", "ROE趋势"],
        "task": "task_multiyear",
    },
    "dividend": {
        "title": "分红历史",
        "fields": ["近年分红方案", "近年累计分红次数"],
        "task": "task_dividend_hist",
    },
    "business": {
        "title": "主营业务构成",
        "fields": [],
        "task": "task_main_business",
        "dynamic_prefix": "主营构成",
    },
    "holders": {
        "title": "股东结构",
        "fields": [],
        "task": "task_holders",
        "dynamic_keys": ["股东户数变化", "前五大股东"],
    },
    "balance": {
        "title": "资产负债表与排雷（亿元）",
        "fields": ["资产负债表报告期", "总资产", "总负债", "归母净资产", "货币资金",
                   "有息负债合计", "有息负债率", "净现金(货币资金-有息负债)",
                   "存货", "应收账款", "其他应收款", "合同负债(预收款)", "无形资产",
                   "商誉", "商誉占总资产", "商誉占净资产",
                   "资产负债率(表算)", "存贷双高预警",
                   "应收占营收比", "应收+存货占营收比"],
        "task": "task_balance",
    },
    "risk": {
        "title": "风险排雷（审计 / 质押 / 解禁）",
        "fields": ["审计报告期", "最近审计意见", "审计机构", "审计费用", "审计意见预警",
                   "质押统计日期", "股权质押比例", "质押笔数", "股权质押预警",
                   "未来解禁次数", "未来解禁计划", "解禁预警"],
        "task": "task_risk",
    },
    "forward": {
        "title": "前瞻业绩（业绩预告 / 快报）",
        "fields": ["业绩预告报告期", "业绩预告类型", "预告净利润变动", "预告净利润",
                   "上年同期净利润", "预告摘要",
                   "业绩快报报告期", "快报营业收入", "快报净利润",
                   "快报上年同期净利润", "快报净利同比", "快报摊薄ROE"],
        "task": "task_forward",
    },
    "capital": {
        "title": "资金结构（北向 / 两融 / 流通股东 / 大宗）",
        "fields": ["北向数据日期", "北向持股比例", "北向持股数量", "北向持股变化(区间)",
                   "两融数据日期", "融资余额", "融券余额", "近期大宗交易"],
        "task": "task_capital",
        "dynamic_keys": ["前五大流通股东"],
    },
    "mgmt": {
        "title": "管理层信号（回购 / 董监高持股）",
        "fields": ["已实施回购次数", "累计回购金额", "累计回购股数", "最近回购日期",
                   "回购情况", "董监高持股合计"],
        "task": "task_mgmt",
        "dynamic_keys": ["董监高持股"],
    },
    "operations": {
        "title": "运营效率（周转率 / 每股指标）",
        "fields": ["总资产周转率", "应收账款周转率", "存货周转率",
                   "每股收益(EPS)", "每股净资产(BPS)"],
    },
    "peer": {
        "title": "同业对比（行业 + 全市场估值锚）",
        "fields": ["对比交易日", "所属行业", "行业样本数", "行业对比",
                   "当前PE", "行业PE分位", "行业PE中位数", "PE相对行业中位数",
                   "当前PB", "行业PB分位", "行业PB中位数", "PB相对行业中位数",
                   "全市场PE分位", "全市场PE中位数", "PE相对全市场中位数",
                   "全市场PB分位", "全市场PB中位数", "PB相对全市场中位数"],
        "task": "task_peer_compare",
    },
    "announcement": {
        "title": "近期公告与披露（权威口径）",
        "fields": ["公告数据日期", "近一年公告条数", "近期公告"],
        "task": "task_announcement",
    },
    "hotrank": {
        "title": "市场热度与拥挤度（人气榜排名）",
        "fields": ["人气榜排名(最新)", "人气榜排名日期", "近14日最佳排名",
                   "近14日排名变化(正数=降温)", "人气榜Top30在榜", "人气热度值"],
        "task": "task_hotrank",
    },
    "dragon": {
        "title": "龙虎榜（次主力资金博弈）",
        "fields": ["近期是否上榜", "龙虎榜上榜日期", "龙虎榜当日涨跌幅", "龙虎榜净买入(亿)",
                   "龙虎榜买入额(亿)", "龙虎榜卖出额(亿)", "龙虎榜游资净额(亿)",
                   "龙虎榜净买入占成交比", "龙虎榜上榜原因", "龙虎榜涉及概念",
                   "上榜时人气排名", "龙虎榜"],
        "task": "task_dragon",
    },
    "enrichment": {
        "title": "金融大数据·全维度数据（估值/两融/陆股通/营收构成/经营数据/股东/分红/增减持/质押/监管/公告/基金持股等）",
        "fields": [],
        "task": "task_lixinger",
        "dynamic_prefix": "金融大数据·",
    },
}

def analyze_sentiment_keywords(text):
    bull_keywords = ['上涨', '增长', '利好', '突破', '超预期', '新高', '增持', '回购', '盈利', '增长', '业绩预增', '利好消息', '政策支持', '订单增加', '销量增长']
    bear_keywords = ['下跌', '下滑', '利空', '不及预期', '新低', '减持', '亏损', '下降', '业绩下滑', '利空消息', '监管收紧', '订单减少', '销量下滑', '风险', '暴雷']

    text_lower = text.lower()
    bull_count = sum(1 for kw in bull_keywords if kw in text)
    bear_count = sum(1 for kw in bear_keywords if kw in text)

    if bull_count > bear_count:
        return 'bull'
    elif bear_count > bull_count:
        return 'bear'
    else:
        return 'neutral'

def _latest_trade_date_datahub(days_back=12):
    now = time.time()
    if _TRADE_DATE_CACHE["date"] and (now - _TRADE_DATE_CACHE["ts"] < 3600):
        return _TRADE_DATE_CACHE["date"]
    end = datetime.datetime.now()
    start = end - datetime.timedelta(days=days_back)
    df, st = fetch_datahub("trade_cal", {
        "exchange": "SSE",
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "is_open": "1",
        "limit": 30,
    })
    date = None
    if df is not None and not df.empty:
        date = str(df["cal_date"].max())
    else:
        d = end.date()
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
        date = d.strftime("%Y%m%d")
    _TRADE_DATE_CACHE["date"] = date
    _TRADE_DATE_CACHE["ts"] = now
    return date

SENTIMENT_ZONES = [
    {"label": "恐慌", "min": 0, "max": 30, "color": "#34d399"},
    {"label": "谨慎", "min": 30, "max": 45, "color": "#22d3ee"},
    {"label": "中性", "min": 45, "max": 58, "color": "#fbbf24"},
    {"label": "乐观", "min": 58, "max": 70, "color": "#fb923c"},
    {"label": "贪婪", "min": 70, "max": 100, "color": "#f87171"},
]

def is_trading_time():
    now = _now_shanghai()
    if now.weekday() >= 5:
        return False
    t = now.time()
    morning = datetime.time(9, 30) <= t <= datetime.time(11, 30)
    afternoon = datetime.time(13, 0) <= t <= datetime.time(15, 0)
    return morning or afternoon

def _pulse_pick(df, sort_col, ascending=False, n=3, where=None):
    if df is None or getattr(df, "empty", True) or sort_col not in df.columns:
        return []
    d = df.dropna(subset=[sort_col])
    if where is not None:
        try:
            d = d[where(d)]
        except Exception:
            return []
    if d.empty:
        return []
    name_map = _stock_name_map()
    out = []
    for ts, r in d.sort_values(sort_col, ascending=ascending).head(n).iterrows():
        code = str(ts).split(".")[0]
        out.append({
            "code": code,
            "name": name_map.get(str(ts).upper()) or code,
            "close": f"{r['close']:.2f}" if pd.notna(r.get("close")) else "--",
            "pct_chg": f"{r['pct_chg']:+.2f}" if pd.notna(r.get("pct_chg")) else "--",
            "is_up": bool(r.get("pct_chg") >= 0) if pd.notna(r.get("pct_chg")) else None,
            "pe_ttm": (f"{r['pe_ttm']:.1f}" if pd.notna(r.get("pe_ttm")) and r.get("pe_ttm") > 0 else "--"),
            "pb": (f"{r['pb']:.2f}" if pd.notna(r.get("pb")) and r.get("pb") > 0 else "--"),
            "dv_ttm": (f"{r['dv_ttm']:.2f}%" if pd.notna(r.get("dv_ttm")) and r.get("dv_ttm") > 0 else "--"),
            "amount_yi": (f"{r['amount_yi']:.2f}" if pd.notna(r.get("amount_yi")) else "--"),
            "net_mf_yi": (f"{r['net_mf_yi']:+.2f}" if pd.notna(r.get("net_mf_yi")) else "--"),
            "turnover": (f"{r['turnover_rate']:.2f}%" if pd.notna(r.get("turnover_rate")) else "--"),
        })
    return out

def _lx_name(code):
    try:
        ex = _guess_exchange(code) or "SH"
        return _lookup_name_from_cache(code, ex) or code
    except Exception:
        return code

def _lx_yi(v):
    try:
        return f"{float(v) / 1e8:.1f}"
    except (TypeError, ValueError):
        return "NA"

def _lx_rows(preset, sort_order="desc", n=15):
    suffix, sort_name = lx_svc.HOT_PRESETS.get(preset, (None, None))
    if not suffix:
        return []
    rows = lx_svc.lx_hot_raw(suffix, sort_name, sort_order, n)
    return [r for r in rows if isinstance(r, dict) and "_lx_err" not in r]

def _safe_float(v):
    try:
        f = float(v)
        if f != f:
            return None
        return f
    except Exception:
        return None
def _is_blank(val):
    if val is None:
        return True
    if isinstance(val, float):
        try:
            if pd.isna(val):
                return True
        except (TypeError, ValueError):
            pass
    s = str(val).strip()
    return s == "" or s.lower() in ("none", "nan", "null", "--")

_TRADE_DATE_CACHE = {"date": None, "ts": 0}

def _now_shanghai():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        return datetime.datetime.now()

def _stock_name_map():
    now = time.time()
    if _NAME_MAP_CACHE["map"] and now - _NAME_MAP_CACHE["ts"] < _NAME_MAP_TTL:
        return _NAME_MAP_CACHE["map"]
    m = {}
    try:
        for row in db.list_all_stock_basics():
            ts = str(row.get("ts_code") or "").upper()
            nm = row.get("name")
            if ts and nm:
                m[ts] = nm
    except Exception as e:
        print(f"[namemap] 载入失败（回退为代码）: {e}")
    try:
        df = STOCK_LIST_CACHE
        if df is not None and not getattr(df, "empty", True) and "ts_code" in df.columns:
            for ts, nm in zip(df["ts_code"], df.get("name", [])):
                ts_u = str(ts).upper()
                if ts_u and nm and ts_u not in m:
                    m[ts_u] = str(nm)
    except Exception as e:
        print(f"[namemap] 实时列表补漏失败（忽略）: {e}")
    if m:
        _NAME_MAP_CACHE.update({"map": m, "ts": now})
    return m
_NAME_MAP_CACHE = {"map": None, "ts": 0}
_NAME_MAP_TTL = 3600
STOCK_LIST_TIME = 0
STOCK_LIST_FAIL_TS = 0
STOCK_LIST_FAIL_BACKOFF = 300

def _get_stock_list_safe():
    global STOCK_LIST_CACHE, STOCK_LIST_TIME, STOCK_LIST_FAIL_TS
    now = time.time()
    if STOCK_LIST_CACHE is not None and (now - STOCK_LIST_TIME < 86400):
        return STOCK_LIST_CACHE

    in_backoff = STOCK_LIST_FAIL_TS and (now - STOCK_LIST_FAIL_TS < STOCK_LIST_FAIL_BACKOFF)

    last_err = None
    if not in_backoff:
        for attempt in range(2):
            try:
                df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
                if df is not None and not df.empty:
                    df = _normalize_stock_list(df)
                    STOCK_LIST_CACHE = df
                    STOCK_LIST_TIME = now
                    STOCK_LIST_FAIL_TS = 0
                    return df
                last_err = "stock_basic 返回空 DataFrame"
            except Exception as e:
                last_err = e
                print(f"Stock List Error (attempt {attempt + 1}): {e}")
    else:
        last_err = "退避期内（上次拉取失败），跳过远程接口"
    try:
        import db as _db
        import pandas as _pd
        rows = _db.list_all_stock_basics()
        if rows:
            df = _pd.DataFrame(rows)
            if "code" in df.columns and "symbol" not in df.columns:
                df = df.rename(columns={"code": "symbol"})
            df["symbol"] = df["symbol"].astype(str).str.zfill(6)
            df = _normalize_stock_list(df[["ts_code", "symbol", "name"]])
            STOCK_LIST_CACHE = df
            STOCK_LIST_TIME = now
            print(f"Stock List: 远程接口不可用，已用本地 stocks 表兜底（{len(df)} 只）")
            return df
    except Exception as e:
        print(f"Stock List DB fallback error: {type(e).__name__}: {e}")

    try:
        ak_df = ak.stock_info_a_code_name()
        if ak_df is not None and not ak_df.empty:
            ak_df = ak_df.rename(columns={'code': 'symbol', 'name': 'name'})
            ak_df['symbol'] = ak_df['symbol'].astype(str).str.zfill(6)
            ak_df['ts_code'] = ak_df.apply(
                lambda r: f"{r['symbol']}.{_guess_exchange(r['symbol']) or 'SH'}", axis=1)
            ak_df = _normalize_stock_list(ak_df)
            STOCK_LIST_CACHE = ak_df
            STOCK_LIST_TIME = now
            print("Stock List: Tushare 限流，已用 AKShare 兜底（名字搜索可用）")
            return ak_df
    except Exception as e:
        print(f"Stock List AKShare fallback error: {e}")

    if STOCK_LIST_CACHE is not None:
        print("Stock List: 重试失败，回退旧缓存")
        return STOCK_LIST_CACHE
    STOCK_LIST_FAIL_TS = now
    print(f"Stock List Error: 无可用股票列表 ({last_err})，{STOCK_LIST_FAIL_BACKOFF}s 内不再重试")
    return None
def _normalize_stock_list(df):
    if df is None or df.empty:
        return df
    if "symbol" in df.columns:
        df = df.copy()
        df["symbol"] = df["symbol"].apply(_normalize_symbol)
    return df
def _normalize_symbol(val):
    try:
        f = float(val)
        return f"{int(round(f)):06d}"
    except (TypeError, ValueError):
        s = str(val).strip()
        if s.isdigit():
            return f"{int(s):06d}"
        return s

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, '.cache')

_WATCH_FUND_METRICS = [
    "pe_ttm", "d_pe_ttm", "pb", "pb_wo_gw", "ps_ttm", "pcf_ttm", "dyr",
    "mc", "cmc", "ecmc",
    "pe_ttm.y5.cvpos", "pb.y5.cvpos", "ps_ttm.y5.cvpos", "dyr.y5.cvpos",
    "pe_ttm.y10.cvpos", "pe_ttm.y3.cvpos",
    "shn",
]
_WATCH_KLINE_DAYS = 30
