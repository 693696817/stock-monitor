import datetime
import sys

import fuyao_client as fy

FAIL = []
WARN = []

def check(name, cond, detail=""):
    if cond:
        print("  OK   " + name)
    else:
        FAIL.append(name)
        print("  FAIL " + name + "  " + str(detail))

def soft(name, cond, detail=""):
    if cond:
        print("  OK   " + name)
    else:
        WARN.append(name)
        print("  WARN " + name + "（非交易时段为空属正常）  " + str(detail))

def main():
    if not fy.configured():
        print("未配置 FUYAO_API_KEY，跳过")
        return 1

    print("\n[1] 连通性")
    ok, msg = fy.probe()
    check("probe 连通", ok, msg)
    print("      " + msg)

    print("\n[2] 元数据 / 检索")
    rows, err = fy.ticker_search("华东医药")
    check("检索无错误", err is None, err)
    check("检索有结果", bool(rows), rows)
    if rows:
        top = rows[0]
        check("检索返回 thscode 且带后缀", top.get("ts_code") == "000963.SZ", top)
        check("检索返回中文名", top.get("name") == "华东医药", top)
    rows2, err2 = fy.ticker_search("贵州茅台")
    check("中文检索（编码）无错误", err2 is None, err2)

    print("\n[3] 行情快照")
    snap, err = fy.snapshot(["600519.SH", "000963.SZ"])
    check("快照无错误", err is None, err)
    check("快照返回 2 条", len(snap) == 2, len(snap))
    if snap:
        s = snap[0]
        check("快照 price 为 float", isinstance(s.get("price"), float), s.get("price"))
        check("快照 change 是百分数字符串",
              s.get("change") is None or isinstance(s.get("change"), str), s.get("change"))
        print("      样例：%s 价 %s 涨跌 %s%%" % (s.get("code"), s.get("price"), s.get("change")))

    print("\n[4] 历史 K 线")
    end = datetime.date.today()
    start = end - datetime.timedelta(days=120)
    bars, err = fy.historical("000963.SZ", start.isoformat(), end.isoformat(), adjust="forward")
    check("K线无错误", err is None, err)
    check("K线有数据", len(bars) > 10, len(bars))
    if bars:
        b = bars[0]
        check("K线字段齐全（date/open/high/low/close/volume/amount）",
              all(k in b for k in ("date", "open", "high", "low", "close", "volume", "amount")), b)
        check("K线日期升序", bars == sorted(bars, key=lambda x: x["date"]),
              [x["date"] for x in bars[:3]])
        check("K线 high >= low", all(x["high"] >= x["low"] for x in bars if x["high"] and x["low"]))
        print("      %d 根，%s ~ %s，末收 %s" % (len(bars), bars[0]["date"], bars[-1]["date"], bars[-1]["close"]))
    bad, berr = fy.historical("000963.SZ", "not-a-date", end.isoformat())
    check("非法日期返回错误（不静默返回空）", berr is not None and not bad, berr)

    print("\n[5] 龙虎榜（本站主接入点）")
    lhb, err = fy.dragon_tiger()
    check("龙虎榜无错误", err is None, err)
    check("龙虎榜有数据", bool(lhb), lhb)
    if lhb:
        it = lhb[0]
        check("含 ts_code/name", bool(it.get("ts_code")) and bool(it.get("name")), it)
        check("change 是百分数字符串（10% -> '10.00'）",
              it.get("change") is None or isinstance(it.get("change"), str), it.get("change"))
        check("净额已换算为亿元且量级合理（<1e4 亿）",
              it.get("net_total_yi") is None or abs(it.get("net_total_yi")) < 1e4,
              it.get("net_total_yi"))
        check("含上榜原因 limit_reason 字段", "limit_reason" in it, list(it))
        check("concepts 为 list", isinstance(it.get("concepts"), list), it.get("concepts"))
        check("含 trade_date", bool(it.get("trade_date")), it.get("trade_date"))
        print("      交易日 %s · %d 条" % (it.get("trade_date"), len(lhb)))
        print("      TOP1 %s %s 涨跌 %s%% 净买 %s 亿 原因：%s"
              % (it.get("code"), it.get("name"), it.get("change"),
                 it.get("net_total_yi"), it.get("limit_reason")))
    lhb2, err2 = fy.dragon_tiger(trade_date="2026-09-04")
    check("指定 trade_date 无错误", err2 is None, err2)
    soft("指定 trade_date 有数据", bool(lhb2), err2)

    print("\n[6] 同花顺热榜")
    hot, err = fy.hot_stock_list()
    check("热榜无错误", err is None, err)
    soft("热榜有数据", bool(hot), err)
    if hot:
        h = hot[0]
        check("热榜自带中文名", bool(h.get("name")), h)
        check("heat 为数值", isinstance(h.get("heat"), float), h.get("heat"))
        print("      TOP1 %s %s 热度 %s" % (h.get("code"), h.get("name"), h.get("heat")))
    hh, herr = fy.hot_stock_list_history("2026-09-04")
    check("历史热榜无错误", herr is None, herr)
    soft("历史热榜有数据", bool(hh), herr)
    if hh:
        check("历史热榜条目含 rank", hh[0].get("rank") is not None, hh[0])
    _, herr2 = fy.hot_stock_list_history("20260904")
    check("历史热榜 yyyyMMdd 会被归一化（不报错）", herr2 is None, herr2)

    d0 = (end - datetime.timedelta(days=30)).isoformat()
    tr, terr = fy.hot_stock_rank_trend("000963.SZ", d0, end.isoformat())
    check("排名走势无错误", terr is None, terr)
    soft("排名走势有数据", bool(tr), terr)
    if tr:
        check("排名走势条目含 date + rank",
              tr[0].get("date") is not None and tr[0].get("rank") is not None, tr[0])
        print("      %s 近 %d 个点，最新排名 %s" % (d0, len(tr), tr[-1].get("rank")))
    sky, serr = fy.skyrocket_list()
    check("飙升榜无错误", serr is None, serr)
    soft("飙升榜有数据", bool(sky), serr)

    print("\n[7] 异动 / 涨跌停（盘中才有，空属正常）")
    an, aerr = fy.anomaly_list()
    check("异动列表无错误", aerr is None, aerr)
    soft("异动列表有数据", bool(an), aerr)
    ans, anserr = fy.anomaly_stock(["000963.SZ", "600519.SH"])
    check("按股票查异动无错误", anserr is None, anserr)
    soft("按股票查异动有数据", bool(ans), anserr)
    for kind in ("up", "down", "break"):
        pool, perr = fy.limit_pool(kind)
        check("股票池(%s)无错误" % kind, perr is None, perr)
        soft("股票池(%s)有数据" % kind, bool(pool), perr)
    lad, lerr = fy.limit_up_ladder()
    check("连板天梯无错误", lerr is None, lerr)
    soft("连板天梯有数据", bool(lad), lerr)

    print("\n[8] 财务指标")
    fi, ferr = fy.financial_indicators("000963.SZ", report="2026-2")
    check("财务指标无错误", ferr is None, ferr)
    soft("财务指标有数据", bool(fi and fi.get("groups")), ferr)
    if fi and fi.get("groups"):
        print("      报告期 %s，分组：%s" % (fi.get("report"), list(fi["groups"])))
        g = fi["groups"].get("growth") or {}
        if g:
            k = list(g)[0]
            print("      成长类样例 %s = %s" % (k, g[k]))
    bad, berr = fy.financial_indicators("000963.SZ", report="2026-06-30")
    check("非法 report 格式返回错误", berr is not None, berr)

    print("\n[9] 交易日历")
    cal, cerr = fy.calendar()
    check("日历无错误", cerr is None, cerr)
    soft("日历有数据", bool(cal), cerr)
    if cal:
        check("日历日期格式 YYYY-MM-DD", all(len(d) == 10 and d[4] == "-" for d in cal), cal[:3])
        print("      %d 个交易日，%s ~ %s" % (len(cal), cal[0], cal[-1]))

    print("\n" + "=" * 60)
    if FAIL:
        print("❌ 失败 %d 项：" % len(FAIL))
        for f in FAIL:
            print("   - " + f)
    if WARN:
        print("⚠️ 空结果 %d 项（非交易时段属正常，交易日重跑应恢复）：" % len(WARN))
        for w in WARN:
            print("   - " + w)
    if not FAIL:
        print("✅ 伏尧数据源封装全部校验通过")
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
