import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

P = F = 0

def ok(name, cond, extra=None):
    global P, F
    if cond:
        P += 1
        print("  [OK] " + name)
    else:
        F += 1
        print("  [FAIL] " + name + (("  -> " + str(extra)) if extra is not None else ""))

def _mkday(d, o, c, h, l, v, a):
    return {"date": d, "open": "%.2f" % o, "close": "%.2f" % c,
            "high": "%.2f" % h, "low": "%.2f" % l,
            "volume": v, "amount": a, "change": None, "turnover": "1.00"}

def test_resample_unit():
    print("\n[A] 聚合数学正确性（纯函数）")
    import stock_detail_service as s

    rows = [
        _mkday("2026-08-31", 10, 11, 11.5, 9.8, 100, 1000),
        _mkday("2026-09-01", 11, 12, 12.5, 10.8, 200, 2000),
        _mkday("2026-09-02", 12, 13, 13.5, 11.8, 300, 3000),
        _mkday("2026-09-03", 13, 9, 13.9, 8.8, 400, 4000),
        _mkday("2026-09-04", 9, 10, 10.5, 8.1, 500, 5000),
    ]
    w = s._resample(rows, "week")
    ok("周线合成 1 根", len(w) == 1, len(w))
    if len(w) != 1:
        return
    k = w[0]
    ok("周·开 = 区间首日开盘 10.00", k["open"] == "10.00", k["open"])
    ok("周·收 = 区间末日收盘 10.00", k["close"] == "10.00", k["close"])
    ok("周·高 = 区间最高 13.90（不是字典序的 10.50）", k["high"] == "13.90", k["high"])
    ok("周·低 = 区间最低 8.10", k["low"] == "8.10", k["low"])
    ok("周·量 = 求和 1500", k["volume"] == 1500.0, k["volume"])
    ok("周·额 = 求和 15000", k["amount"] == 15000.0, k["amount"])
    ok("周·跨 5 个交易日", k["span_days"] == 5, k["span_days"])

    m = s._resample(rows, "month")
    ok("月线合成 2 根（8月 + 9月）", len(m) == 2, len(m))
    if len(m) == 2:
        ok("月1 开10 收11", m[0]["open"] == "10.00" and m[0]["close"] == "11.00",
           (m[0]["open"], m[0]["close"]))
        ok("月2 开11 收10", m[1]["open"] == "11.00" and m[1]["close"] == "10.00",
           (m[1]["open"], m[1]["close"]))
        ok("月2 涨跌幅 = (10/11-1) = -9.09%", m[1]["change"] == "-9.09", m[1]["change"])
        ok("月1 无前值 → 涨跌幅为 None（不编 0）", m[0]["change"] is None, m[0]["change"])

    tricky = [
        _mkday("2026-09-01", 100, 100, 100, 100, 10, 100),
        _mkday("2026-09-02", 99, 99, 999, 1, 10, 100),
    ]
    t = s._resample(tricky, "week")
    ok("高低价按数值比较而非字典序（999 > 100）",
       t and t[0]["high"] == "999.00" and t[0]["low"] == "1.00",
       t[0] if t else None)

def test_service_e2e():
    print("\n[B] 五个周期 × 全部档位（接口层）")
    import db
    import stock_detail_service as s

    TS = "600519.SH"

    counts = {}
    for period in ("day", "week", "month", "year"):
        prev_n = 0
        for days in s.PERIOD_WINDOWS[period]:
            r = s.get_kline(TS, fq="lxr", days=days, period=period)
            ok("%s · %s日 → ok" % (period, days), bool(r.get("ok")), r.get("error"))
            n = r.get("count") or 0
            counts.setdefault(period, []).append(n)
            d = r.get("data") or []
            if d:
                bad = [x for x in d if x.get("open") is None or x.get("close") is None]
                ok("%s · %s日 开收盘无缺失" % (period, days), not bad,
                   bad[:2] if bad else None)
            ok("%s · %s日 根数随窗口单调不减（%d ≥ %d）" % (period, days, n, prev_n),
               n >= prev_n, (n, prev_n))
            prev_n = n

    import lixinger_service as lx
    raw = lx.fetch_candlestick(TS, days=3650, fq_type="lxr_fc_rights") or []
    drows = sorted([x for x in raw if x.get("date")], key=lambda x: str(x.get("date")))
    daily = [{"date": str(x.get("date"))[:10],
              "open": x.get("open"), "close": x.get("close"),
              "high": x.get("high"), "low": x.get("low"),
              "volume": x.get("volume"), "amount": x.get("amount"),
              "change": None, "turnover": x.get("to_r")} for x in drows]
    counts = [("day", len(daily))] + [
        (p, len(s._resample(daily, p))) for p in ("week", "month", "year")
    ]
    mono = all(counts[i][1] < counts[i - 1][1] for i in range(1, len(counts)))
    ok("同一份日线：日 > 周 > 月 > 年 根数递减", mono, counts)
    if len(daily) > 100:
        ratio = len(daily) / float(counts[1][1])
        ok("周线根数 ≈ 日线/5（实测 %.2f，应在 4.5~5.5）" % ratio, 4.5 <= ratio <= 5.5, ratio)

    print("\n[C] 分时")
    r = s.get_kline(TS, fq="lxr", days=1, period="minute")
    ok("分时 ok", bool(r.get("ok")), r.get("error"))
    rows = r.get("data") or []
    ok("分时根数 200~250（A股全天）", 200 <= len(rows) <= 250, len(rows))
    if rows:
        t0, t1 = rows[0]["date"], rows[-1]["date"]
        ok("分时时间严格递增 %s → %s" % (t0, t1), t0 < t1, (t0, t1))
        ok("分时同一交易日", t0[:10] == t1[:10], (t0[:10], t1[:10]))
        ok("分时昨收非空", r.get("prev_close") is not None, r.get("prev_close"))
        avg = r.get("avg_price") or []
        ok("均价线非空且长度一致", len(avg) == len(rows) and all(x is not None for x in avg),
           (len(avg), len(rows)))
        chg = r.get("change") or []
        ok("分时涨跌幅序列非空", len(chg) == len(rows) and chg[-1] is not None,
           chg[-1] if chg else None)

        day = s.get_kline(TS, fq="lxr", days=60, period="day")
        drows = day.get("data") or []
        if drows:
            last_day = drows[-1]
            ok("分时所属日 == 日线最后一根日期（%s / %s）" % (t1[:10], last_day["date"]),
               t1[:10] == last_day["date"], (t1[:10], last_day["date"]))
            mc = float(rows[-1]["close"])
            dc = float(last_day["close"])
            ok("分时末收 == 日线收盘（%.2f / %.2f）" % (mc, dc), abs(mc - dc) < 0.01, (mc, dc))
            if chg:
                dchg = float(last_day["change"]) if last_day.get("change") else None
                ok("分时末涨跌幅 == 日线涨跌幅（%.2f%% / %.2f%%）" % (chg[-1], dchg or 0),
                   dchg is not None and abs(chg[-1] - dchg) < 0.02, (chg[-1], dchg))

    print("\n[D] 边界与健壮性")
    r = s.get_kline(TS, fq="lxr", days=120, period="bogus")
    ok("非法 period 回落到 day", r.get("period") == "day", r.get("period"))
    r = s.get_kline(TS, fq="lxr", days=99999, period="week")
    ok("越界 days 被夹到最近档位", r.get("ok") and r.get("count", 0) > 0, r.get("count"))
    r = s.get_kline(TS, fq="bogus", days=120, period="day")
    ok("非法 fq 回落到新版全复权", r.get("fq") == "lxr_fc_rights", r.get("fq"))
    r = s.get_kline(TS, fq="lxr", days=1825, period="year")
    ok("年线（仅 5~7 根）不崩且指标结构存在",
       r.get("ok") and isinstance(r.get("indicators"), dict), r.get("error"))
    ok("年线根数 ≤ 7", (r.get("count") or 0) <= 7, r.get("count"))

def test_http():
    print("\n[E] HTTP 接口")
    import urllib.request
    sys.path.insert(0, HERE)
    import auth

    class NR(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a):
            return None

    op = urllib.request.build_opener(NR, urllib.request.ProxyHandler({}))
    for period, days in (("minute", 1), ("day", 120), ("week", 365),
                         ("month", 730), ("year", 1825)):
        req = urllib.request.Request(
            "http://127.0.0.1:8015/api/stock/600519.SH/kline?period=%s&days=%d" % (period, days))
        req.add_header("Cookie", "geek_session=" + auth._sign({"uid": 1}))
        try:
            r = op.open(req, timeout=90)
            import json
            j = json.loads(r.read().decode("utf-8"))
            ok("GET /kline?period=%s → 200 ok" % period,
               r.status == 200 and j.get("status") == "success" and j.get("ok"),
               j.get("error") or j.get("msg"))
        except Exception as e:
            ok("GET /kline?period=%s" % period, False, "%s: %s" % (type(e).__name__, e))

if __name__ == "__main__":
    test_resample_unit()
    try:
        test_service_e2e()
    except Exception as e:
        F += 1
        print("  [FAIL] 接口层测试异常: %s: %s" % (type(e).__name__, e))
    try:
        test_http()
    except Exception as e:
        print("  [SKIP] HTTP 段（8015 未启动？）: %s: %s" % (type(e).__name__, e))
    print("\n---- PASS %d / FAIL %d" % (P, F))
    sys.exit(1 if F else 0)
