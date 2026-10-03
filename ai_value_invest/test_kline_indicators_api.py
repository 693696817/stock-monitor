import json
import urllib.request

BASE = "http://127.0.0.1:8015"

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))

def get(path):
    r = opener.open(BASE + path, timeout=90)
    return r.status, json.loads(r.read().decode("utf-8"))

def main():
    ok_all = True

    def check(name, cond, detail=""):
        nonlocal ok_all
        if cond:
            print("  OK   " + name)
        else:
            ok_all = False
            print("  FAIL " + name + "  " + str(detail))

    for days in (60, 120, 240):
        code, j = get("/api/stock/000963.SZ/kline?days=%d&fq=lxr" % days)
        print("\n=== days=%d  HTTP %d ===" % (days, code))
        check("接口 status=success", j.get("status") == "success", j.get("msg"))
        check("ok=True", j.get("ok") is True, j.get("error"))
        rows = j.get("data") or []
        ind = j.get("indicators") or {}
        print("  K线 %d 根，复权=%s" % (len(rows), j.get("fq_label")))
        check("有 K 线数据", len(rows) > 0)
        check("有 indicators", bool(ind), list(ind)[:5])

        bad = {k: len(v) for k, v in ind.items() if len(v) != len(rows)}
        check("全部指标数组与 K 线等长（%d）" % len(rows), not bad, bad)

        ma60 = [v for v in (ind.get("ma60") or []) if v is not None]
        check("MA60 有值（预热窗口生效，%d/%d 个）" % (len(ma60), len(rows)), len(ma60) > 0)
        macd = [v for v in (ind.get("macd_bar") or []) if v is not None]
        check("MACD 柱有值（%d/%d 个）" % (len(macd), len(rows)), len(macd) > 0)
        adx = [v for v in (ind.get("adx") or []) if v is not None]
        check("ADX 有值（%d/%d 个）" % (len(adx), len(rows)), len(adx) > 0)

        def rng(key, lo, hi):
            vals = [v for v in (ind.get(key) or []) if v is not None]
            return all(lo <= v <= hi for v in vals), (min(vals) if vals else None, max(vals) if vals else None)

        for key, lo, hi in (("rsi6", 0, 100), ("wr6", 0, 100), ("tide_wave", -100, 100),
                            ("di_plus", 0, 100), ("kdj_k", -50, 150)):
            good, ext = rng(key, lo, hi)
            check("%s ∈ [%s,%s]  实测 %s" % (key, lo, hi, ext), good)

        dif, dea, bar = ind.get("macd_dif") or [], ind.get("macd_dea") or [], ind.get("macd_bar") or []
        bad_bar = [i for i in range(len(rows))
                   if bar[i] is not None and dif[i] is not None and dea[i] is not None
                   and abs(bar[i] - 2 * (dif[i] - dea[i])) > 1e-3]
        check("MACD 柱 == 2×(DIF−DEA)", not bad_bar, bad_bar[:5])

        up, dn = ind.get("td9_up") or [], ind.get("td9_down") or []
        bad_td = [i for i in range(len(rows)) if up[i] is not None and dn[i] is not None]
        check("九转：同一根不会既计上升又计下降", not bad_td, bad_td[:5])
        bad_td2 = [i for i in range(len(rows)) if (up[i] or 0) > 9 or (dn[i] or 0) > 9]
        check("九转：计数不超过 9", not bad_td2, bad_td2[:5])

        i = len(rows) - 1
        print("  ---- 最后一根 (%s) ----" % rows[i]["date"])
        print("   收 %s   量 %s" % (rows[i]["close"], rows[i]["volume"]))
        for k in ("ma5", "ma20", "ma60", "boll_up", "boll_mid", "boll_low",
                  "macd_dif", "macd_dea", "macd_bar", "kdj_k", "kdj_d", "kdj_j",
                  "rsi6", "wr6", "bias6", "cci", "di_plus", "di_minus", "adx",
                  "atr", "dpo", "obv", "tide_wave", "tide_tide", "tide_bar"):
            print("   %-10s %s" % (k, ind.get(k, ["?"])[i]))
        nz = sum(1 for a in range(len(rows)) if (up[a] or 0) >= 6 or (dn[a] or 0) >= 6)
        print("   九转 6~9 标注点：%d 个" % nz)
        check("存在九转标注点（前端才有东西可画）", nz > 0, nz)

        params = j.get("indicator_params") or {}
        check("返回 indicator_params（前端口径说明靠它）", bool(params), params)

    print("\n" + "=" * 60)
    print("PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1

if __name__ == "__main__":
    raise SystemExit(main())
