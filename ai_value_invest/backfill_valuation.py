
import argparse
import datetime
import sys
import time

import db
import lixinger_service as lx_svc

HORIZONS = ((20, "px_20d", "ret_20d"),
            (60, "px_60d", "ret_60d"),
            (120, "px_120d", "ret_120d"),
            (250, "px_250d", "ret_250d"))

def _to_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None

def _bar_date(b):
    return str(b.get("date") or "")[:10]

def _bar_close(b):
    for k in ("close", "closingPrice", "closePrice"):
        v = _to_float(b.get(k))
        if v is not None:
            return v
    return None

def backfill_one(row, dry_run=False):
    rid = row.get("id")
    ts_code = row.get("stock_code")
    adate = row.get("analysis_date")
    if not ts_code or not adate:
        return "skip", "缺代码或日期"

    ad = str(adate)[:10]
    try:
        y, m, d = (int(x) for x in ad.split("-"))
        start = datetime.date(y, m, d)
    except Exception:
        return "skip", f"日期格式异常 {ad}"

    span = (datetime.date.today() - start).days + 5
    if span < 5:
        return "skip", "日期在未来"

    try:
        data = lx_svc.fetch_candlestick(ts_code, days=span + 450)
    except Exception as e:
        return "error", f"K线拉取失败 {type(e).__name__}: {e}"

    bars = [b for b in (data or []) if _bar_close(b) is not None and _bar_date(b)]
    if not bars:
        return "error", "K线为空"
    bars.sort(key=_bar_date)

    idx = None
    for i, b in enumerate(bars):
        if _bar_date(b) >= ad:
            idx = i
            break
    if idx is None:
        return "skip", "该日之后无交易数据"

    base = _bar_close(bars[idx]) or _to_float(row.get("price_at"))
    if not base or base <= 0:
        return "skip", "无法确定基准价"

    fields = {}
    for n, pk, rk in HORIZONS:
        j = idx + n
        if j >= len(bars):
            continue
        pj = _bar_close(bars[j])
        if pj is None or pj <= 0:
            continue
        fields[pk] = round(pj, 3)
        fields[rk] = round((pj - base) / base * 100.0, 2)

    if not fields:
        return "wait", f"数据只到 {_bar_date(bars[-1])}，还不够 N 个交易日"

    if dry_run:
        return "dry", str(fields)
    ok = db.apply_valuation_backfill(rid, **fields)
    return ("ok" if ok else "error"), str(fields)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = db.list_valuations_for_backfill(limit=args.limit)
    print(f"待回填记录：{len(rows)} 条（limit={args.limit}"
          f"{'，dry-run 不写库' if args.dry_run else ''}）\n")

    stat = {}
    for r in rows:
        st, msg = backfill_one(r, dry_run=args.dry_run)
        stat[st] = stat.get(st, 0) + 1
        print(f"  [{st:5}] id={r.get('id')} {r.get('stock_code')} "
              f"{r.get('analysis_date')}  {msg}")
        time.sleep(0.1)

    print("\n" + "-" * 50)
    print("汇总：" + "  ".join(f"{k}={v}" for k, v in sorted(stat.items())))
    return 0

if __name__ == "__main__":
    sys.exit(main())
