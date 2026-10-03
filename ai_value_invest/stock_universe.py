import asyncio
import datetime
import traceback

try:
    import akshare as ak
except Exception:
    ak = None

from data_source import get_pro
from db import upsert_stocks

_SYNC_STATE = {
    "running": False,
    "message": "尚未同步",
    "a": 0,
    "hk": 0,
    "total": 0,
    "error": None,
    "updated_at": None,
}

def fetch_a_stocks():
    rows = []
    try:
        pro = get_pro()
        df = pro.stock_basic(exchange="", list_status="L",
                             fields="ts_code,symbol,name,exchange,list_status")
        if df is not None and len(df):
            for _, r in df.iterrows():
                rows.append((str(r["ts_code"]), str(r["symbol"]), str(r["name"]),
                             str(r["exchange"]), str(r["list_status"])))
            return rows
    except Exception as e:
        print(f"[stock_universe] A股 proxy 拉取失败，回退 AKShare: {e}")
    if ak is not None:
        try:
            df = ak.stock_info_a_code_name()
            for _, r in df.iterrows():
                code = str(r["code"]).zfill(6)
                ts = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
                rows.append((ts, code, str(r["name"]), "SH" if code.startswith("6") else "SZ", "L"))
            return rows
        except Exception as e:
            print(f"[stock_universe] A股 AKShare 回退失败: {e}")
    return rows

def fetch_hk_stocks():
    rows = []
    if ak is not None:
        try:
            df = ak.stock_hk_spot_em()
            for _, r in df.iterrows():
                code = str(r["代码"]).zfill(5)
                ts = f"{code}.HK"
                rows.append((ts, code, str(r["名称"]), "HK", "L"))
            return rows
        except Exception as e:
            print(f"[stock_universe] 港股 AKShare 拉取失败: {e}")
    return rows

def sync_stock_universe():
    a = fetch_a_stocks()
    hk = fetch_hk_stocks()
    a_rows = [{"code": c, "ts_code": t, "name": n, "market": "A", "exchange": ex, "list_status": ls}
              for (t, c, n, ex, ls) in a]
    hk_rows = [{"code": c, "ts_code": t, "name": n, "market": "HK", "exchange": ex, "list_status": ls}
               for (t, c, n, ex, ls) in hk]
    upsert_stocks(a_rows)
    upsert_stocks(hk_rows)
    return {"a": len(a_rows), "hk": len(hk_rows), "total": len(a_rows) + len(hk_rows), "error": None}

async def _worker():
    _SYNC_STATE["running"] = True
    _SYNC_STATE["message"] = "同步中..."
    _SYNC_STATE["error"] = None
    try:
        res = await asyncio.to_thread(sync_stock_universe)
        _SYNC_STATE.update({k: res[k] for k in ("a", "hk", "total")})
        _SYNC_STATE["message"] = f"\u540c\u6b65\u5b8c\u6210\uff1aA\u80a1 {res['a']} \u53ea\uff0c\u6e2f\u80a1 {res['hk']} \u53ea"
        _SYNC_STATE["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        _SYNC_STATE["error"] = str(e)
        _SYNC_STATE["message"] = "\u540c\u6b65\u5931\u8d25\uff1a" + str(e)[:120]
        print("[stock_universe] sync error:", traceback.format_exc())
    finally:
        _SYNC_STATE["running"] = False

def trigger_sync():
    if _SYNC_STATE["running"]:
        return False
    asyncio.create_task(_worker())
    return True

def get_sync_state():
    return dict(_SYNC_STATE)
