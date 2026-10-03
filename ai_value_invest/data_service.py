import os
os.environ.setdefault("TQDM_DISABLE", "1")
import tushare as ts
import akshare as ak
import pandas as pd
import datetime
import numpy as np
import time
import re
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from fastapi.concurrency import run_in_threadpool
from data_source import get_pro, get_pro_bar, fetch_news_datahub, fetch_datahub, fetch_disclosure_rows
import config
import requests
import threading
import db
import lixinger_service as lx_svc
from lixinger import get_client, LixingerError
from dataservice.common import _normalize_stock_list
from dataservice.common import _get_stock_list_safe, STOCK_LIST_TIME, STOCK_LIST_FAIL_TS, STOCK_LIST_FAIL_BACKOFF
from dataservice.common import _NAME_MAP_CACHE, _NAME_MAP_TTL
from dataservice.common import _TRADE_DATE_CACHE, _is_blank, _now_shanghai, _stock_name_map
from dataservice.common import DATA_GROUPS, SENTIMENT_ZONES, STOCK_LIST_CACHE, pro, pro_bar, _ak_symbol, _CACHE_DIR, _fetch_safe, _guess_exchange, _is_num, _latest_trade_date_datahub, _lookup_name_from_cache, _lx_name, _lx_rows, _lx_yi, _pulse_pick, _safe_float, _to_number, _WATCH_FUND_METRICS, _WATCH_KLINE_DAYS, _yi, analyze_sentiment_keywords, is_trading_time, safe_get, safe_get_multi

from dataservice.market import _FUYAO_LHB_CACHE, evaluate_watch_goals, fetch_fuyao_dragon_tiger, fetch_lixinger_top_list, fetch_watch_quotes_sync, get_dragon_tiger_cached, get_lixinger_top_list_cached, get_market_breadth, get_market_hot_rank, get_market_limit_stats, get_market_overview_datahub, get_market_pools, get_opportunities_data_sync, get_risk_data_sync, get_watch_metric_values
from dataservice.events import task_announcement, task_dragon, task_hotrank

DATA_CACHE = {}
CACHE_TTL = 300
DATA_CACHE_MAX = 2000

def _data_cache_trim():
    if len(DATA_CACHE) <= DATA_CACHE_MAX:
        return
    items = sorted(DATA_CACHE.items(), key=lambda kv: kv[1].get("timestamp", 0))
    for k, _ in items[: len(items) // 2]:
        DATA_CACHE.pop(k, None)

_AK_SPOT_EM_BROKEN = False

def _lookup_local_stock(keyword: str):
    kw = (keyword or "").strip()
    if not kw:
        return None, None
    kw_u = kw.upper()
    if re.fullmatch(r"\d{6}(\.(SZ|SH|BJ))?", kw_u):
        code6 = kw_u.split(".")[0]
        suf = kw_u.split(".")[1] if "." in kw_u else _guess_exchange(code6)
        if suf:
            row = _local_stock_row("ts_code = %s", f"{code6}.{suf}")
            if row:
                return row["ts_code"], row["name"]
    rows = _local_stock_rows(kw)
    if not rows:
        return None, None
    for r in rows:
        if (r.get("name") or "") == kw:
            return r["ts_code"], r["name"]
    return rows[0]["ts_code"], rows[0]["name"]

def _local_stock_rows(kw: str):
    prefix = f"{kw}%"
    like = f"%{kw}%"
    try:
        conn = db.get_conn()
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ts_code, name, list_status FROM stocks "
                "WHERE name = %s OR name LIKE %s OR name LIKE %s "
                "ORDER BY CASE WHEN name = %s THEN 0 "
                "              WHEN name LIKE %s THEN 1 ELSE 2 END, ts_code "
                "LIMIT 20",
                (kw, prefix, like, kw, prefix),
            )
            return list(cur.fetchall())
    except Exception as e:
        print(f"⚠️ [Stock] 本地股票表查询失败 {kw}: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

def _local_stock_row(where: str, *args):
    try:
        conn = db.get_conn()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT ts_code, name FROM stocks WHERE {where} LIMIT 1", args)
            return cur.fetchone()
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

def _get_stock_code_sync(keyword: str):
    try:
        keyword = (keyword or "").strip()
        if not keyword:
            return None, None
        u = keyword.upper()

        m = re.fullmatch(r"(\d{6})\.(SZ|SH|BJ)", u)
        if m:
            code6, suf = m.group(1), m.group(2)
            return f"{code6}.{suf}", _lookup_name_from_cache(code6, suf) or u

        m = re.search(r"(?<!\\d)(\d{6})(?:\.(SZ|SH|BJ))?(?!\\d)", u)
        if m:
            code6 = m.group(1)
            suf = m.group(2) or _guess_exchange(code6)
            if suf:
                ts_code = f"{code6}.{suf}"
                if STOCK_LIST_CACHE is None or STOCK_LIST_CACHE.empty:
                    _get_stock_list_safe()
                return ts_code, _lookup_name_from_cache(code6, suf) or ts_code

        local = _lookup_local_stock(keyword)
        if local and local[0]:
            return local

        df = _get_stock_list_safe()
        if df is not None and not df.empty:
            m2 = df[df['name'] == keyword]
            if not m2.empty:
                return m2.iloc[0]['ts_code'], m2.iloc[0]['name']
            m2 = df[df['name'].str.contains(keyword, na=False)]
            if not m2.empty:
                return m2.iloc[0]['ts_code'], m2.iloc[0]['name']

        return None, None
    except Exception as e:
        print(f"Search Error: {e}")
        return None, None

def task_realtime(symbol):
    data = {}

    try:
        df = ts.get_realtime_quotes(symbol)
        if df is not None and not df.empty:
            row = df.iloc[0]
            price = float(row['price'])
            pre_close = float(row['pre_close'])
            volume = float(row['volume'])
            amount = float(row['amount'])

            change_pct = 0.0
            if pre_close > 0:
                change_pct = ((price - pre_close) / pre_close) * 100

            data.update({
                "当前价格": f"{price:.2f} 元",
                "今日涨跌幅": f"{change_pct:.2f}%",
                "成交量": f"{volume/100:.0f} 手",
                "成交额": f"{amount/100000000:.2f} 亿元",
            })
            return data
    except Exception as e:
        print(f"⚠️ TS Realtime Failed: {e}, switching to AKShare...")

    try:
        df = ak.stock_bid_ask_em(symbol=symbol)
        if not df.empty:
            pass

        min_df = ak.stock_zh_a_hist_min_em(symbol=symbol, period='1', adjust='')
        if not min_df.empty:
            latest = min_df.iloc[-1]
            price = float(latest['收盘'])

            change_pct = "N/A"
            if '涨跌幅' in min_df.columns:
                 change_pct = f"{latest['涨跌幅']}%"

            data.update({
                "当前价格": f"{price:.2f} 元",
                "今日涨跌幅": change_pct,
                "成交量": f"{latest['成交量']} 手",
                "成交额": f"{latest['成交额']}",
            })
            return data

    except Exception as e:
        print(f"❌ Realtime Data Error: {e}")

    return data

def task_daily_basic(ts_code):
    data = {}
    df = _fetch_safe(pro.daily_basic, "daily_basic", ts_code=ts_code, limit=1,
                     fields='close,pe,pe_ttm,pb,ps_ttm,dv_ttm,dv_ratio,turnover_rate,volume_ratio,total_share,float_share,total_mv,circ_mv')
    if df is not None and not df.empty:
        row = df.iloc[0]
        data.update({
            "PE(静态)": safe_get(row, 'pe'),
            "PE(TTM)": safe_get(row, 'pe_ttm'),
            "PB(市净率)": safe_get(row, 'pb'),
            "PS(市销率)": safe_get(row, 'ps_ttm'),
            "股息率(TTM)": safe_get(row, 'dv_ttm', unit="%"),
            "股息率(静态)": safe_get(row, 'dv_ratio', unit="%"),
            "总股本": safe_get(row, 'total_share', multiplier=1/10000, unit="亿股"),
            "流通股本": safe_get(row, 'float_share', multiplier=1/10000, unit="亿股"),
            "总市值": safe_get(row, 'total_mv', multiplier=1/10000, unit="亿元"),
            "流通市值": safe_get(row, 'circ_mv', multiplier=1/10000, unit="亿元"),
            "换手率": safe_get(row, 'turnover_rate', unit="%"),
            "量比": safe_get(row, 'volume_ratio'),
        })
        if "当前价格" not in data:
            data["当前价格"] = f"{safe_get(row, 'close')} 元"
    if "PE(TTM)" not in data or data.get("总市值") in (None, "N/A"):
        for k, v in _ak_valuation(ts_code).items():
            data.setdefault(k, v)
    return data

def task_dividend(ts_code):
    data = {}
    df = _fetch_safe(pro.dividend, "dividend", ts_code=ts_code,
                     fields='ts_code,end_date,div_proc,cash_div', limit=5)
    if df is not None and not df.empty:
        df = df.copy()
        df['cash_div'] = pd.to_numeric(df['cash_div'], errors='coerce')
        imp = df[df['div_proc'].astype(str).str.contains('实施', na=False)]
        pick = (imp if not imp.empty else df).sort_values('end_date', ascending=False).iloc[0]
        cd = pick.get('cash_div')
        if cd is not None and not pd.isna(cd) and cd > 0:
            data["每股现金分红(最新)"] = f"{cd:.4f} 元"
            data["_cash_div_raw"] = float(cd)
            data["分红报告期"] = str(pick.get('end_date'))
    return data

def task_valuation_percentile(ts_code):
    data = {}
    try:
        today = datetime.datetime.now().strftime('%Y%m%d')
        start = (datetime.datetime.now() - datetime.timedelta(days=365 * 3)).strftime('%Y%m%d')
        df = _fetch_safe(pro.daily_basic, "daily_basic_hist", ts_code=ts_code,
                         start_date=start, end_date=today, fields='trade_date,pe_ttm,pb', limit=800)
        if df is not None and len(df) > 20:
            df = df.copy()
            df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce')
            df['pb'] = pd.to_numeric(df['pb'], errors='coerce')
            if 'trade_date' in df.columns:
                df = df.sort_values('trade_date')
            df = df.dropna(subset=['pe_ttm', 'pb'])
            df = df[(df['pe_ttm'] > 0) & (df['pb'] > 0)]
            if len(df) > 20:
                cur_pe = df['pe_ttm'].iloc[-1]
                cur_pb = df['pb'].iloc[-1]
                pe_pct = float((df['pe_ttm'] < cur_pe).mean() * 100)
                pb_pct = float((df['pb'] < cur_pb).mean() * 100)
                data["PE(TTM)历史百分位"] = f"{pe_pct:.1f}%（近{len(df)}个交易日）"
                data["PB历史百分位"] = f"{pb_pct:.1f}%"
    except Exception as e:
        print(f"[data] valuation_percentile 失败: {e}")
    return data

def task_fina_indicator(ts_code):
    data = {}
    df = _fetch_safe(pro.fina_indicator, ts_code=ts_code, limit=1)
    if df is not None and not df.empty:
        row = df.iloc[0]
        data.update({
            "财报报告期": safe_get(row, 'end_date'),
            "ROE(加权)": safe_get(row, 'roe_waa', unit="%"),
            "ROIC": safe_get(row, 'roic', unit="%"),
            "销售毛利率": safe_get(row, 'grossprofit_margin', unit="%"),
            "销售净利率": safe_get(row, 'netprofit_margin', unit="%"),
            "资产负债率": safe_get(row, 'debt_to_assets', unit="%"),
            "_fina_deduct_profit": safe_get(row, 'profit_dedt', multiplier=1/1e8, unit="亿元"),
            "流动比率": safe_get(row, 'current_ratio'),
            "速动比率": safe_get(row, 'quick_ratio'),

            "存货周转率": safe_get(row, 'inv_turn'),
            "应收账款周转率": safe_get(row, 'ar_turn'),
            "总资产周转率": safe_get_multi(row, ['assets_turn', 'ca_turn']),

            "营收同比增速": safe_get(row, 'tr_yoy', unit="%"),
            "净利同比增速": safe_get(row, 'netprofit_yoy', unit="%"),
            "每股收益(EPS)": safe_get(row, 'eps', unit="元"),
            "每股净资产(BPS)": safe_get(row, 'bps', unit="元"),
            "每股经营现金流": safe_get(row, 'ocfps', unit="元"),
        })
    if not data:
        data = _ak_fina(ts_code)
    return data

def task_income(ts_code):
    data = {}
    df = _fetch_safe(pro.income, ts_code=ts_code, limit=1)
    if df is not None and not df.empty:
        row = df.iloc[0]
        data.update({
            "利润表报告期": safe_get(row, 'end_date'),
            "营业总收入": safe_get(row, 'total_revenue', multiplier=1/1e8, unit="亿元"),
            "营业总成本": safe_get(row, 'total_cost', multiplier=1/1e8, unit="亿元"),
            "研发费用": safe_get(row, 'rd_exp', multiplier=1/1e8, unit="亿元"),
            "财务费用": safe_get(row, 'fin_exp', multiplier=1/1e8, unit="亿元"),
            "归母净利润": safe_get(row, 'n_income_attr_p', multiplier=1/1e8, unit="亿元"),
            "扣非净利润": safe_get_multi(row, ['n_income_attr_p_cut', 'profit_smooth', 'dt_netprofit_incl_min_int_inc'], multiplier=1/1e8, unit="亿元")
        })
        data["_revenue_raw"] = _to_number(row.get('total_revenue'))
    if not data:
        data = _ak_income(ts_code)
    return data

def task_cashflow(ts_code):
    data = {}
    df = _fetch_safe(pro.cashflow, ts_code=ts_code, limit=1)
    if df is not None and not df.empty:
        row = df.iloc[0]
        n_act = _to_number(row.get('n_cashflow_act'))
        if n_act is None: n_act = 0
        n_inv = _to_number(row.get('n_cashflow_inv'))
        fcf_val = _to_number(row.get('free_cashflow'))
        if fcf_val is not None:
            fcf = fcf_val
        else:
            cap_exp = _to_number(row.get('c_pay_acquis_asset'))
            if cap_exp is None:
                cap_exp = _to_number(row.get('c_pay_acq_const_fiolta'))
            if cap_exp is None: cap_exp = 0
            fcf = n_act - cap_exp

        data.update({
            "现金流报告期": safe_get(row, 'end_date'),
            "经营活动现金流净额": f"{n_act/1e8:.2f} 亿元",
            "投资活动现金流净额": (f"{n_inv/1e8:.2f} 亿元" if n_inv is not None else "--"),
            "估算自由现金流(FCF)": f"{fcf/1e8:.2f} 亿元",
        })
    if not data:
        data = _ak_cashflow(ts_code)
    return data

def task_tech_ma(ts_code):
    data = {}
    try:
        today = datetime.datetime.now().strftime('%Y%m%d')
        start = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime('%Y%m%d')
        df = pro_bar(ts_code=ts_code, adj='qfq', start_date=start, end_date=today)
        if df is not None and len(df) > 20:
            closes = df['close'].values
            ma5 = np.mean(closes[:5])
            ma20 = np.mean(closes[:20])
            data.update({
                "MA5": f"{ma5:.2f}",
                "MA20": f"{ma20:.2f}",
                "趋势信号": "多头排列" if ma5 > ma20 else "空头排列"
            })
    except Exception:
        pass
    if "MA5" not in data:
        data.update(_ak_tech_ma(ts_code))
    return data

def _ak_latest_row(df, date_col):
    if df is None or df.empty:
        return None
    df = df.copy()
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col]).sort_values(date_col, ascending=False)
    return df.iloc[0] if not df.empty else None

def _ak_income(ts_code):
    data = {}
    try:
        code6, ex = _ak_symbol(ts_code)
        df = ak.stock_profit_sheet_by_report_em(symbol=f"{ex}{code6}")
        r = _ak_latest_row(df, 'REPORT_DATE')
        if r is None:
            return data
        yi = lambda v: (float(v) / 1e8) if isinstance(v, (int, float)) and not pd.isna(v) else None
        pc = lambda v: float(v) if isinstance(v, (int, float)) and not pd.isna(v) else None
        ti = yi(r.get('TOTAL_OPERATE_INCOME'))
        if ti is not None: data["营业总收入"] = f"{ti:.2f} 亿元"
        ni = yi(r.get('PARENT_NETPROFIT'))
        if ni is not None: data["归母净利润"] = f"{ni:.2f} 亿元"
        dn = yi(r.get('DEDUCT_PARENT_NETPROFIT'))
        if dn is not None: data["扣非净利润"] = f"{dn:.2f} 亿元"
        rd = yi(r.get('RESEARCH_EXPENSE'))
        if rd is not None: data["研发费用"] = f"{rd:.2f} 亿元"
        y1 = pc(r.get('TOTAL_OPERATE_INCOME_YOY'))
        if y1 is not None: data["营收同比增速"] = f"{y1:.2f}%"
        y2 = pc(r.get('PARENT_NETPROFIT_YOY'))
        if y2 is not None: data["净利同比增速"] = f"{y2:.2f}%"
        rd_date = r.get('REPORT_DATE')
        if rd_date is not None and not pd.isna(rd_date):
            data["利润表报告期"] = pd.to_datetime(rd_date).strftime('%Y-%m-%d')
    except Exception as e:
        print(f"[ak] income 兜底失败: {e}")
    return data

def _ak_cashflow(ts_code):
    data = {}
    try:
        code6, ex = _ak_symbol(ts_code)
        df = ak.stock_cash_flow_sheet_by_report_em(symbol=f"{ex}{code6}")
        r = _ak_latest_row(df, 'REPORT_DATE')
        if r is None:
            return data
        yi = lambda v: (float(v) / 1e8) if isinstance(v, (int, float)) and not pd.isna(v) else None
        nocf = yi(r.get('NETCASH_OPERATE'))
        if nocf is not None: data["经营活动现金流净额"] = f"{nocf:.2f} 亿元"
        icf = yi(r.get('NETCASH_INVEST'))
        if nocf is not None and icf is not None:
            data["估算自由现金流(FCF)"] = f"{nocf - icf:.2f} 亿元"
        rd_date = r.get('REPORT_DATE')
        if rd_date is not None and not pd.isna(rd_date):
            data["现金流报告期"] = pd.to_datetime(rd_date).strftime('%Y-%m-%d')
    except Exception as e:
        print(f"[ak] cashflow 兜底失败: {e}")
    return data

def _ak_fina(ts_code):
    data = {}
    try:
        code6, _ = _ak_symbol(ts_code)
        df = ak.stock_financial_analysis_indicator(symbol=code6)
        if df is None or df.empty:
            return data
        df = df.dropna(subset=['销售毛利率(%)', '资产负债率(%)'], how='any')
        r = _ak_latest_row(df, '日期')
        if r is None:
            return data
        pc = lambda k: (float(r[k]) if k in r and isinstance(r[k], (int, float)) and not pd.isna(r[k]) else None)
        roe = pc('加权净资产收益率(%)') or pc('净资产收益率(%)')
        if roe is not None: data["ROE(加权)"] = f"{roe:.2f}%"
        gm = pc('销售毛利率(%)')
        if gm is not None: data["销售毛利率"] = f"{gm:.2f}%"
        nm = pc('销售净利率(%)')
        if nm is not None: data["销售净利率"] = f"{nm:.2f}%"
        dr = pc('资产负债率(%)')
        if dr is not None: data["资产负债率"] = f"{dr:.2f}%"
        cr = pc('流动比率')
        if cr is not None: data["流动比率"] = f"{cr:.2f}"
        qr = pc('速动比率')
        if qr is not None: data["速动比率"] = f"{qr:.2f}"
        it = pc('存货周转率(次)')
        if it is not None: data["存货周转率"] = f"{it:.2f}"
        art = pc('应收账款周转率(次)')
        if art is not None: data["应收账款周转率"] = f"{art:.2f}"
        ocfps = pc('每股经营性现金流(元)')
        if ocfps is not None: data["每股经营现金流"] = f"{ocfps:.2f} 元"
    except Exception as e:
        print(f"[ak] fina 兜底失败: {e}")
    return data

def _ak_call_with_timeout(fn, timeout=8, default=None):
    import concurrent.futures as _cf
    try:
        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(fn).result(timeout=timeout)
    except Exception:
        return default

def _ak_valuation(ts_code):
    global _AK_SPOT_EM_BROKEN
    data = {}
    if _AK_SPOT_EM_BROKEN:
        return data
    try:
        code6, _ = _ak_symbol(ts_code)
        df = _ak_call_with_timeout(ak.stock_zh_a_spot_em, timeout=8)
        if df is None or df.empty:
            return data
        r = df[df['代码'] == code6]
        if r.empty:
            return data
        r = r.iloc[0]
        pc = lambda k: (float(r[k]) if k in r and isinstance(r[k], (int, float)) and not pd.isna(r[k]) else None)
        yi = lambda k: (float(r[k]) / 1e8) if k in r and isinstance(r[k], (int, float)) and not pd.isna(r[k]) else None
        pe = pc('市盈率-动态')
        if pe is not None: data["PE(TTM)"] = pe
        pb = pc('市净率')
        if pb is not None: data["PB(市净率)"] = pb
        dv = pc('股息率')
        if dv is not None: data["股息率(TTM)"] = f"{dv:.2f}%" if dv > 0 else "N/A"
        tm = yi('总市值')
        if tm is not None: data["总市值"] = f"{tm:.2f} 亿元"
        cm = yi('流通市值')
        if cm is not None: data["流通市值"] = f"{cm:.2f} 亿元"
        tr = pc('换手率')
        if tr is not None: data["换手率"] = f"{tr:.2f}%"
    except Exception as e:
        print(f"[ak] valuation 兜底失败: {e}")
        _AK_SPOT_EM_BROKEN = True
    return data

def task_technical(ts_code):
    data = {}
    dfp = _fetch_safe(pro.stk_factor_pro, "stk_factor_pro", ts_code=ts_code, limit=1)
    if dfp is not None and not dfp.empty:
        row = dfp.iloc[0]
        num = lambda k: _fmt_num(safe_get(row, k))
        data.update({
            "技术指标日期": safe_get(row, 'trade_date'),
            "MACD-DIF": num('macd_dif_qfq'),
            "MACD-DEA": num('macd_dea_qfq'),
            "MACD-柱": num('macd_qfq'),
            "KDJ-K": num('kdj_k_qfq'),
            "KDJ-D": num('kdj_d_qfq'),
            "KDJ-J": num('kdj_qfq'),
            "RSI6": num('rsi_qfq_6'),
            "RSI12": num('rsi_qfq_12'),
            "RSI24": num('rsi_qfq_24'),
            "BOLL上轨": num('boll_upper_qfq'),
            "BOLL中轨": num('boll_mid_qfq'),
            "BOLL下轨": num('boll_lower_qfq'),
            "CCI": num('cci_qfq'),
            "WR(威廉)": num('wr_qfq'),
            "BIAS(乖离率)": num('bias1_qfq'),
            "ATR(真实波幅)": num('atr_qfq'),
            "PSY(心理线)": num('psy_qfq'),
            "ROC(变动率)": num('roc_qfq'),
            "DMI-ADX": num('dmi_adx_qfq'),
            "MTM(动量)": num('mtm_qfq'),
        })
        obv = _to_number(row.get('obv_qfq'))
        if obv is not None:
            data["OBV(能量潮)"] = f"{obv:,.0f}"
        return data

    df = _fetch_safe(pro.stk_factor, "stk_factor", ts_code=ts_code, limit=1)
    if df is not None and not df.empty:
        row = df.iloc[0]
        num = lambda k: _fmt_num(safe_get(row, k))
        data.update({
            "技术指标日期": safe_get(row, 'trade_date'),
            "MACD-DIF": num('macd_dif'),
            "MACD-DEA": num('macd_dea'),
            "MACD-柱": num('macd'),
            "KDJ-K": num('kdj_k'),
            "KDJ-D": num('kdj_d'),
            "KDJ-J": num('kdj_j'),
            "RSI6": num('rsi_6'),
            "RSI12": num('rsi_12'),
            "RSI24": num('rsi_24'),
            "BOLL上轨": num('boll_upper'),
            "BOLL中轨": num('boll_mid'),
            "BOLL下轨": num('boll_lower'),
            "CCI": num('cci'),
        })
    return data

def task_moneyflow(ts_code):
    data = {}
    df = _fetch_safe(pro.moneyflow, ts_code=ts_code, limit=5)
    if df is None or df.empty:
        return data
    yi = lambda v: (f"{float(v) / 1e4:.2f} 亿元" if _is_num(v) else "N/A")
    if 'trade_date' in df.columns:
        df = df.sort_values('trade_date', ascending=False)
    row = df.iloc[0]
    for src, dst in [
        ('net_mf_amount', '主力净流入'),
        ('buy_elg_amount', '特大单买入额'), ('sell_elg_amount', '特大单卖出额'),
        ('buy_lg_amount', '大单买入额'), ('sell_lg_amount', '大单卖出额'),
        ('buy_md_amount', '中单买入额'), ('sell_md_amount', '中单卖出额'),
        ('buy_sm_amount', '小单买入额'), ('sell_sm_amount', '小单卖出额'),
    ]:
        data[dst] = yi(safe_get_multi(row, [src, src.replace('net_mf_amount', 'net_mf_inflow')]))
    data["资金流日期"] = safe_get(row, 'trade_date')

    net = safe_get_multi(row, ['net_mf_amount', 'net_mf_inflow'])
    if _is_num(net):
        v = float(net) / 1e4
        data["主力资金方向"] = "净流入" if v > 0 else ("净流出" if v < 0 else "持平")

    try:
        seq = []
        for i in range(min(5, len(df))):
            r = df.iloc[i]
            v = safe_get_multi(r, ['net_mf_amount', 'net_mf_inflow'])
            d = safe_get(r, 'trade_date')
            if _is_num(v):
                seq.append(f"{d}:{float(v) / 1e4:+.2f}亿")
        if seq:
            data["近5日主力净额"] = " , ".join(reversed(seq))
    except Exception:
        pass
    return data

def task_multiyear(ts_code):
    data = {}
    df = _fetch_safe(pro.fina_indicator, ts_code=ts_code, limit=12)
    if df is None or df.empty:
        return data
    rows = []
    for i in range(len(df)):
        r = df.iloc[i]
        ed = str(safe_get(r, 'end_date') or "")
        if ed.endswith("1231"):
            rows.append(r)
        if len(rows) >= 5:
            break
    if not rows:
        rows = [df.iloc[i] for i in range(min(3, len(df)))]

    lines = []
    for r in rows:
        ed = safe_get(r, 'end_date')
        roe = safe_get(r, 'roe_waa', unit="%")
        npm = safe_get(r, 'netprofit_margin', unit="%")
        dta = safe_get(r, 'debt_to_assets', unit="%")
        tr_yoy = safe_get(r, 'tr_yoy', unit="%")
        np_yoy = safe_get(r, 'netprofit_yoy', unit="%")
        lines.append(f"{ed} | ROE {roe} | 净利率 {npm} | 资产负债率 {dta} | 营收增速 {tr_yoy} | 净利增速 {np_yoy}")
    if lines:
        data["近年年报财务趋势"] = "\n    " + "\n    ".join(lines)
        try:
            vals = []
            for r in rows:
                v = safe_get(r, 'roe_waa')
                if _is_num(v):
                    vals.append(float(v))
            if len(vals) >= 2:
                first, last = vals[-1], vals[0]
                if last > first * 1.1:
                    data["ROE趋势"] = "改善"
                elif last < first * 0.9:
                    data["ROE趋势"] = "下滑"
                else:
                    data["ROE趋势"] = "基本稳定"
        except Exception:
            pass
    return data

def task_dividend_hist(ts_code):
    data = {}
    df = _fetch_safe(pro.dividend, ts_code=ts_code, limit=40)
    if df is None or df.empty:
        return data
    try:
        df = df.sort_values("end_date", ascending=False)
    except Exception:
        pass
    lines = []
    paid = 0
    for i in range(min(6, len(df))):
        r = df.iloc[i]
        proc = str(safe_get(r, 'div_proc') or "")
        ed = safe_get(r, 'end_date')
        cash = safe_get(r, 'cash_div')
        if proc and proc != "实施":
            continue
        lines.append(f"{ed} | 每10股派息 {cash if cash not in (None,'') else '—'} 元")
        paid += 1
        if paid >= 5:
            break
    if lines:
        data["近年分红方案"] = "\n    " + "\n    ".join(lines)
        data["近年累计分红次数"] = f"{len(lines)} 次（已实施）"
    return data

def task_main_business(ts_code):
    data = {}
    df = _fetch_safe(pro.fina_mainbz, ts_code=ts_code, limit=30)
    if df is None or df.empty:
        return data
    latest_ed = str(safe_get(df.iloc[0], 'end_date') or "")
    rows = [df.iloc[i] for i in range(len(df))
            if str(safe_get(df.iloc[i], 'end_date') or "") == latest_ed]
    items = []
    for r in rows:
        item = str(safe_get(r, 'bz_item') or "").strip()
        if not item or any(k in item for k in ("合计", "小计", "总计")):
            continue
        sales = safe_get(r, 'bz_sales')
        profit = safe_get(r, 'bz_profit')
        if not _is_num(sales):
            continue
        items.append((item, float(sales), profit))
    seen, uniq = set(), []
    for it in items:
        key = (it[0], round(it[1], 2))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    uniq.sort(key=lambda x: -x[1])
    if not uniq:
        return data

    out = []
    for item, sales, profit in uniq[:6]:
        sv = f"{sales / 1e8:.2f} 亿元"
        pv = f"{float(profit) / 1e8:.2f} 亿元" if _is_num(profit) else "—"
        gm = ""
        if _is_num(profit) and sales > 0:
            gm = f" | 毛利率 {float(profit) / sales * 100:.1f}%"
        out.append(f"{item}: 营收 {sv}{gm} | 毛利 {pv}")
    data[f"主营构成（{latest_ed}，按营收降序）"] = (
        "\n    " + "\n    ".join(out)
        + "\n    （注：接口返回含产品/地区等多套口径，各项不可直接相加，故不提供占比）"
    )
    return data

def task_holders(ts_code):
    data = {}
    try:
        df = _fetch_safe(pro.stk_holdernumber, ts_code=ts_code, limit=4)
        if df is not None and not df.empty:
            try:
                df = df.sort_values("end_date", ascending=False)
            except Exception:
                pass
            seq = []
            for i in range(min(4, len(df))):
                r = df.iloc[i]
                seq.append(f"{safe_get(r, 'end_date')}: {safe_get(r, 'holder_num')} 户")
            if seq:
                data["股东户数变化"] = "\n    " + "\n    ".join(seq)
    except Exception:
        pass
    try:
        df2 = _fetch_safe(pro.top10_holders, ts_code=ts_code, limit=10)
        if df2 is not None and not df2.empty:
            try:
                df2 = df2.sort_values("end_date", ascending=False)
            except Exception:
                pass
            latest_ed = str(safe_get(df2.iloc[0], 'end_date') or "")
            names = []
            for i in range(len(df2)):
                r = df2.iloc[i]
                if str(safe_get(r, 'end_date') or "") != latest_ed:
                    continue
                nm = safe_get(r, 'holder_name')
                ratio = safe_get(r, 'hold_ratio', unit="%")
                if nm:
                    names.append(f"{nm}（{ratio}）")
                if len(names) >= 5:
                    break
            if names:
                data[f"前五大股东（{latest_ed}）"] = "、".join(names)
    except Exception:
        pass
    return data

_INDUSTRY_CACHE = {}
_INDUSTRY_TTL = 7 * 86400
_INDUSTRY_CACHE_FILE = os.path.join(_CACHE_DIR, 'industry_map.json')
_SNAPSHOT_DIR = _CACHE_DIR

def _industry_load_file():
    try:
        if not os.path.exists(_INDUSTRY_CACHE_FILE):
            return None
        with open(_INDUSTRY_CACHE_FILE, 'r', encoding='utf-8') as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            return None
        ts_ = obj.get('_ts') or 0
        m = obj.get('map')
        if not isinstance(m, dict) or not m:
            return None
        return ts_, m
    except Exception:
        return None

def _industry_save_file(m):
    try:
        d = os.path.dirname(_INDUSTRY_CACHE_FILE)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(_INDUSTRY_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'_ts': time.time(), 'map': m}, f, ensure_ascii=False)
    except Exception as e:
        print(f"[peer] 行业缓存写入失败（不影响分析）: {e}")

def _industry_fetch():
    CHUNK, MAX_ROWS = 500, 7000
    m, offset = {}, 0
    while offset < MAX_ROWS:
        got = None
        for _ in range(2):
            try:
                df = _fetch_safe(pro.stock_basic, "stock_basic", limit=CHUNK,
                                 offset=offset, fields='ts_code,industry')
                if df is not None and not df.empty:
                    got = df
                    break
            except Exception:
                pass
        if got is None:
            print(f"[peer] 行业分块 offset={offset} 抓取失败，本次终止")
            break
        for j in range(len(got)):
            r = got.iloc[j]
            m[str(r.get('ts_code'))] = str(r.get('industry') or "")
        if len(got) < CHUNK:
            break
        offset += CHUNK
    return m or None

_INDUSTRY_BUILDING = False

def _industry_build_async():
    global _INDUSTRY_BUILDING
    try:
        m = _industry_fetch()
        if m:
            _INDUSTRY_CACHE.update({'ts': time.time(), 'map': m})
            _industry_save_file(m)
            print(f"[peer] 行业分类后台构建完成（{len(m)} 家）")
    except Exception as e:
        print(f"[peer] 行业分类后台构建异常: {e}")
    finally:
        _INDUSTRY_BUILDING = False

def _industry_map():
    global _INDUSTRY_BUILDING
    now = time.time()
    cached = _INDUSTRY_CACHE.get('map')
    if cached and now - _INDUSTRY_CACHE.get('ts', 0) < _INDUSTRY_TTL:
        return cached

    loaded = _industry_load_file()
    if loaded:
        ts_, m = loaded
        if now - ts_ < _INDUSTRY_TTL:
            _INDUSTRY_CACHE.update({'ts': ts_, 'map': m})
            return m

    if loaded:
        if not _INDUSTRY_BUILDING:
            _INDUSTRY_BUILDING = True
            threading.Thread(target=_industry_build_async, daemon=True).start()
        if not cached:
            _INDUSTRY_CACHE.update({'ts': loaded[0], 'map': loaded[1]})
        return cached or loaded[1]

    if not _INDUSTRY_BUILDING:
        _INDUSTRY_BUILDING = True
        threading.Thread(target=_industry_build_async, daemon=True).start()
        print("[peer] 行业分类首次后台构建中，本次 peer 组先降级为全市场口径")
    return cached or {}

_SNAPSHOT_CACHE = {}
_SNAPSHOT_TTL = 1800

_DAILY_BASIC_PAGE = 5000
_DAILY_BASIC_MAX_PAGES = 6

def _market_snapshot(trade_date):
    now = time.time()

    def _cached(d):
        c = _SNAPSHOT_CACHE.get(d)
        if c and now - c[0] < _SNAPSHOT_TTL:
            return c[1]
        fp = os.path.join(_SNAPSHOT_DIR, f"snapshot_{d}.json")
        if os.path.exists(fp):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    rows = json.load(f)
                if rows:
                    _SNAPSHOT_CACHE[d] = (now, rows)
                    return rows
            except Exception:
                pass
        return None

    hit = _cached(trade_date)
    if hit:
        return hit, trade_date

    d0 = datetime.datetime.strptime(str(trade_date), "%Y%m%d").date()
    for delta in range(0, 8):
        d = d0 - datetime.timedelta(days=delta)
        ds_str = d.strftime("%Y%m%d")
        if delta:
            hit = _cached(ds_str)
            if hit:
                print(f"⚠️ [peer] {trade_date} 无估值快照，回退到 {ds_str}（缓存）")
                return hit, ds_str
        rows, offset = [], 0
        for _page in range(_DAILY_BASIC_MAX_PAGES):
            df = _fetch_safe(pro.daily_basic, "daily_basic", trade_date=ds_str,
                             limit=_DAILY_BASIC_PAGE, offset=offset,
                             fields='ts_code,pe_ttm,pb')
            if df is None or df.empty:
                break
            rows.extend([str(c), _to_number(pe), _to_number(pb)]
                        for c, pe, pb in zip(df['ts_code'], df['pe_ttm'], df['pb']))
            if len(df) < _DAILY_BASIC_PAGE:
                break
            offset += _DAILY_BASIC_PAGE
        if not rows:
            continue
        try:
            os.makedirs(_SNAPSHOT_DIR, exist_ok=True)
            fp = os.path.join(_SNAPSHOT_DIR, f"snapshot_{ds_str}.json")
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(rows, f, ensure_ascii=False)
        except Exception as e:
            print(f"[peer] 快照缓存写入失败（不影响分析）: {e}")
        _SNAPSHOT_CACHE[ds_str] = (now, rows)
        _snapshot_cleanup(keep=ds_str)
        if delta:
            print(f"⚠️ [peer] {trade_date} 无估值快照，回退到 {ds_str}（{len(rows)} 只）")
        return rows, ds_str
    return None, None
    return rows

def _snapshot_cleanup(keep: str, max_files: int = 10):
    try:
        if not os.path.isdir(_SNAPSHOT_DIR):
            return
        files = [f for f in os.listdir(_SNAPSHOT_DIR)
                 if f.startswith("snapshot_") and f.endswith(".json")]
        if len(files) <= max_files:
            return
        files.sort()
        for f in files[:-max_files]:
            if f == f"snapshot_{keep}.json":
                continue
            try:
                os.remove(os.path.join(_SNAPSHOT_DIR, f))
            except Exception:
                pass
    except Exception as e:
        print(f"[peer] 快照清理异常（不影响分析）: {e}")

def task_peer_compare(ts_code):
    data = {}
    try:
        ind_map = _industry_map()
        my_ind = ind_map.get(ts_code) or None

        trade_date = _latest_trade_date_datahub()
        rows, used_date = _market_snapshot(trade_date)
        if not rows:
            return data
        data["对比交易日"] = used_date or trade_date

        cur_pe = cur_pb = None
        for c, pe, pb in rows:
            if c == ts_code:
                cur_pe, cur_pb = pe, pb
                break

        def _emit(label, subset):
            for idx, name, cur in ((1, "PE", cur_pe), (2, "PB", cur_pb)):
                vals = sorted(r[idx] for r in subset if r[idx] is not None and r[idx] > 0)
                if not vals or cur is None or cur <= 0:
                    continue
                med = vals[len(vals) // 2]
                below = sum(1 for v in vals if v < cur)
                data[f"{label}{name}分位"] = (
                    f"{below / len(vals) * 100:.0f}%（{label} {len(vals)} 家有效样本，越低越便宜）")
                data[f"{label}{name}中位数"] = f"{med:.2f}"
                data[f"当前{name}"] = f"{cur:.2f}"
                data[f"{name}相对{label}中位数"] = f"{(cur / med - 1) * 100:+.1f}%"

        if my_ind:
            peers = [r for r in rows if ind_map.get(r[0]) == my_ind]
            data["所属行业"] = my_ind
            data["行业样本数"] = f"{len(peers)} 家"
            if len(peers) >= 5:
                _emit("行业", peers)
            else:
                data["行业对比"] = "同行业样本不足 5 家，跳过行业分位（仅保留全市场口径）"
        else:
            data["行业对比"] = "未取到行业分类，仅提供全市场口径"

        _emit("全市场", rows)
    except Exception as e:
        print(f"[peer] 同业对比失败: {e}")
    return data

def task_balance(ts_code):
    data = {}
    df = _fetch_safe(pro.balancesheet, "balancesheet", ts_code=ts_code, limit=1)
    if df is None or df.empty:
        return data
    row = df.iloc[0]

    money = _yi(row.get('money_cap'))
    inventories = _yi(row.get('inventories'))
    ar = _yi(row.get('accounts_receiv'))
    oth_recv = _yi(row.get('oth_receiv'))
    contract = _yi(row.get('contract_liab'))
    intan = _yi(row.get('intan_assets'))
    goodwill = _yi(row.get('goodwill'))
    ta = _yi(row.get('total_assets'))
    tl = _yi(row.get('total_liab'))
    eq = _yi(row.get('total_hldr_eqy_exc_min_int'))
    ib = sum(_yi(row.get(k)) or 0 for k in
             ('st_borr', 'lt_borr', 'bond_payable', 'non_cur_liab_due_1y', 'cb_borr'))

    data["资产负债表报告期"] = safe_get(row, 'end_date')
    if ta:
        data["总资产"] = f"{ta:.2f} 亿元"
    if tl is not None:
        data["总负债"] = f"{tl:.2f} 亿元"
    if eq:
        data["归母净资产"] = f"{eq:.2f} 亿元"
    if money is not None:
        data["货币资金"] = f"{money:.2f} 亿元"
    data["有息负债合计"] = f"{ib:.2f} 亿元"
    if money is not None:
        data["净现金(货币资金-有息负债)"] = f"{money - ib:.2f} 亿元"
    if inventories is not None:
        data["存货"] = f"{inventories:.2f} 亿元"
    if ar is not None:
        data["应收账款"] = f"{ar:.2f} 亿元"
    if oth_recv is not None:
        data["其他应收款"] = f"{oth_recv:.2f} 亿元"
    if contract is not None:
        data["合同负债(预收款)"] = f"{contract:.2f} 亿元"
    if intan is not None:
        data["无形资产"] = f"{intan:.2f} 亿元"

    if ta and ta > 0:
        if tl is not None:
            data["资产负债率(表算)"] = f"{tl / ta * 100:.2f} %"
        if ib > 0:
            data["有息负债率"] = f"{ib / ta * 100:.2f} %"

    if goodwill and goodwill > 0:
        data["商誉"] = f"{goodwill:.2f} 亿元"
        if ta and ta > 0:
            data["商誉占总资产"] = f"{goodwill / ta * 100:.2f} %"
        if eq and eq > 0:
            data["商誉占净资产"] = f"{goodwill / eq * 100:.2f} %"
    else:
        data["商誉"] = "无商誉（无商誉减值风险）"

    if money is not None and ib > 0 and ta and ta > 0:
        m_pct, ib_pct = money / ta * 100, ib / ta * 100
        if m_pct > 15 and ib_pct > 15:
            data["存贷双高预警"] = (f"⚠ 异常：货币资金占总资产 {m_pct:.1f}%，同时有息负债占总资产 "
                                  f"{ib_pct:.1f}%——存贷双高，建议核查货币资金真实性与受限情况")
        else:
            data["存贷双高预警"] = f"否（货币资金占比 {m_pct:.1f}%，有息负债占比 {ib_pct:.1f}%）"
    elif ib <= 0:
        data["存贷双高预警"] = "否（无有息负债）"

    if ar is not None:
        data["_ar_raw"] = _to_number(row.get('accounts_receiv'))
    if inventories is not None:
        data["_inv_raw"] = _to_number(row.get('inventories'))
    return data

def task_risk(ts_code):
    data = {}
    today = datetime.datetime.now().strftime('%Y%m%d')

    df = _fetch_safe(pro.fina_audit, "fina_audit", ts_code=ts_code, limit=3)
    if df is not None and not df.empty:
        try:
            df = df.sort_values("end_date", ascending=False)
        except Exception:
            pass
        r = df.iloc[0]
        res = str(safe_get(r, 'audit_result') or "").strip()
        if res and res != "N/A":
            data["审计报告期"] = safe_get(r, 'end_date')
            data["最近审计意见"] = res
            agency = safe_get(r, 'audit_agency')
            if agency not in (None, "N/A", ""):
                data["审计机构"] = agency
            fees = _to_number(r.get('audit_fees'))
            if fees:
                data["审计费用"] = f"{fees / 1e4:.1f} 万元"
            data["审计意见预警"] = ("否（标准无保留意见）" if "标准无保留" in res
                                 else f"⚠ 非标准无保留意见：{res} ——需重点核查财务质量")

    df = _fetch_safe(pro.pledge_stat, "pledge_stat", ts_code=ts_code, limit=2)
    if df is not None and not df.empty:
        try:
            df = df.sort_values("end_date", ascending=False)
        except Exception:
            pass
        r = df.iloc[0]
        ratio = _to_number(r.get('pledge_ratio'))
        if ratio is not None:
            data["质押统计日期"] = safe_get(r, 'end_date')
            data["股权质押比例"] = f"{ratio:.2f} %"
            data["股权质押预警"] = ("⚠ 质押比例偏高（>30%），关注大股东资金链与平仓风险"
                                  if ratio > 30 else "正常")
        cnt = _to_number(r.get('pledge_count'))
        if cnt is not None:
            data["质押笔数"] = f"{int(cnt)} 笔"

    df = _fetch_safe(pro.share_float, "share_float", ts_code=ts_code, limit=60)
    if df is not None and not df.empty:
        rows = []
        for i in range(len(df)):
            r = df.iloc[i]
            fd = str(safe_get(r, 'float_date') or "").strip()
            if not fd.isdigit() or fd < today:
                continue
            ratio = _to_number(r.get('float_ratio')) or 0
            holder = safe_get(r, 'holder_name')
            rows.append((fd, ratio, holder))
        if rows:
            rows.sort()
            lines = []
            for fd, ratio, holder in rows[:4]:
                nm = holder if holder not in (None, "N/A") else "—"
                lines.append(f"{fd} | 解禁比例 {ratio:.2f}% | {nm}")
            data["未来解禁计划"] = "\n    " + "\n    ".join(lines)
            data["未来解禁次数"] = f"{len(rows)} 次"
            if rows[0][1] > 10:
                data["解禁预警"] = f"⚠ 最近一次解禁比例 {rows[0][1]:.2f}%（>10%），短期抛压需关注"
        else:
            data["未来解禁计划"] = "近期无解禁安排"
    return data

def task_forward(ts_code):
    data = {}
    df = _fetch_safe(pro.forecast, "forecast", ts_code=ts_code, limit=2)
    if df is not None and not df.empty:
        try:
            df = df.sort_values("end_date", ascending=False)
        except Exception:
            pass
        r = df.iloc[0]
        data["业绩预告报告期"] = safe_get(r, 'end_date')
        tp = safe_get(r, 'type')
        if tp not in (None, "N/A", ""):
            data["业绩预告类型"] = tp
        lo, hi = _to_number(r.get('p_change_min')), _to_number(r.get('p_change_max'))
        if lo is not None:
            data["预告净利润变动"] = (f"{lo:.2f}%" if (hi is None or abs(hi - lo) < 1e-9)
                                  else f"{lo:.2f}% ~ {hi:.2f}%")
        nlo, nhi = _to_number(r.get('net_profit_min')), _to_number(r.get('net_profit_max'))
        if nlo is not None:
            data["预告净利润"] = (f"{nlo / 1e4:.2f} 亿元"
                               if (nhi is None or abs(nhi - nlo) < 1e-9)
                               else f"{nlo / 1e4:.2f} ~ {nhi / 1e4:.2f} 亿元")
        last = _to_number(r.get('last_parent_net'))
        if last:
            data["上年同期净利润"] = f"{last / 1e4:.2f} 亿元"
        sm = safe_get(r, 'summary')
        if sm not in (None, "N/A", ""):
            data["预告摘要"] = sm

    df2 = _fetch_safe(pro.express, "express", ts_code=ts_code, limit=2)
    if df2 is not None and not df2.empty:
        try:
            df2 = df2.sort_values("end_date", ascending=False)
        except Exception:
            pass
        r = df2.iloc[0]
        data["业绩快报报告期"] = safe_get(r, 'end_date')
        rev, ni = _yi(r.get('revenue')), _yi(r.get('n_income'))
        if rev is not None:
            data["快报营业收入"] = f"{rev:.2f} 亿元"
        if ni is not None:
            data["快报净利润"] = f"{ni:.2f} 亿元"
            last_np = _yi(r.get('yoy_net_profit'))
            if last_np:
                data["快报上年同期净利润"] = f"{last_np:.2f} 亿元"
                if abs(last_np) > 1e-9:
                    data["快报净利同比"] = f"{(ni - last_np) / abs(last_np) * 100:.2f} %"
        roe = _to_number(r.get('diluted_roe'))
        if roe is not None:
            data["快报摊薄ROE"] = f"{roe:.2f} %"
    return data

def task_capital(ts_code):
    data = {}
    df = _fetch_safe(pro.hk_hold, "hk_hold", ts_code=ts_code, limit=6)
    if df is not None and not df.empty:
        d = df.copy()
        if 'trade_date' in d.columns:
            d = d.sort_values('trade_date', ascending=False)
        r = d.iloc[0]
        ratio, vol = _to_number(r.get('ratio')), _to_number(r.get('vol'))
        if ratio is not None:
            data["北向数据日期"] = safe_get(r, 'trade_date')
            data["北向持股比例"] = f"{ratio:.2f} %"
        if vol is not None:
            data["北向持股数量"] = f"{vol / 1e4:.2f} 万股"
        if len(d) > 1:
            r_old = d.iloc[-1]
            r0 = _to_number(r_old.get('ratio'))
            if ratio is not None and r0 is not None:
                data["北向持股变化(区间)"] = (
                    f"{ratio - r0:+.2f} 个百分点"
                    f"（{safe_get(r_old, 'trade_date')} → {safe_get(r, 'trade_date')}）")

    df = _fetch_safe(pro.margin_detail, "margin_detail", ts_code=ts_code, limit=2)
    if df is not None and not df.empty:
        try:
            df = df.sort_values("trade_date", ascending=False)
        except Exception:
            pass
        r = df.iloc[0]
        rzye, rqye = _to_number(r.get('rzye')), _to_number(r.get('rqye'))
        if rzye is not None:
            data["两融数据日期"] = safe_get(r, 'trade_date')
            data["融资余额"] = f"{rzye / 1e8:.2f} 亿元"
        if rqye is not None:
            data["融券余额"] = (f"{rqye / 1e8:.2f} 亿元" if rqye >= 1e8
                             else f"{rqye / 1e4:.2f} 万元")

    df = _fetch_safe(pro.top10_floatholders, "top10_floatholders", ts_code=ts_code, limit=12)
    if df is not None and not df.empty:
        try:
            df = df.sort_values("end_date", ascending=False)
        except Exception:
            pass
        latest = str(safe_get(df.iloc[0], 'end_date') or "")
        names = []
        for i in range(len(df)):
            r = df.iloc[i]
            if str(safe_get(r, 'end_date') or "") != latest:
                continue
            nm = safe_get(r, 'holder_name')
            if nm in (None, "N/A", ""):
                continue
            ratio = safe_get(r, 'hold_float_ratio', unit="%")
            names.append(f"{nm}（{ratio}）")
            if len(names) >= 5:
                break
        if names:
            data[f"前五大流通股东（{latest}）"] = "、".join(names)

    bd = lx_svc.fetch_recent_events(ts_code, "block_deal", 5)
    if bd:
        lines = []
        for r in bd[:3]:
            dstr = str(r.get("date") or "")[:10]
            price = _to_number(r.get("tradingPrice"))
            amt_yuan = _to_number(r.get("tradingAmount"))
            vol_g = _to_number(r.get("tradingVolume"))
            disc = _to_number(r.get("discountRate"))
            if amt_yuan is None:
                continue
            p = f"{price:.2f}" if price is not None else "—"
            amt_wan = amt_yuan / 1e4
            vol_txt = f" | 量 {vol_g / 1e4:.2f} 万股" if vol_g is not None else ""
            disc_txt = f"{disc * 100:.2f}%" if disc is not None else "—"
            lines.append(f"{dstr} | 成交价 {p} 元 | 金额 {amt_wan:.2f} 万元{vol_txt} | 折价 {disc_txt}")
        if lines:
            data["近期大宗交易"] = "\n    " + "\n    ".join(lines)
    return data

def task_mgmt(ts_code):
    data = {}
    df = _fetch_safe(pro.repurchase, "repurchase", ts_code=ts_code, limit=12)
    if df is not None and not df.empty:
        done = []
        for i in range(len(df)):
            r = df.iloc[i]
            proc = str(safe_get(r, 'proc') or "")
            amt = _to_number(r.get('amount'))
            if not amt or ("实施" not in proc and "完成" not in proc):
                continue
            done.append((str(safe_get(r, 'end_date') or ""), amt, _to_number(r.get('vol'))))
        if done:
            total_amt = sum(x[1] for x in done)
            total_vol = sum(x[2] for x in done if x[2] is not None)
            data["已实施回购次数"] = f"{len(done)} 次"
            data["累计回购金额"] = f"{total_amt / 1e8:.2f} 亿元"
            if total_vol:
                data["累计回购股数"] = f"{total_vol / 1e4:.2f} 万股"
            if done[0][0]:
                data["最近回购日期"] = done[0][0]
        else:
            data["回购情况"] = "近期无已实施回购（仅预案或未开展）"

    df = _fetch_safe(pro.stk_rewards, "stk_rewards", ts_code=ts_code, limit=12)
    if df is not None and not df.empty:
        try:
            df = df.sort_values("end_date", ascending=False)
        except Exception:
            pass
        latest = str(safe_get(df.iloc[0], 'end_date') or "")
        tops = []
        for i in range(len(df)):
            r = df.iloc[i]
            if str(safe_get(r, 'end_date') or "") != latest:
                continue
            nm = safe_get(r, 'name')
            hv = _to_number(r.get('hold_vol'))
            if nm in (None, "N/A", "") or not hv:
                continue
            tops.append((hv, nm, str(safe_get(r, 'title') or "")))
        if tops:
            tops.sort(reverse=True)
            lines = [f"{nm}（{title or '—'}）：{hv / 1e4:,.2f} 万股" for hv, nm, title in tops[:5]]
            data[f"董监高持股（{latest}）"] = "\n    " + "\n    ".join(lines)
            data["董监高持股合计"] = f"{sum(t[0] for t in tops) / 1e4:,.2f} 万股"
    return data

def _fmt_num(v):
    if v in (None, ""):
        return "N/A"
    if _is_num(v):
        return f"{float(v):.2f}"
    return str(v)

def _ak_tech_ma(ts_code):
    data = {}
    try:
        code6, ex = _ak_symbol(ts_code)
        if ex == 'BJ':
            return data
        sym = ('sh' if ex == 'SH' else 'sz') + code6
        df = ak.stock_zh_a_daily(symbol=sym, adjust='qfq')
        if df is not None and len(df) >= 20:
            closes = df['close'].astype(float).values
            ma5 = float(closes[-5:].mean())
            ma20 = float(closes[-20:].mean())
            data["MA5"] = f"{ma5:.2f}"
            data["MA20"] = f"{ma20:.2f}"
            data["趋势信号"] = "多头排列" if ma5 > ma20 else "空头排列"
    except Exception as e:
        print(f"[ak] tech_ma 兜底失败: {e}")
    return data

def _get_comprehensive_data_parallel(ts_code: str, preference_id: str = None, groups: list = None,
                                     metrics_sink: dict = None):
    picked = resolve_data_groups(preference_id, groups)
    cache_key = f"{ts_code}::{'+'.join(picked)}"

    now = time.time()
    cached = DATA_CACHE.get(cache_key)
    if cached and now - cached['timestamp'] < CACHE_TTL:
        print(f"🚀 [Cache Hit] {ts_code} 组={'+'.join(picked)}")
        if metrics_sink is not None:
            metrics_sink.update(cached.get('metrics') or {})
            if cached.get('completeness'):
                metrics_sink["completeness"] = cached["completeness"]
        return cached['formatted_text']

    symbol = ts_code.split('.')[0]
    final_data = {}

    need = set(picked)
    base_tasks = {
        "future_realtime": (task_realtime, symbol),
        "future_daily": (task_daily_basic, ts_code),
        "future_valpct": (task_valuation_percentile, ts_code),
    }
    if need & {"quote"}:
        base_tasks["future_tech"] = (task_tech_ma, ts_code)
    if need & {"profitability", "growth", "cashflow", "multiyear", "comprehensive", "operations"}:
        base_tasks["future_fina"] = (task_fina_indicator, ts_code)
    if need & {"growth"}:
        base_tasks["future_income"] = (task_income, ts_code)
    if need & {"cashflow"}:
        base_tasks["future_cf"] = (task_cashflow, ts_code)
    if need & {"valuation", "dividend"}:
        base_tasks["future_dividend"] = (task_dividend, ts_code)
    for g in picked:
        tname = (DATA_GROUPS.get(g) or {}).get("task")
        if tname:
            fn = globals().get(tname)
            if callable(fn):
                base_tasks["grp_" + g] = (fn, ts_code)

    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {k: executor.submit(fn, arg) for k, (fn, arg) in base_tasks.items()}
            for k, fut in futures.items():
                try:
                    final_data.update(fut.result() or {})
                except Exception as e:
                    print(f"⚠️ [panel] 子任务 {k} 失败（已跳过）: {e}")

    except Exception as e:
        print(f"❌ Parallel Execution Error: {e}")
        print(traceback.format_exc())
        return f"数据获取服务暂时不可用: {e}"

    if final_data.get("股息率(TTM)") in (None, "N/A"):
        cd = final_data.get("_cash_div_raw")
        price = final_data.get("当前价格")
        if cd and price:
            try:
                pv = float(str(price).split()[0])
                if pv > 0:
                    final_data["股息率(TTM)"] = f"{cd / pv * 100:.2f} %（预案测算）"
            except (ValueError, AttributeError, TypeError):
                pass
    final_data.pop("_cash_div_raw", None)

    if final_data.get("扣非净利润") in (None, "N/A"):
        ded = final_data.get("_fina_deduct_profit")
        if ded and ded != "N/A":
            final_data["扣非净利润"] = ded
    final_data.pop("_fina_deduct_profit", None)

    ar_raw = final_data.get("_ar_raw")
    rev_raw = final_data.get("_revenue_raw")
    if ar_raw and rev_raw and rev_raw > 0:
        final_data["应收占营收比"] = f"{ar_raw / rev_raw * 100:.2f} %"
        inv_raw = final_data.get("_inv_raw")
        if inv_raw:
            final_data["应收+存货占营收比"] = f"{(ar_raw + inv_raw) / rev_raw * 100:.2f} %"
    final_data.pop("_ar_raw", None)
    final_data.pop("_inv_raw", None)
    final_data.pop("_revenue_raw", None)

    if not final_data:
        return "数据获取服务暂时不可用（本次未能拉取到任何行情/财务数据）"

    formatted_summary = _format_panel(ts_code, final_data, picked)

    panel_metrics = _panel_metrics_from_final(final_data)
    if metrics_sink is not None:
        metrics_sink.update(panel_metrics)
        metrics_sink["completeness"] = panel_completeness(final_data, picked)

    if final_data:
        DATA_CACHE[cache_key] = {
            "timestamp": now,
            "formatted_text": formatted_summary,
            "metrics": panel_metrics,
            "completeness": panel_completeness(final_data, picked),
        }
        _data_cache_trim()
    return formatted_summary

def task_lixinger(ts_code):
    try:
        bundle = lx_svc.gather_lixinger(ts_code)
    except Exception as e:
        print(f"⚠️ [Lixinger] gather 失败(已跳过): {e}")
        return {}
    out = {}
    out.update(bundle.get("overrides") or {})
    out.update(bundle.get("display") or {})
    return out

PREFERENCE_DATA_GROUPS = {
    "short_term":       ["quote", "technical", "moneyflow", "valuation", "capital",
                         "announcement", "hotrank", "dragon", "enrichment"],
    "swing":            ["quote", "technical", "moneyflow", "valuation", "growth",
                         "forward", "capital", "announcement", "hotrank", "dragon", "enrichment"],
    "long_term_value":  ["quote", "valuation", "profitability", "growth", "cashflow",
                         "multiyear", "dividend", "business", "operations",
                         "balance", "risk", "peer", "announcement", "enrichment"],
    "comprehensive":    ["quote", "technical", "moneyflow", "valuation", "profitability",
                         "growth", "cashflow", "multiyear", "dividend", "business",
                         "operations", "balance", "risk", "forward", "capital", "mgmt",
                         "holders", "peer", "announcement", "hotrank", "dragon", "enrichment"],
    "deep_tech":        ["quote", "technical", "moneyflow", "valuation", "growth",
                         "capital", "balance", "risk", "peer",
                         "announcement", "hotrank", "enrichment"],
    "deep_value":       ["quote", "valuation", "profitability", "growth", "cashflow",
                         "multiyear", "dividend", "business", "operations",
                         "balance", "risk", "forward", "capital", "mgmt", "holders", "peer",
                         "announcement", "enrichment"],
}

_BASE_GROUPS = ["quote", "valuation"]
_EXTRA_FIELDS = []

def _pref_groups_from_settings(preference_id: str):
    if not preference_id:
        return None
    try:
        import settings as _st
        for p in (_st.get_analysis_preferences() or []):
            if p.get("id") == preference_id:
                g = p.get("data_groups")
                if isinstance(g, list) and g:
                    return [x for x in g if x in DATA_GROUPS]
    except Exception:
        pass
    return None

def resolve_data_groups(preference_id: str = None, groups: list = None) -> list:
    if groups:
        picked = list(groups)
    else:
        picked = _pref_groups_from_settings(preference_id) \
            or list(PREFERENCE_DATA_GROUPS.get(preference_id) or _BASE_GROUPS)
    for g in _BASE_GROUPS:
        if g not in picked:
            picked.append(g)
    ordered = [g for g in DATA_GROUPS if g in picked]
    return ordered or list(DATA_GROUPS.keys())

def panel_completeness(final_data: dict, groups: list) -> dict:
    total = filled = 0
    per_group = []
    missing_groups = []
    for g in (groups or []):
        cfg = DATA_GROUPS.get(g)
        if not cfg:
            continue
        fields = list(cfg.get("fields") or [])
        for prefix in (cfg.get("dynamic_keys") or []):
            fields += [k for k in (final_data or {}) if str(k).startswith(prefix)]
        if cfg.get("dynamic_prefix"):
            fields += [k for k in (final_data or {}) if str(k).startswith(cfg["dynamic_prefix"])]
        seen = set()
        g_total = g_filled = 0
        missing_keys = []
        for key in fields:
            if key in seen:
                continue
            seen.add(key)
            g_total += 1
            if (final_data or {}).get(key, "N/A") not in (None, "", "N/A"):
                g_filled += 1
            elif len(missing_keys) < 4:
                missing_keys.append(key)
        if g_total:
            per_group.append({"title": cfg.get("title") or g,
                              "filled": g_filled, "total": g_total,
                              "pct": round(g_filled * 100 / g_total),
                              "missing": missing_keys})
            total += g_total
            filled += g_filled
            if g_filled == 0:
                missing_groups.append(cfg.get("title") or g)
    pct = round(filled * 100 / total) if total else 0
    return {"pct": pct, "filled": filled, "total": total,
            "groups": per_group, "missing_groups": missing_groups,
            "level": "good" if pct >= 90 else ("fair" if pct >= 70 else "poor")}

def _format_panel(ts_code: str, final_data: dict, groups: list) -> str:
    lines = [f"【股票数据面板: {ts_code}】"]
    for g in groups:
        cfg = DATA_GROUPS.get(g)
        if not cfg:
            continue
        fields = list(cfg.get("fields") or [])
        for prefix in (cfg.get("dynamic_keys") or []):
            fields += [k for k in final_data if str(k).startswith(prefix)]
        if cfg.get("dynamic_prefix"):
            fields += [k for k in final_data if str(k).startswith(cfg["dynamic_prefix"])]
        seen, body = set(), []
        for key in fields:
            if key in seen:
                continue
            seen.add(key)
            val = final_data.get(key, "N/A")
            if val in (None, "", "N/A"):
                continue
            body.append(f"{key}: {val}")
        if body:
            lines.append(f"\n--- {cfg['title']} ---")
            lines.extend(body)
    return "\n".join(lines) + "\n"

RANK_CACHE = {
    "hot_stocks": [],
    "hot_concepts": [],
    "hot_industries": [],
    "top_gainers": [],
    "timestamp": 0,
    "updated_at": 0,
}
RANK_CACHE_TTL = 3600
RANK_CACHE_TTL_OFFHOURS = 7200

_RANK_SCHEDULER_STARTED = False

LOCAL_HOT_CACHE = {"key": None, "items": [], "timestamp": 0}
LOCAL_HOT_TTL = 3600
LOCAL_HOT_DAYS = 7
LOCAL_HOT_LIMIT = 10

NEWS_CACHE = {
    "data": [],
    "timestamp": 0
}
NEWS_CACHE_TTL = 3600

def get_news_data_sync(src='gelonghui', limit=50):
    global NEWS_CACHE
    now = time.time()
    if NEWS_CACHE.get("data") is not None and (now - NEWS_CACHE["timestamp"] < NEWS_CACHE_TTL):
        return NEWS_CACHE["data"]

    try:
        sync_gelonghui_news()
    except Exception as e:
        print(f"⚠️ [News] 格隆汇同步失败: {type(e).__name__}: {e}")

    try:
        total, rows = db.list_news(limit=limit, offset=0)
        items = [_row_to_news_item(r) for r in rows]
    except Exception as e:
        print(f"⚠️ [News] 读取本地快讯失败: {e}")
        items = []

    NEWS_CACHE["data"] = items
    NEWS_CACHE["timestamp"] = now
    NEWS_CACHE["provider"] = "金融大数据"
    NEWS_CACHE["notice"] = ""
    print(f"📰 [News] 本地库返回 {len(items)} 条")
    return items

def invalidate_news_cache():
    NEWS_CACHE["timestamp"] = 0

GELONGHUI_BASE = "https://www.gelonghui.com/api/live-channels/all/lives/v4"
_NEWS_SCHEDULER_STARTED = False

def _clean_gelonghui_text(text):
    if not text:
        return ""
    t = str(text)
    t = t.replace("格隆汇", "")
    t = t.replace("格隆汇讯", "")
    t = re.sub(r'^\s*\d+月\d+[日号]?\s*[｜|]?\s*', '', t)
    t = re.sub(r'^[｜|]\s*', '', t)
    return t.strip()

def fetch_gelonghui_news(category='all', limit=50, timeout=25):
    ts = int(time.time() * 1000)
    url = f"{GELONGHUI_BASE}?category={category}&limit={int(limit)}&timestamp={ts}"
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }, timeout=timeout)
    except Exception as e:
        print(f"⚠️ [News] 格隆汇请求异常: {type(e).__name__}: {e}")
        return []
    try:
        j = resp.json()
    except Exception:
        print(f"⚠️ [News] 格隆汇响应非 JSON HTTP {resp.status_code}: {resp.text[:160]}")
        return []
    if j.get("statusCode") != 200:
        print(f"⚠️ [News] 格隆汇业务码异常 statusCode={j.get('statusCode')}")
        return []
    items = j.get("result") or []
    out = []
    for it in items:
        gid = it.get("id")
        if not gid:
            continue
        title = _clean_gelonghui_text(it.get("title") or "")
        content = _clean_gelonghui_text(it.get("content") or "")
        ct = int(it.get("createTimestamp") or 0)
        try:
            dt = datetime.datetime.fromtimestamp(ct) if ct else datetime.datetime.now()
        except Exception:
            dt = datetime.datetime.now()
        text = f"{title} {content}".strip()
        sentiment = analyze_sentiment_keywords(text)
        tags = extract_tags(text)
        ai_comment = generate_ai_comment(title, content, sentiment)
        out.append({
            "gid": gid,
            "category": category,
            "title": title,
            "content": content,
            "create_timestamp": ct,
            "news_date": dt.strftime("%Y-%m-%d"),
            "news_time": dt.strftime("%H:%M"),
            "important": is_important_news(title, content),
            "sentiment": sentiment,
            "tags": ",".join(tags) if tags else "",
            "ai_comment": ai_comment,
        })
    return out

def sync_gelonghui_news():
    imp = fetch_gelonghui_news('important', 50)
    alln = fetch_gelonghui_news('all', 50)
    by_id = {}
    for it in alln:
        by_id[it["gid"]] = it
    for it in imp:
        e = by_id.get(it["gid"])
        if e:
            e["important"] = True
        else:
            by_id[it["gid"]] = it
    rows = list(by_id.values())
    if rows:
        try:
            upserted = db.upsert_news(rows)
            print(f"📰 [News] 格隆汇同步入库 {upserted} 条（important={len(imp)}, all={len(alln)}）")
        except Exception as e:
            print(f"⚠️ [News] 入库失败: {type(e).__name__}: {e}")
    else:
        print("⚠️ [News] 格隆汇本次返回 0 条")
    return len(rows)

def _row_to_news_item(r):
    tags_raw = r.get("tags") or ""
    tags = [t for t in tags_raw.split(",") if t] if tags_raw else ["市场快讯"]
    return {
        "gid": int(r.get("gid") or 0),
        "time": (str(r.get("news_time") or "") or "")[:5],
        "date": str(r.get("news_date") or "") or "",
        "title": r.get("title") or "",
        "content": r.get("content") or "",
        "source": "",
        "sentiment": r.get("sentiment") or "neutral",
        "important": bool(r.get("important")),
        "tags": tags,
        "ai_comment": r.get("ai_comment") or "",
        "likes": int(r.get("likes") or 0),
        "views": int(r.get("views") or 0),
        "pinned": bool(r.get("pinned")),
    }

def start_news_scheduler(interval=3600):
    global _NEWS_SCHEDULER_STARTED
    if _NEWS_SCHEDULER_STARTED:
        return
    _NEWS_SCHEDULER_STARTED = True

    def _loop():
        while True:
            time.sleep(interval)
            try:
                sync_gelonghui_news()
            except Exception as e:
                print(f"⚠️ [News] 定时同步异常: {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"📰 [News] 定时同步已启动（每 {interval}s）")

def init_news():
    try:
        db.ensure_news_table()
    except Exception as e:
        print(f"⚠️ [News] 建表失败: {e}")
    try:
        sync_gelonghui_news()
    except Exception as e:
        print(f"⚠️ [News] 首同步失败: {e}")
    start_news_scheduler(3600)

def _fetch_news_real(src, limit):
    limit = int(limit)
    USE_DATAHUB_NEWS = getattr(config, "DATAHUB_NEWS_ENABLED", False)

    items = []
    providers = []
    notice = None

    end = datetime.datetime.now()
    start = end - datetime.timedelta(days=3)

    try:
        df, status = fetch_news_datahub(
            "major_news", src,
            start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"),
            limit=max(limit, 100),
        )
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                dt = str(row.get("datetime", "") or "")
                if " " in dt:
                    date_part, time_part = dt.split(" ", 1)
                else:
                    date_part, time_part = dt[:10], (dt[11:16] if len(dt) >= 16 else "")
                title = str(row.get("title", "") or "")
                content = str(row.get("content", "") or "")
                title = _derive_title(title, content)
                text = f"{title} {content}"
                sentiment = analyze_sentiment_keywords(text)
                items.append({
                    "time": time_part[:5],
                    "date": date_part,
                    "title": title,
                    "content": content,
                    "source": "datahub_major_news",
                    "sentiment": sentiment,
                    "important": is_important_news(title, content),
                    "tags": extract_tags(text),
                    "ai_comment": generate_ai_comment(title, content, sentiment),
                })
            providers.append("DATAHUB·major_news")
        elif status == "rate_limit":
            notice = "DATAHUB 新闻接口当前触发限频（40次/天），短讯已切换财联社实时快讯"
        elif status == "no_permission":
            notice = "DATAHUB 长篇通讯(major_news)未授权，已用财联社实时快讯"
        elif status == "disabled":
            notice = "未配置 DATAHUB 密钥，使用财联社实时快讯"
        elif status in ("error", "empty"):
            notice = "DATAHUB 新闻接口暂未返回数据（网络/网关异常或当日无通讯），已用财联社实时快讯"
    except Exception as e:
        print(f"⚠️ [News] DATAHUB major_news 异常: {type(e).__name__}: {e}")
        if not notice:
            notice = "DATAHUB 新闻接口暂不可用（网络/网关异常），已用财联社实时快讯"

    if USE_DATAHUB_NEWS and not providers:
        try:
            df2, status2 = fetch_news_datahub(
                "news", src,
                start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"),
                limit=max(limit, 100),
            )
            if df2 is not None and not df2.empty:
                for _, row in df2.iterrows():
                    dt = str(row.get("datetime", "") or "")
                    date_part, time_part = (dt.split(" ", 1) if " " in dt else (dt[:10], dt[11:16] if len(dt) >= 16 else ""))
                    title = _derive_title(str(row.get("title", "") or ""), str(row.get("content", "") or ""))
                    content = str(row.get("content", "") or "")
                    text = f"{title} {content}"
                    sentiment = analyze_sentiment_keywords(text)
                    items.append({
                        "time": time_part[:5], "date": date_part,
                        "title": title, "content": content, "source": "datahub_news",
                        "sentiment": sentiment,
                        "important": is_important_news(title, content),
                        "tags": extract_tags(text),
                        "ai_comment": generate_ai_comment(title, content, sentiment),
                    })
                providers.append("DATAHUB·news")
        except Exception as e:
            print(f"⚠️ [News] DATAHUB news 异常: {type(e).__name__}: {e}")

    try:
        df3 = ak.stock_info_global_cls()
        if df3 is not None and not df3.empty:
            for _, row in df3.iterrows():
                title = str(row.get("标题", "") or "")
                content = str(row.get("内容", "") or "")
                title = _derive_title(title, content)
                d = str(row.get("发布日期", "") or "")
                t = str(row.get("发布时间", "") or "")
                text = f"{title} {content}"
                sentiment = analyze_sentiment_keywords(text)
                items.append({
                    "time": t[:5], "date": d, "title": title, "content": content,
                    "source": "cls", "sentiment": sentiment,
                    "important": is_important_news(title, content),
                    "tags": extract_tags(text),
                    "ai_comment": generate_ai_comment(title, content, sentiment),
                })
            providers.append("财联社")
    except Exception as e:
        print(f"⚠️ [News] AKShare 财联社异常: {type(e).__name__}: {e}")

    items = _dedupe_news(items)
    items.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    provider = "金融大数据" if providers else "none"
    return items[:limit], provider, notice

def _derive_title(title, content):
    title = (title or "").strip()
    if title:
        return title
    c = (content or "").strip()
    if not c:
        return ""
    m = re.match(r'^财联社\d+月\d+日(上午|下午|早间|晚间)?电[，,]?\s*', c)
    if m:
        c = c[m.end():].strip()
    return c[:40]

def _dedupe_news(items):
    seen = set()
    out = []
    for it in items:
        key = (it.get("date"), it.get("time"), it.get("title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

def get_news_akshare_fallback(limit=30):
    items, _, _ = _fetch_news_real("cls", limit)
    return items

def extract_tags(text):
    tags = []
    concept_keywords = ['AI', '人工智能', '芯片', '半导体', '新能源', '光伏', '风电', '电动车', '锂电池', '固态电池', '机器人', '人形机器人', '白酒', '消费', '医药', '医疗', '金融', '地产', '基建', '军工', '数字经济', '算力', '数据中心']

    for kw in concept_keywords:
        if kw in text:
            tags.append(kw)

    return tags[:3] if tags else ['市场快讯']

def is_important_news(title, content):
    important_keywords = ['重大', '突发', '重磅', '央行', '国务院', '证监会', '工信部', '超预期', '涨停', '跌停', '万亿', '千亿', '里程碑']
    text = title + ' ' + content
    return any(kw in text for kw in important_keywords)

def generate_ai_comment(title, content, sentiment):
    if sentiment == 'bull':
        return "本地关键词判定为偏正面消息（含利好/增长/回购类词汇）。具体影响请以公告原文为准。"
    elif sentiment == 'bear':
        return "本地关键词判定为偏负面消息（含利空/下滑/减持类词汇）。具体影响请以公告原文为准。"
    else:
        return "本地关键词判定为中性消息，未命中明显的利好/利空词汇。"

def fetch_latest_dragon_tiger(max_back_days=7, page_size=100):
    now = _now_shanghai()
    for i in range(max(1, int(max_back_days))):
        day = (now - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            rows = get_client().get("cn/company/trading-abnormal",
                                    date=day, pageIndex=0,
                                    pageSize=max(1, min(int(page_size), 100)))
        except LixingerError:
            rows = None
        except Exception as e:
            print(f"⚠️ [Lixinger] 当日龙虎榜请求异常 {day}: {type(e).__name__}: {e}")
            rows = None
        if rows:
            return day, rows
    return None, None

_THS_BRAND_RE = re.compile(r"同花顺(?:iFinD|iFind|数据|财经|资讯)?")

def _parse_ths_concept(val):
    if val is None:
        return []
    if isinstance(val, list):
        raw = [str(x) for x in val]
    elif isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                raw = [str(x) for x in obj]
            else:
                raw = [s]
        except Exception:
            raw = [p.strip() for p in re.split(r"[,;；\s]+", s) if p.strip()]
    else:
        return []
    out = []
    for c in raw:
        c = _THS_BRAND_RE.sub("", str(c)).strip(" 、,，")
        if c and c not in out:
            out.append(c)
    return out

def _fmt_ths_td(s):
    if not s:
        return ""
    s = str(s).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return s

def _clean_reason(v):
    s = str(v or "").strip()
    if s.lower() in ("nan", "none", "null"):
        return ""
    s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    s = _THS_BRAND_RE.sub("", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def fetch_ths_hot(market, trade_date=None, is_new="N", limit=2000, timeout=30):
    params = {"market": market, "is_new": is_new, "limit": limit}
    if trade_date:
        params["trade_date"] = trade_date
    df, st = fetch_datahub("ths_hot", params, timeout=timeout)
    if df is None or getattr(df, "empty", True):
        return None, st
    return df.to_dict("records"), st

def _collect_ths_reasons(rows):
    pool = {}
    for r in rows or []:
        code = str(r.get("ts_code") or "").strip()
        if not code or code in pool:
            continue
        rs = _clean_reason(r.get("rank_reason"))
        if rs:
            pool[code] = rs
    return pool

def _ths_order(row):
    try:
        rk = int(row.get("rank") or 0)
    except Exception:
        rk = 0
    return (rk if rk else 9999, -(_safe_float(row.get("hot")) or 0.0))

_THS_DEAD_UNTIL = 0.0

def _fetch_ths_snapshot(market, timeout=45, retries=2):
    global _THS_DEAD_UNTIL
    if time.time() < _THS_DEAD_UNTIL:
        return [], ""

    td = _latest_trade_date_datahub()

    def _only_latest_date(rs):
        dates = sorted({str(r.get("trade_date") or "") for r in rs if r.get("trade_date")},
                       reverse=True)
        if not dates:
            return [], ""
        latest = dates[0]
        return [r for r in rs if str(r.get("trade_date")) == latest], latest

    for attempt in range(retries + 1):
        rows, st = fetch_ths_hot(market, trade_date=td, is_new="N", timeout=timeout)
        if rows and st == "ok":
            return rows, td
        if attempt < retries:
            time.sleep(1.0 * (attempt + 1))

    rows, st = fetch_ths_hot(market, is_new="N", timeout=timeout)
    if rows and st == "ok":
        picked, latest = _only_latest_date(rows)
        if picked:
            return picked, latest

    _THS_DEAD_UNTIL = time.time() + 3600
    return [], td

def _fetch_fuyao_hot_rows(top_n=30):
    try:
        import fuyao_client
        rows, err = fuyao_client.hot_stock_list()
        if err or not rows:
            return []
        now = time.strftime("%Y-%m-%d %H:%M:00")
        td = _latest_trade_date_datahub()

        px = {}
        try:
            from dataservice.market import _market_pulse
            pdf = _market_pulse(td)
            if pdf is not None and not pdf.empty:
                for code, r in pdf.iterrows():
                    px[code] = (r.get("close"), r.get("pct_chg"))
        except Exception:
            pass

        out = []
        for it in rows[:top_n]:
            code = str(it.get("ts_code") or "").strip()
            close, pct = px.get(code, (None, None))
            out.append({
                "ts_code": code,
                "ts_name": it.get("name") or "",
                "hot": it.get("heat") or 0,
                "rank": it.get("rank"),
                "rank_time": now,
                "trade_date": td,
                "current_price": close,
                "pct_change": pct,
                "rank_reason": "",
                "concept": "",
            })
        return out
    except Exception as e:
        print(f"⚠️ [Rank] 伏尧热榜回退失败: {type(e).__name__}: {e}")
        return []

def _ths_batch_key(row):
    return str(row.get("rank_time") or "")[:13]

def _latest_snapshot_slice(rows, top_n=20):
    if not rows:
        return []

    by_ts = {}
    for r in rows:
        by_ts.setdefault(str(r.get("rank_time") or ""), []).append(r)
    latest_ts = max(by_ts.keys())
    if len(by_ts[latest_ts]) >= top_n:
        out, seen = [], set()
        for r in sorted(by_ts[latest_ts], key=_ths_order):
            code = str(r.get("ts_code") or "").strip()
            if code and code not in seen:
                seen.add(code)
                out.append(r)
        return out[:top_n]

    by_batch = {}
    for r in rows:
        by_batch.setdefault(_ths_batch_key(r), []).append(r)

    out, seen = [], set()
    for bk in sorted(by_batch.keys(), reverse=True):
        newest = {}
        for r in by_batch[bk]:
            code = str(r.get("ts_code") or "").strip()
            if not code:
                continue
            prev = newest.get(code)
            if prev is None or str(r.get("rank_time") or "") > str(prev.get("rank_time") or ""):
                newest[code] = r
        for r in sorted(newest.values(), key=_ths_order):
            code = str(r.get("ts_code") or "").strip()
            if code in seen:
                continue
            seen.add(code)
            out.append(r)
        if len(out) >= top_n:
            break
    return out[:top_n]

def _build_ths_board(rows, top_n=20):
    picked = _latest_snapshot_slice(rows, top_n)
    if not picked:
        return []
    max_hot = max((_safe_float(p.get("hot")) or 0.0 for p in picked), default=0.0) or 1.0
    out = []
    for p in picked:
        name = str(p.get("ts_name") or "").strip()
        if not name:
            continue
        pct = _safe_float(p.get("pct_change"))
        hot = _safe_float(p.get("hot")) or 0.0
        try:
            rk = int(p.get("rank") or 0)
        except Exception:
            rk = 0
        out.append({
            "name": name,
            "code": str(p.get("ts_code") or "").strip(),
            "rank": rk,
            "hot": hot,
            "heat": round(hot / max_hot * 100, 1),
            "change": (f"{pct:.2f}" if pct is not None else "--"),
            "reason": _clean_reason(p.get("rank_reason")),
        })
    return out

def get_market_rank_data_sync():
    global RANK_CACHE
    now = time.time()
    if RANK_CACHE["hot_stocks"] and (now - RANK_CACHE["timestamp"] < RANK_CACHE_TTL):
        return RANK_CACHE
    if RANK_CACHE["hot_stocks"] and not is_trading_time():
        if now - RANK_CACHE["timestamp"] < RANK_CACHE_TTL_OFFHOURS:
            return RANK_CACHE

    data = {"hot_stocks": [], "hot_concepts": [], "hot_industries": [], "top_gainers": []}

    trade_date = _latest_trade_date_datahub()

    srows, td_used = _fetch_ths_snapshot("热股")
    rank_src = "ths"
    if not srows:
        srows = _fetch_fuyao_hot_rows()
        rank_src = "fuyao"
        if srows:
            print(f"ℹ️ [Rank] THS 热榜不可用，已切换伏尧热股榜（{len(srows)} 条）")
    if srows:
        reason_pool = _collect_ths_reasons(srows)
        picked = _latest_snapshot_slice(srows, 20)
        if picked:
            max_hot = max((_safe_float(p.get("hot")) or 0.0 for p in picked), default=0.0) or 1.0
            for i, it in enumerate(picked):
                code = str(it.get("ts_code") or "").strip()
                name = str(it.get("ts_name") or "").strip() or code
                pct = _safe_float(it.get("pct_change"))
                pf = _safe_float(it.get("current_price"))
                hot = _safe_float(it.get("hot")) or 0.0
                data["hot_stocks"].append({
                    "rank": i + 1, "code": code, "name": name,
                    "price": (f"{pf:.2f}" if (pf is not None and pf != 0) else "--"),
                    "change": (f"{pct:.2f}" if pct is not None else "--"),
                    "pct": pct if pct is not None else 0.0,
                    "heat": round(hot / max_hot * 100, 1),
                    "hot_raw": hot,
                    "net_amount": (f"{pct:+.2f}%" if pct is not None else "--"),
                    "org_amount": "--",
                    "concept": _parse_ths_concept(it.get("concept")),
                    "reason": reason_pool.get(code) or _clean_reason(it.get("rank_reason")),
                    "last_date": _fmt_ths_td(it.get("trade_date") or td_used),
                    "rank_time": str(it.get("rank_time") or ""),
                })

    gain = sorted([s for s in data["hot_stocks"] if s.get("change") != "--"],
                  key=lambda x: -float(x.get("pct") or 0))[:10]
    for s in gain:
        data["top_gainers"].append({
            "code": s["code"], "name": s["name"],
            "price": s["price"], "change": s["change"], "pct": s["pct"],
            "heat": s["heat"], "net_amount": s["net_amount"],
        })

    crows, _ = _fetch_ths_snapshot("概念板块")
    data["hot_concepts"] = _build_ths_board(crows, 10)

    irows, itd = _fetch_ths_snapshot("行业板块")
    data["hot_industries"] = _build_ths_board(irows, 10)

    data["basis"] = rank_src
    td = (data["hot_stocks"][0]["last_date"] if data["hot_stocks"]
          else _fmt_ths_td(td_used or itd or trade_date))
    data["trade_date"] = td

    if data["hot_stocks"] or data["hot_concepts"] or data["hot_industries"]:
        RANK_CACHE.update(data)
        RANK_CACHE["timestamp"] = now
        RANK_CACHE["updated_at"] = now
        return RANK_CACHE

    print(f"⚠️ [Rank] THS 热榜无数据，返回旧缓存/空")
    return RANK_CACHE

def get_local_hot_analysis(days: int = LOCAL_HOT_DAYS, limit: int = LOCAL_HOT_LIMIT,
                           force: bool = False):
    global LOCAL_HOT_CACHE
    now = time.time()
    cache_key = (days, limit)
    if (not force) and LOCAL_HOT_CACHE["items"] and LOCAL_HOT_CACHE["key"] == cache_key \
            and (now - LOCAL_HOT_CACHE["timestamp"] < LOCAL_HOT_TTL):
        return list(LOCAL_HOT_CACHE["items"])
    try:
        rows = db.get_hot_analysis_stocks(days=days, limit=limit)
    except Exception as e:
        print(f"⚠️ [LocalHot] 查询失败，沿用旧缓存: {e}")
        return list(LOCAL_HOT_CACHE["items"])
    items = []
    for i, r in enumerate(rows or []):
        items.append({
            "rank": i + 1,
            "code": r.get("stock_code") or "",
            "name": r.get("stock_name") or r.get("stock_code") or "",
            "cnt": int(r.get("cnt") or 0),
            "last_at": r.get("last_at") or "",
        })
    LOCAL_HOT_CACHE["key"] = cache_key
    LOCAL_HOT_CACHE["items"] = items
    LOCAL_HOT_CACHE["timestamp"] = now
    return list(items)

def start_rank_scheduler(interval: int = 3600):
    global _RANK_SCHEDULER_STARTED
    if _RANK_SCHEDULER_STARTED:
        return
    _RANK_SCHEDULER_STARTED = True

    def _loop():
        _last_local = 0
        while True:
            try:
                now = time.time()
                if is_trading_time():
                    get_market_rank_data_sync()
                elif RANK_CACHE["hot_stocks"]:
                    if now - RANK_CACHE["timestamp"] >= RANK_CACHE_TTL_OFFHOURS:
                        get_market_rank_data_sync()
                if now - _last_local >= interval:
                    get_local_hot_analysis(force=True)
                    _last_local = now
            except Exception as e:
                print(f"⚠️ [Rank] 定时刷新异常: {e}")
            time.sleep(300)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("📈 [Rank] 定时刷新已启动（外部热榜：交易时间每小时；本站热门分析：每小时）")

def init_rank():
    try:
        get_market_rank_data_sync()
    except Exception as e:
        print(f"⚠️ [Rank] 首次拉取失败: {e}")
    start_rank_scheduler(3600)

_ALERT_METRIC_FIELD = {
    "total_mv": "total_mv",
    "pe_ttm": "pe_ttm",
    "pb": "pb",
    "pb_y5": "pb.y5.cvpos",
    "price": "close",
    "pct_chg": "pct_chg",
}

_ALERT_LOCAL_METRICS = {"val_low"}

_ALERT_SCHEDULER_STARTED = False

def _fetch_alert_values(ts_code):
    out = {"total_mv": None, "pe_ttm": None, "pb": None, "pb_y5": None,
           "price": None, "pct_chg": None}

    try:
        rows = lx_svc.fetch_candlestick(ts_code, days=_WATCH_KLINE_DAYS, fq_type="lxr_fc_rights")
        if rows:
            last = sorted(rows, key=lambda r: str(r.get("date") or ""))[-1]
            out["price"] = _safe_float(last.get("close"))
            chg = _safe_float(last.get("change"))
            out["pct_chg"] = (chg * 100) if chg is not None else None
    except Exception as e:
        print(f"⚠️ [Alert] K线拉值失败 {ts_code}: {type(e).__name__}: {e}")

    try:
        r = lx_svc.fetch_fundamental(ts_code, metrics=_WATCH_FUND_METRICS)
        if r:
            pe = _safe_float(r.get("pe_ttm"))
            out["pe_ttm"] = pe if (pe is not None and pe > 0) else None
            mc = _safe_float(r.get("mc"))
            out["total_mv"] = (mc / 1e8) if mc else None
            pb = _safe_float(r.get("pb"))
            out["pb"] = pb if (pb is not None and pb > 0) else None
            cv = _safe_float(r.get("pb.y5.cvpos"))
            out["pb_y5"] = (cv * 100) if cv is not None else None
    except Exception as e:
        print(f"⚠️ [Alert] 估值拉值失败 {ts_code}: {type(e).__name__}: {e}")

    return out

def _fetch_alert_value(ts_code, metric):
    return _fetch_alert_values(ts_code).get(metric)

def _alert_hit(operator, value, threshold, threshold2):
    if value is None:
        return False
    if operator == "gte":
        return value >= threshold
    if operator == "lte":
        return value <= threshold
    if operator == "between":
        return threshold <= value <= threshold2
    return False

_LOCAL_METRIC_CACHE = {}

def _local_metric_value(alert):
    key = (alert.get("user_id"), alert.get("ts_code"))
    if key in _LOCAL_METRIC_CACHE:
        return _LOCAL_METRIC_CACHE[key]
    try:
        band = db.get_latest_valuation_band(alert.get("user_id"), alert.get("ts_code"))
    except Exception as e:
        print(f"⚠️ [Alert] 读研报估值失败 {key}: {e}")
        band = {}
    if band:
        lo = _safe_float(band.get("val_low"))
        band = band if (lo is not None and lo > 0) else {}
    _LOCAL_METRIC_CACHE[key] = band
    return band

def evaluate_alerts_once():
    try:
        alerts = db.list_all_enabled_alerts()
    except Exception as e:
        print(f"⚠️ [Alert] 拉取提醒规则失败: {e}")
        return
    if not alerts:
        return
    _LOCAL_METRIC_CACHE.clear()

    disc_alerts = [a for a in alerts if (a.get("metric") or "") == "disclosure"]
    if disc_alerts:
        try:
            evaluate_disclosure_alerts(disc_alerts)
        except Exception as e:
            print(f"⚠️ [Alert] 披露提醒评估异常: {e}")
    alerts = [a for a in alerts if (a.get("metric") or "") != "disclosure"]
    if not alerts:
        return

    todo_codes = sorted({a["ts_code"] for a in alerts if a.get("ts_code")})
    values = {}
    for tsc in todo_codes:
        try:
            vals = _fetch_alert_values(tsc)
        except Exception as e:
            print(f"⚠️ [Alert] 拉值失败 {tsc}: {type(e).__name__}: {e}")
            vals = {}
        for metric in _ALERT_METRIC_FIELD:
            values[(tsc, metric)] = vals.get(metric)

    for a in alerts:
        metric = a.get("metric") or "total_mv"
        if metric in _ALERT_LOCAL_METRICS:
            band = _local_metric_value(a)
            if not band:
                continue
            cur_mv = values.get((a["ts_code"], "total_mv"))
            try:
                db.update_alert(a["id"], a["user_id"], last_value=cur_mv)
            except Exception:
                pass
            if cur_mv is not None and cur_mv <= band.get("val_low"):
                try:
                    db.update_alert(a["id"], a["user_id"], triggered=1,
                                    triggered_at=db._now(), last_value=cur_mv)
                    print(f"🔔 [Alert] 触发提醒 user={a['user_id']} {a['stock_name']}({a['ts_code']}) "
                          f"总市值 {cur_mv:.0f}亿 已跌破研报合理下限 "
                          f"{band.get('val_low'):.0f}亿（研报日 {band.get('analysis_date')}）")
                except Exception as e:
                    print(f"⚠️ [Alert] 写触发状态失败: {e}")
            continue
        val = values.get((a["ts_code"], metric))
        try:
            db.update_alert(a["id"], a["user_id"], last_value=val)
        except Exception:
            pass
        if _alert_hit(a.get("operator"), val, float(a.get("threshold") or 0),
                      float(a.get("threshold2")) if a.get("threshold2") is not None else None):
            try:
                db.update_alert(a["id"], a["user_id"], triggered=1,
                                triggered_at=db._now(), last_value=val)
                print(f"🔔 [Alert] 触发提醒 user={a['user_id']} {a['stock_name']}({a['ts_code']}) "
                      f"{metric}={val}")
            except Exception as e:
                print(f"⚠️ [Alert] 写触发状态失败: {e}")

def start_alert_scheduler(interval=3600):
    global _ALERT_SCHEDULER_STARTED
    if _ALERT_SCHEDULER_STARTED:
        return
    _ALERT_SCHEDULER_STARTED = True

    def _loop():
        _last = 0.0
        while True:
            try:
                now = time.time()
                if is_trading_time() and now - _last >= interval:
                    evaluate_alerts_once()
                    _last = now
            except Exception as e:
                print(f"⚠️ [Alert] 定时评估异常: {e}")
            time.sleep(300)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("🔔 [Alert] 提醒定时评估已启动（交易时间每小时）")

def init_alerts():
    try:
        db.ensure_watch_alerts_table()
    except Exception as e:
        print(f"⚠️ [Alert] 建表失败: {e}")
    start_alert_scheduler(3600)

_DISCLOSURE_LOCK = threading.Lock()
_DISCLOSURE_SYNC_TS = {"last": 0.0}

def _disc_str8(v):
    s = "" if v is None else str(v).strip()
    return s if len(s) == 8 and s.isdigit() else ""

def _report_periods_ahead(n=2):
    today = datetime.date.today()
    out = []
    for y in (today.year, today.year + 1):
        for md in ("0331", "0630", "0930", "1231"):
            d = datetime.date(y, int(md[:2]), int(md[2:]))
            if d >= today:
                out.append(f"{y}{md}")
    return out[:max(1, int(n))]

def _report_periods_around(before=1, ahead=2):
    today = datetime.date.today()
    all_p = []
    for y in (today.year - 1, today.year, today.year + 1):
        for md in ("0331", "0630", "0930", "1231"):
            all_p.append(f"{y}{md}")
    future = [p for p in all_p if p >= today.strftime("%Y%m%d")]
    cur_idx = all_p.index(future[0]) if future else len(all_p)
    out = all_p[max(0, cur_idx - max(0, int(before))): cur_idx + max(0, int(ahead))]
    return out

def sync_disclosure_watchlist():
    try:
        codes = db.list_distinct_watch_codes()
    except Exception as e:
        print(f"⚠️ [Disclosure] 自选股列表读取失败: {e}")
        return 0
    if not codes:
        return 0
    names = {}
    try:
        names = {r["ts_code"]: (r.get("name") or "") for r in (db.list_all_stock_basics() or [])}
    except Exception:
        pass
    ok = 0
    for tsc in codes:
        try:
            rows = fetch_disclosure_rows(ts_code=tsc)
            if rows:
                for r in rows:
                    r["stock_name"] = names.get(tsc, "")
                db.upsert_disclosure_rows(rows)
                ok += 1
        except Exception as e:
            print(f"⚠️ [Disclosure] 同步失败 {tsc}: {type(e).__name__}: {e}")
    print(f"📅 [Disclosure] 自选股披露计划同步 {ok}/{len(codes)} 只")
    return ok

def sync_disclosure_market_periods():
    total = 0
    for period in _report_periods_around(before=1, ahead=2):
        try:
            rows = fetch_disclosure_rows(end_date=period)
            if not rows:
                continue
            db.upsert_disclosure_rows(rows)
            total += len(rows)
            print(f"📅 [Disclosure] 报告期 {period} 全市场同步 {len(rows)} 行")
        except Exception as e:
            print(f"⚠️ [Disclosure] 报告期 {period} 同步失败: {type(e).__name__}: {e}")
    return total

def disclosure_sync_once():
    with _DISCLOSURE_LOCK:
        try:
            db.ensure_disclosure_table()
        except Exception as e:
            print(f"⚠️ [Disclosure] 建表失败: {e}")
            return
        sync_disclosure_watchlist()
        sync_disclosure_market_periods()
        _DISCLOSURE_SYNC_TS["last"] = time.time()

def start_disclosure_scheduler(interval=6 * 3600, first_delay=90):
    global _DISCLOSURE_SCHED_STARTED
    if _DISCLOSURE_SCHED_STARTED:
        return
    _DISCLOSURE_SCHED_STARTED = True

    def _loop():
        time.sleep(max(30, int(first_delay)))
        while True:
            try:
                disclosure_sync_once()
            except Exception as e:
                print(f"⚠️ [Disclosure] 同步轮异常: {e}")
            time.sleep(max(600, int(interval)))

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("📅 [Disclosure] 披露计划定时同步已启动（每 6 小时）")

_DISCLOSURE_SCHED_STARTED = False

def get_disclosure_days_until(ts_code):
    row = None
    try:
        row = db.get_next_disclosure(ts_code)
    except Exception as e:
        print(f"⚠️ [Disclosure] 读取失败 {ts_code}: {e}")
    if not row:
        try:
            rows = fetch_disclosure_rows(ts_code=ts_code)
            if rows:
                db.upsert_disclosure_rows(rows)
                row = db.get_next_disclosure(ts_code)
        except Exception as e:
            print(f"⚠️ [Disclosure] 回源失败 {ts_code}: {type(e).__name__}: {e}")
    if not row:
        return None, None
    pre = _disc_str8(row.get("pre_date"))
    if not pre:
        return None, None
    try:
        d = datetime.datetime.strptime(pre, "%Y%m%d").date()
    except ValueError:
        return None, None
    return pre, (d - datetime.date.today()).days

def evaluate_disclosure_alerts(alerts):
    hit = 0
    for a in alerts:
        pre, days = get_disclosure_days_until(a.get("ts_code"))
        if days is None:
            continue
        try:
            thr = int(float(a.get("threshold") or 0))
        except (TypeError, ValueError):
            continue
        val = float(days)
        try:
            db.update_alert(a["id"], a["user_id"], last_value=val)
        except Exception:
            pass
        if 0 <= days <= max(1, min(thr, 60)):
            try:
                db.update_alert(a["id"], a["user_id"], triggered=1,
                                triggered_at=db._now(), last_value=val)
                hit += 1
                print(f"🔔 [Alert] 财报提醒触发 user={a['user_id']} {a.get('stock_name')}({a.get('ts_code')}) "
                      f"距披露 {days} 天（{pre}）")
            except Exception as e:
                print(f"⚠️ [Alert] 写触发状态失败: {e}")
    return hit

def init_disclosure_sync():
    try:
        db.ensure_disclosure_table()
    except Exception as e:
        print(f"⚠️ [Disclosure] 建表失败: {e}")
    start_disclosure_scheduler()

async def get_stock_code(keyword: str):
    return await run_in_threadpool(_get_stock_code_sync, keyword)

def _panel_metrics_from_final(final_data: dict) -> dict:
    def _num(v):
        if v in (None, "N/A", ""):
            return None
        s = str(v).replace(",", "").strip()
        m = re.match(r"^-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        try:
            return float(m.group(0))
        except ValueError:
            return None

    out = {}
    for key, out_key in (("当前价格", "price_now"), ("PE(TTM)", "pe_ttm_now"),
                         ("PB(市净率)", "pb_now"), ("总市值", "mc_now")):
        v = _num(final_data.get(key))
        if v is not None:
            out[out_key] = v
    return out

async def get_stock_data_summary(ts_code: str, preference_id: str = None, groups: list = None,
                                 metrics_sink: dict = None):
    return await run_in_threadpool(
        lambda: _get_comprehensive_data_parallel(ts_code, preference_id, groups, metrics_sink)
    )

async def get_market_rank_data():
    return await run_in_threadpool(get_market_rank_data_sync)

async def get_news_data(src='eastmoney', limit=50):
    return await run_in_threadpool(get_news_data_sync, src, limit)

async def get_opportunities_data():
    return await run_in_threadpool(get_opportunities_data_sync)

async def get_risk_data():
    return await run_in_threadpool(get_risk_data_sync)
