import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

import data_service as ds
from dataservice import market as ds_market
import fuyao_client as fy

PASS = FAIL = 0

def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  ✅ %s" % name)
    else:
        FAIL += 1
        print("  ❌ %s  %s" % (name, detail))

def soft(name, ok, detail=""):
    if ok:
        print("  ✅ %s" % name)
    else:
        print("  ⚠️  %s（非交易时段属正常）  %s" % (name, detail))

print("\n[1] 连板天梯结构不变量")
lad, err = fy.limit_up_ladder()
check("天梯无错误", err is None, err)
if lad:
    days = lad.get("days") or []
    check("days 非空", bool(days), lad.get("window_days"))
    check("days 按日期升序", [d.get("date") for d in days] == sorted(d.get("date") for d in days),
          [d.get("date") for d in days][:3])
    check("window_days == len(days)", lad.get("window_days") == len(days),
          "%s vs %s" % (lad.get("window_days"), len(days)))
    bad = [d for d in days if (d.get("max_board") or 0) != (max(d["tiers"]) if d.get("tiers") else 0)]
    check("max_board == max(tiers) 键", not bad, bad[:1])
    bad2 = [d for d in days if d.get("total") != sum((d.get("tiers") or {}).values())]
    check("total == Σtiers", not bad2, bad2[:1])
    bad3 = []
    for d in days:
        t, tiers = d.get("top"), d.get("tiers") or {}
        if t and tiers and t.get("board") != max(tiers):
            bad3.append((d.get("date"), t.get("board"), max(tiers)))
    check("top.board == 最高层级", not bad3, bad3[:1])
    print("      最新 %s 最高 %s 板，连板 %s 家，窗口 %s 个交易日"
          % (days[-1].get("date"), days[-1].get("max_board"), days[-1].get("total"), len(days)))

print("\n[2] 聚合层 get_market_limit_stats / get_market_hot_rank")
stats = ds.get_market_limit_stats(force=True)
check("聚合返回 dict", isinstance(stats, dict), stats)
if stats:
    L = stats.get("ladder")
    check("ladder 存在", isinstance(L, dict), stats)
    if L:
        check("ladder.date 为 yyyy-mm-dd", str(L.get("date") or "").count("-") == 2, L.get("date"))
        check("hist 长度 <= 30", len(L.get("hist") or []) <= 30, len(L.get("hist") or []))
        check("hist 每项含 date/max_board/total",
              all({"date", "max_board", "total"} <= set(h) for h in (L.get("hist") or [])), (L.get("hist") or [])[:1])
        check("tiers 按 board 升序",
              [t["board"] for t in L.get("tiers") or []] == sorted(t["board"] for t in L.get("tiers") or []),
              L.get("tiers"))
        check("trend 取值合法", L.get("trend") in ("up", "down", "flat"), L.get("trend"))
        mb, pmb = L.get("max_board"), L.get("prev_max_board")
        want = "up" if mb > pmb else ("down" if mb < pmb else "flat")
        check("trend 与 prev 一致", L.get("trend") == want, (mb, pmb, L.get("trend")))
    soft("pools 有数据（仅交易时段）", bool(stats.get("pools")), "周末/盘后为空属预期")
    if stats.get("pools"):
        p = stats["pools"]
        sr = p.get("seal_rate")
        check("封板率 0~100 或 None", sr is None or 0 <= sr <= 100, sr)
        check("封板率与 up/break 一致",
              sr is None or abs(sr - round(p["up"] / (p["up"] + p["break"]) * 100, 1)) < 0.05, (sr, p))

hot = ds.get_market_hot_rank(force=True)
check("人气榜返回 dict", isinstance(hot, dict), hot)
if hot:
    check("hot 榜单非空", bool(hot.get("hot")), hot.get("as_of"))
    check("sky 榜单非空", bool(hot.get("sky")), hot.get("as_of"))
    check("hot 不超过 10 条", len(hot.get("hot") or []) <= 10, len(hot.get("hot") or []))
    check("条目含 rank/name/heat",
          all({"rank", "name", "heat"} <= set(r) for r in (hot.get("hot") or [])), (hot.get("hot") or [])[:1])
    check("rank 从 1 递增", [r["rank"] for r in hot["hot"]] == list(range(1, len(hot["hot"]) + 1)),
          [r["rank"] for r in hot["hot"]][:5])
    print("      TOP1 %s 热度 %s（更新 %s）"
          % (hot["hot"][0].get("name"), hot["hot"][0].get("heat"), hot.get("as_of")))

print("\n[3] 情绪模型：缺失分项贡献 0，不压向 50")

def _senti(**kw):
    r = {"north_is_up": kw.get("north"), "ladder": kw.get("ladder"), "pools": kw.get("pools")}
    ds_market._compute_sentiment(r, kw.get("rows"))
    return r["sentiment"]

base = _senti(rows=rows, north=None, ladder=None, pools=None)
check("仅龙虎榜时 = 50 + (40/60-0.5)*38", abs(base - (50 + (40 / 60 - 0.5) * 38)) < 0.05, base)
check("北向流入 +8", abs(_senti(rows=rows, north=True, ladder=None) - (base + 8)) < 0.05, base)
check("北向流出 -8", abs(_senti(rows=rows, north=False, ladder=None) - (base - 8)) < 0.05, base)
check("北向缺失 = 北向 0（不是 -8）", _senti(rows=rows, north=None, ladder=None) == base, base)
check("无连板（0 板）→ -12", abs(_senti(rows=rows, north=None,
                                ladder={"max_board": 0}) - (base - 12)) < 0.05, base)
check("4 板 → 0 分（中性基准）",
      abs(_senti(rows=rows, north=None, ladder={"max_board": 4}) - base) < 0.05, base)
check("8 板 → +12（封顶）",
      abs(_senti(rows=rows, north=None, ladder={"max_board": 8}) - (base + 12)) < 0.05, base)
check("12 板仍封顶 +12（不溢出）",
      abs(_senti(rows=rows, north=None, ladder={"max_board": 12}) - (base + 12)) < 0.05, base)
check("涨停:跌停=1:1 → 0 分",
      abs(_senti(rows=rows, north=None, pools={"up": 50, "down": 50}) - base) < 0.05, base)
check("涨停全占 → +12",
      abs(_senti(rows=rows, north=None, pools={"up": 100, "down": 0}) - (base + 12)) < 0.05, base)
check("跌停全占 → -12",
      abs(_senti(rows=rows, north=None, pools={"up": 0, "down": 100}) - (base - 12)) < 0.05, base)
check("全部分项缺失 = 50 中性", _senti(rows=None, north=None, ladder=None, pools=None) == 50, "")
check("分值域 2~98", all(2 <= _senti(rows=rows, north=True, ladder={"max_board": 9},
                                    pools={"up": 999, "down": 0}) <= 98 for _ in range(1)), "")
r = {}
ds_market._compute_sentiment(r, rows)
check("sentiment_parts 有明细", bool(r.get("sentiment_parts")), r.get("sentiment_parts"))

print("\n[3b] 分档（恐惧贪婪条）与 label 判定必须一致")
def _label_of(v):
    return ("贪婪" if v >= 70 else "乐观" if v >= 58 else
            "中性" if v >= 45 else "谨慎" if v >= 30 else "恐慌")

mismatch = []
for v in [0, 1, 14.9, 29.99, 30, 31, 44.99, 45, 50, 57.99, 58, 66.7, 69.99, 70, 85, 99.9]:
    z = ds_market._sentiment_zone(v)
    if not z or z["label"] != _label_of(v):
        mismatch.append((v, z and z["label"], _label_of(v)))
check("zones 与 label 判定逐点一致（16 个取样点）", not mismatch, mismatch[:3])
check("zones 首尾覆盖 0~100",
      ds.SENTIMENT_ZONES[0]["min"] == 0 and ds.SENTIMENT_ZONES[-1]["max"] == 100,
      (ds.SENTIMENT_ZONES[0], ds.SENTIMENT_ZONES[-1]))
gaps = [(a["max"], b["min"]) for a, b in zip(ds.SENTIMENT_ZONES, ds.SENTIMENT_ZONES[1:]) if a["max"] != b["min"]]
check("zones 区间无缝无重叠", not gaps, gaps)
check("zones 五项齐全", len(ds.SENTIMENT_ZONES) == 5, len(ds.SENTIMENT_ZONES))

print("\n[4] include_fuyao 开关语义")
check("默认不带伏尧字段", d_off.get("ladder") is None and d_off.get("hot_rank") is None,
      (d_off.get("ladder"), d_off.get("hot_rank")))
check("默认仍算出情绪", isinstance(d_off.get("sentiment"), (int, float)), d_off.get("sentiment"))
d_on = ds.get_market_overview_datahub(include_fuyao=True)
check("include_fuyao=True 带上天梯", isinstance(d_on.get("ladder"), dict), d_on.get("ladder"))
check("include_fuyao=True 带上人气榜", isinstance(d_on.get("hot_rank"), dict), d_on.get("hot_rank"))
print("      情绪 OFF=%s / ON=%s，分项 %s"
      % (d_off.get("sentiment"), d_on.get("sentiment"), d_on.get("sentiment_parts")))

print("\n[5] 回落路径：伏尧关闭时不崩")
import settings as _st

_orig = _st.get_setting
try:
    _st.get_setting = lambda k, d=None: ("0" if k == "FUYAO_ENABLED" else _orig(k, d))
    ds_market._FUYAO_LADDER_CACHE.update({"ts": 0.0, "data": None, "empty_ts": 0.0})
    ds_market._FUYAO_HOT_CACHE.update({"ts": 0.0, "data": None, "empty_ts": 0.0})
    d = ds.get_market_overview_datahub(include_fuyao=True)
    check("关闭后不抛异常", isinstance(d, dict), type(d))
    check("关闭后 ladder 为 None", d.get("ladder") is None, d.get("ladder"))
    check("关闭后 hot_rank 为 None", d.get("hot_rank") is None, d.get("hot_rank"))
    check("关闭后情绪仍可算", isinstance(d.get("sentiment"), (int, float)), d.get("sentiment"))
    check("关闭后指数/龙虎榜不受影响", bool(d.get("sh")) and d.get("limit_count") is not None,
          (d.get("sh", {}).get("price") if isinstance(d.get("sh"), dict) else None, d.get("limit_count")))
finally:
    _st.get_setting = _orig

print("\n[6] 缓存语义")
ds_market._FUYAO_LADDER_CACHE.update({"ts": 0.0, "data": None, "empty_ts": 0.0})
import time

t0 = time.time(); ds.get_market_limit_stats(force=True); t1 = time.time()
ds.get_market_limit_stats(); t2 = time.time()
check("二次调用走缓存（<50ms）", (t2 - t1) * 1000 < 50, "%.1fms" % ((t2 - t1) * 1000))
print("      首次 %.0fms，缓存后 %.1fms" % ((t1 - t0) * 1000, (t2 - t1) * 1000))

print("\n---- PASS %d / FAIL %d ----" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
