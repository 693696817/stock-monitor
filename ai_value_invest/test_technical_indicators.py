import math

import technical_indicators as ti

FAIL = []

def check(name, cond, detail=""):
    if cond:
        print("  ✓ " + name)
    else:
        FAIL.append(name + (" | " + str(detail) if detail else ""))
        print("  ✗ " + name + "  " + str(detail))

def series(n, start=10.0, step=1.0, spread=0.4):
    rows = []
    for i in range(n):
        c = start + i * step
        o = c - step * 0.5 if step else c
        rows.append({
            "date": "2026-01-%02d" % (i + 1),
            "open": o, "high": c + spread, "low": o - spread, "close": c,
            "volume": 1000000 + i * 1000,
            "amount": (1000000 + i * 1000) * c,
        })
    return rows

def flat(n, price=10.0):
    return [{"date": "2026-01-%02d" % (i + 1), "open": price, "high": price,
             "low": price, "close": price, "volume": 1000, "amount": 10000} for i in range(n)]

print("\n[1] 长度对齐 / 结构")
rows = series(80)
ind = ti.compute_all(rows)
check("返回非空", len(ind) > 20, list(ind)[:5])
check("全部数组与 rows 等长（80）",
      all(len(v) == 80 for v in ind.values()),
      {k: len(v) for k, v in ind.items() if len(v) != 80})

print("\n[2] 预热期必须是 None（不是 0！）")
check("ma60 前 59 根为 None", all(ind["ma60"][i] is None for i in range(59)), ind["ma60"][:3])
check("ma60 第 60 根有值", ind["ma60"][59] is not None, ind["ma60"][59])
check("ma5 前 4 根为 None", all(ind["ma5"][i] is None for i in range(4)))
check("boll_up 前 19 根为 None", all(ind["boll_up"][i] is None for i in range(19)))
check("adx 起始段为 None（Wilder 双平滑需要更长预热）",
      all(ind["adx"][i] is None for i in range(20)), ind["adx"][:25])

print("\n[3] 恒等关系")
dif, dea, bar = ind["macd_dif"], ind["macd_dea"], ind["macd_bar"]
ok = True
for i in range(80):
    if bar[i] is None:
        continue
    if abs(bar[i] - 2 * (dif[i] - dea[i])) > 1e-3:
        ok = False
        break
check("MACD 柱 == 2×(DIF−DEA)", ok)
ok = True
worst = 0.0
for i in range(80):
    if ind["kdj_j"][i] is None:
        continue
    diff = abs(ind["kdj_j"][i] - (3 * ind["kdj_k"][i] - 2 * ind["kdj_d"][i]))
    worst = max(worst, diff)
    if diff > 0.05:
        ok = False
check("KDJ: J == 3K − 2D（含舍入容差 0.05，实测 %.4f）" % worst, ok)
ok = True
for i in range(80):
    if ind["boll_up"][i] is None:
        continue
    if not (ind["boll_up"][i] >= ind["boll_mid"][i] >= ind["boll_low"][i]):
        ok = False
        break
check("BOLL: 上轨 ≥ 中轨 ≥ 下轨", ok)
ok = True
for i in range(80):
    if ind["tide_bar"][i] is None:
        continue
    if abs(ind["tide_bar"][i] - (ind["tide_wave"][i] - ind["tide_tide"][i])) > 1e-2:
        ok = False
        break
check("潮汐柱 == 汐线 − 潮线", ok)

print("\n[4] 值域")
check("RSI ∈ [0,100]", all(0 <= v <= 100 for v in ind["rsi6"] if v is not None))
check("WR ∈ [0,100]", all(0 <= v <= 100 for v in ind["wr6"] if v is not None))
check("潮汐 ∈ [−100,100]", all(-100 <= v <= 100 for v in ind["tide_wave"] if v is not None))
check("DI+ / DI− ∈ [0,100]",
      all(0 <= v <= 100 for v in ind["di_plus"] if v is not None)
      and all(0 <= v <= 100 for v in ind["di_minus"] if v is not None))

print("\n[5] 单调上涨序列的极值语义")
check("RSI6 恒为 100（无下跌日）", all(v == 100 for v in ind["rsi6"] if v is not None), ind["rsi6"][-3:])
check("WR6 落在超买区（<20）",
      all(0 <= v < 20 for v in ind["wr6"] if v is not None), ind["wr6"][-3:])
check("潮汐 = +100（全阳线 → 净额占比 100%）",
      all(abs(v - 100) < 1e-6 for v in ind["tide_wave"] if v is not None), ind["tide_wave"][-3:])
check("OBV 单调递增", all(ind["obv"][i] <= ind["obv"][i + 1]
                        for i in range(60, 79) if ind["obv"][i] is not None))
check("上升九转计数出现 9", 9 in [v for v in ind["td9_up"] if v is not None])
check("上升九转时下降计数为空",
      all(ind["td9_down"][i] is None for i in range(80) if ind["td9_up"][i] is not None))

print("\n[6] 九转计数循环（1→9 后重新起算，不出现 10）")
up = [v for v in ind["td9_up"] if v is not None]
check("计数不超 9", max(up) <= 9, max(up))
check("计数序列递增到 9 后回落", up[:11] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 1, 2], up[:11])

print("\n[7] 缺失值不污染窗口（关键：不能拿 None 当 0）")
bad = series(40)
bad[20]["close"] = None
bad[20]["high"] = None
ind2 = ti.compute_all(bad)
check("缺失日 ma5 为 None", ind2["ma5"][20] is None)
check("窗口含缺失的 5 个位置全部断开（20~24）",
      all(ind2["ma5"][i] is None for i in range(20, 25)), ind2["ma5"][20:26])
check("窗口完全滑过缺失后恢复（i=25，窗口 21~25）", ind2["ma5"][25] is not None, ind2["ma5"][25])
check("缺失日不影响数组长度", len(ind2["ma5"]) == 40)

print("\n[8] 一字板（最高=最低）不崩、不算 NaN")
fl = flat(40)
ind3 = ti.compute_all(fl)
check("BOLL 三轨相等（标准差 0）",
      all(abs(ind3["boll_up"][i] - ind3["boll_low"][i]) < 1e-9
          for i in range(19, 40)), ind3["boll_up"][-1])
check("KDJ RSV 退化取 50 中值 → K 收敛 50", abs(ind3["kdj_k"][-1] - 50) < 0.5, ind3["kdj_k"][-1])
check("WR 退化取 50 中值", abs(ind3["wr6"][-1] - 50) < 1e-9, ind3["wr6"][-1])
check("CCI 分母为 0 时取 0 而非 NaN/Inf", ind3["cci"][-1] == 0.0, ind3["cci"][-1])
check("无 NaN 泄漏",
      not any(isinstance(v, float) and math.isnan(v)
              for arr in ind3.values() for v in arr))

print("\n[9] 空输入")
check("空 rows 返回空 dict", ti.compute_all([]) == {})
check("None 输入不抛异常", ti.compute_all(None) == {})

print("\n" + "=" * 60)
if FAIL:
    print("❌ 失败 %d 项：" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("✅ 技术指标全部不变量校验通过")
