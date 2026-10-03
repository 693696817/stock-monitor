import io
import sys
import time

import data_service as ds
import settings

FAIL = []

def check(name, cond, detail=""):
    if cond:
        print("  OK   " + name)
    else:
        FAIL.append(name)
        print("  FAIL " + name + "  " + str(detail))

def reset_cache():
    ds._FUYAO_LHB_CACHE["rows"] = None
    ds._FUYAO_LHB_CACHE["ts"] = 0.0

def main():
    print("\n[1] 数据源开关状态")
    check("settings.fuyao_enabled() 为 True", settings.fuyao_enabled() is True,
          settings.fuyao_enabled())
    import fuyao_client
    check("伏瑶客户端已配置 Key", fuyao_client.configured())

    print("\n[2] 龙虎榜统一入口 —— 伏尧优先")
    reset_cache()
    t0 = time.time()
    rows, provider = ds.get_dragon_tiger_cached("desc", limit=100)
    ms = int((time.time() - t0) * 1000)
    check("provider == 伏尧", provider == "伏尧", provider)
    check("有数据", bool(rows), rows)
    print("      %d 条，耗时 %dms（对比：理杏仁路径要再逐条补 100 次日线）" % (len(rows), ms))
    if rows:
        r = rows[0]
        check("兼容字段 stock_code 存在", bool(r.get("stock_code")), list(r))
        check("兼容字段 net_total_yi 存在", r.get("net_total_yi") is not None, r.get("net_total_yi"))
        check("新字段 name（理杏仁源没有）", bool(r.get("name")), r.get("name"))
        check("新字段 change 涨跌幅", r.get("change") is not None, r.get("change"))
        check("新字段 limit_reason 上榜原因", r.get("limit_reason") is not None, r.get("limit_reason"))
        check("新字段 concepts 概念标签", isinstance(r.get("concepts"), list), r.get("concepts"))
        check("新字段 buy_yi / sell_yi", r.get("buy_yi") is not None and r.get("sell_yi") is not None,
              [r.get("buy_yi"), r.get("sell_yi")])
        check("新字段 hot_money_yi 游资净额", "hot_money_yi" in r, list(r))
        print("      TOP1: %s %s 涨跌 %s%% 净买 %s 亿" %
              (r.get("stock_code"), r.get("name"), r.get("change"), r.get("net_total_yi")))
        print("      上榜原因：%s" % (r.get("limit_reason") or "（无）"))
        print("      概念：%s" % "、".join(r.get("concepts") or []))

    print("\n[3] 排序语义（desc=净买入 TOP / asc=净卖出 TOP）")
    reset_cache()
    up, _ = ds.get_dragon_tiger_cached("desc", limit=100)
    if up:
        vals = [float(x.get("net_total_yi") or 0) for x in up]
        check("desc 按净买入降序", vals == sorted(vals, reverse=True), vals[:5])
        check("desc 首条为正（净买入）", vals[0] > 0, vals[0])
    reset_cache()
    dn, _ = ds.get_dragon_tiger_cached("asc", limit=100)
    if dn:
        vals2 = [float(x.get("net_total_yi") or 0) for x in dn]
        check("asc 按净卖出升序", vals2 == sorted(vals2), vals2[:5])

    print("\n[4] 回落路径：关掉伏尧开关后应干净退回理杏仁")
    orig_get = settings.get_setting

    def patched(key, default=None):
        if key == "FUYAO_ENABLED":
            return "0"
        return orig_get(key, default)

    settings.get_setting = patched
    try:
        reset_cache()
        rows2, provider2 = ds.get_dragon_tiger_cached("desc", limit=100)
        check("关掉开关后不再使用伏尧", provider2 != "伏尧", provider2)
        check("回落不抛异常、不返回 None", rows2 is not None)
        print("      回落 provider=%r，%d 条（理杏仁无数据时为空属正常）" % (provider2, len(rows2 or [])))
        if rows2:
            r2 = rows2[0]
            check("回落源仍保证兼容字段 stock_code/net_total_yi",
                  bool(r2.get("stock_code")) and r2.get("net_total_yi") is not None, list(r2))
    finally:
        settings.get_setting = orig_get
    reset_cache()

    print("\n[5] 二次调用走进程缓存（不再重复打接口）")
    t1 = time.time()
    ds.get_dragon_tiger_cached("desc", limit=100)
    first = int((time.time() - t1) * 1000)
    t2 = time.time()
    ds.get_dragon_tiger_cached("desc", limit=100)
    second = int((time.time() - t2) * 1000)
    check("第二次调用明显更快（缓存命中 %dms → %dms）" % (first, second), second < first,
          [first, second])

    print("\n" + "=" * 60)
    if FAIL:
        print("❌ 失败 %d 项：" % len(FAIL))
        for f in FAIL:
            print("   - " + f)
        return 1
    print("✅ 伏尧接入集成验收全部通过")
    return 0

if __name__ == "__main__":
    sys.exit(main())
