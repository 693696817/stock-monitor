from typing import List, Optional

__all__ = ["compute_all", "PARAMS"]

PARAMS = {
    "ma": [5, 10, 20, 60],
    "boll": [20, 2],
    "macd": [12, 26, 9],
    "kdj": [9, 3, 3],
    "rsi": [6, 12, 24],
    "wr": [6, 10],
    "bias": [6, 12, 24],
    "cci": 14,
    "dmi": 14,
    "atr": 14,
    "dpo": 20,
    "vol_ma": [5, 10],
    "tide": [6, 20],
    "td9": 4,
}

def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f

def _r(v, nd=4) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return round(f, nd)

def _col(rows, key) -> List[Optional[float]]:
    return [_f((r or {}).get(key)) for r in rows]

def sma(vals, n) -> List[Optional[float]]:
    out = [None] * len(vals)
    if n <= 0:
        return out
    win, total, bad = [], 0.0, 0
    for i, v in enumerate(vals):
        win.append(v)
        if v is None:
            bad += 1
        else:
            total += v
        if len(win) > n:
            old = win.pop(0)
            if old is None:
                bad -= 1
            else:
                total -= old
        if len(win) == n and bad == 0:
            out[i] = total / n
    return out

def _roll_ext(vals, n, mode) -> List[Optional[float]]:
    out = [None] * len(vals)
    for i in range(n - 1, len(vals)):
        seg = vals[i - n + 1:i + 1]
        if any(v is None for v in seg):
            continue
        out[i] = max(seg) if mode == "max" else min(seg)
    return out

def hhv(vals, n):
    return _roll_ext(vals, n, "max")

def llv(vals, n):
    return _roll_ext(vals, n, "min")

def ema(vals, n) -> List[Optional[float]]:
    out = [None] * len(vals)
    if n <= 0:
        return out
    k = 2.0 / (n + 1.0)
    prev = None
    for i, v in enumerate(vals):
        if v is None:
            continue
        prev = v if prev is None else v * k + prev * (1.0 - k)
        out[i] = prev
    return out

def rma(vals, n) -> List[Optional[float]]:
    out = [None] * len(vals)
    if n <= 0:
        return out
    seed, cnt = 0.0, 0
    prev = None
    for i, v in enumerate(vals):
        if v is None:
            continue
        if prev is None:
            seed += v
            cnt += 1
            if cnt == n:
                prev = seed / n
                out[i] = prev
            continue
        prev = (prev * (n - 1) + v) / n
        out[i] = prev
    return out

def boll(closes, n=20, k=2):
    mid = sma(closes, n)
    up = [None] * len(closes)
    low = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        if mid[i] is None:
            continue
        seg = closes[i - n + 1:i + 1]
        if any(v is None for v in seg):
            continue
        var = sum((v - mid[i]) ** 2 for v in seg) / n
        sd = var ** 0.5
        up[i] = mid[i] + k * sd
        low[i] = mid[i] - k * sd
    return mid, up, low

def td9(closes, shift=4):
    n = len(closes)
    up = [None] * n
    down = [None] * n
    uc = dc = 0
    for i in range(shift, n):
        c, ref = closes[i], closes[i - shift]
        if c is None or ref is None:
            uc = dc = 0
            continue
        if uc >= 9:
            uc = 0
        if dc >= 9:
            dc = 0
        if c > ref:
            uc += 1
            dc = 0
        elif c < ref:
            dc += 1
            uc = 0
        else:
            uc = dc = 0
        if uc:
            up[i] = uc
        if dc:
            down[i] = dc
    return up, down

def macd(closes, s=12, l=26, m=9):
    es, el = ema(closes, s), ema(closes, l)
    dif = [None] * len(closes)
    for i in range(len(closes)):
        if es[i] is not None and el[i] is not None:
            dif[i] = es[i] - el[i]
    dea = ema(dif, m)
    bar = [None] * len(closes)
    for i in range(len(closes)):
        if dif[i] is not None and dea[i] is not None:
            bar[i] = 2.0 * (dif[i] - dea[i])
    return dif, dea, bar

def kdj(highs, lows, closes, n=9, m1=3, m2=3):
    hh, ll = hhv(highs, n), llv(lows, n)
    rsv = [None] * len(closes)
    for i in range(len(closes)):
        if hh[i] is None or ll[i] is None or closes[i] is None:
            continue
        rng = hh[i] - ll[i]
        rsv[i] = 50.0 if rng == 0 else (closes[i] - ll[i]) / rng * 100.0
    k = [None] * len(closes)
    d = [None] * len(closes)
    j = [None] * len(closes)
    pk = pd = 50.0
    for i in range(len(closes)):
        if rsv[i] is None:
            continue
        pk = (m1 - 1) / m1 * pk + 1.0 / m1 * rsv[i]
        pd = (m2 - 1) / m2 * pd + 1.0 / m2 * pk
        k[i], d[i], j[i] = pk, pd, 3.0 * pk - 2.0 * pd
    return k, d, j

def rsi(closes, n=6):
    gain = [None] * len(closes)
    loss = [None] * len(closes)
    prev = None
    for i, c in enumerate(closes):
        if c is None:
            continue
        if prev is not None:
            diff = c - prev
            gain[i] = max(diff, 0.0)
            loss[i] = max(-diff, 0.0)
        prev = c
    ag, al = rma(gain, n), rma(loss, n)
    out = [None] * len(closes)
    for i in range(len(closes)):
        if ag[i] is None or al[i] is None:
            continue
        if al[i] == 0:
            out[i] = 100.0 if ag[i] > 0 else 50.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + ag[i] / al[i])
    return out

def wr(highs, lows, closes, n):
    hh, ll = hhv(highs, n), llv(lows, n)
    out = [None] * len(closes)
    for i in range(len(closes)):
        if hh[i] is None or ll[i] is None or closes[i] is None:
            continue
        rng = hh[i] - ll[i]
        out[i] = 50.0 if rng == 0 else (hh[i] - closes[i]) / rng * 100.0
    return out

def bias(closes, n):
    ma = sma(closes, n)
    out = [None] * len(closes)
    for i in range(len(closes)):
        if ma[i] is None or closes[i] is None or ma[i] == 0:
            continue
        out[i] = (closes[i] - ma[i]) / ma[i] * 100.0
    return out

def cci(highs, lows, closes, n=14):
    tp = [None] * len(closes)
    for i in range(len(closes)):
        if highs[i] is None or lows[i] is None or closes[i] is None:
            continue
        tp[i] = (highs[i] + lows[i] + closes[i]) / 3.0
    ma = sma(tp, n)
    out = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        if ma[i] is None or tp[i] is None:
            continue
        seg = tp[i - n + 1:i + 1]
        if any(v is None for v in seg):
            continue
        md = sum(abs(v - ma[i]) for v in seg) / n
        out[i] = 0.0 if md == 0 else (tp[i] - ma[i]) / (0.015 * md)
    return out

def _true_range(highs, lows, closes):
    tr = [None] * len(closes)
    prev = None
    for i in range(len(closes)):
        h, l, c = highs[i], lows[i], closes[i]
        if h is None or l is None or c is None:
            prev = c
            continue
        if prev is None:
            tr[i] = h - l
        else:
            tr[i] = max(h - l, abs(h - prev), abs(l - prev))
        prev = c
    return tr

def atr(highs, lows, closes, n=14):
    return rma(_true_range(highs, lows, closes), n)

def dmi(highs, lows, closes, n=14):
    size = len(closes)
    pdm = [None] * size
    ndm = [None] * size
    for i in range(1, size):
        h, l = highs[i], lows[i]
        ph, pl = highs[i - 1], lows[i - 1]
        if None in (h, l, ph, pl):
            continue
        up_move, dn_move = h - ph, pl - l
        pdm[i] = up_move if (up_move > dn_move and up_move > 0) else 0.0
        ndm[i] = dn_move if (dn_move > up_move and dn_move > 0) else 0.0
    tr = _true_range(highs, lows, closes)
    atr_n = rma(tr, n)
    sp = rma(pdm, n)
    sn = rma(ndm, n)
    dip = [None] * size
    dim = [None] * size
    dx = [None] * size
    for i in range(size):
        if atr_n[i] is None or atr_n[i] == 0 or sp[i] is None or sn[i] is None:
            continue
        dip[i] = 100.0 * sp[i] / atr_n[i]
        dim[i] = 100.0 * sn[i] / atr_n[i]
        s = dip[i] + dim[i]
        dx[i] = 0.0 if s == 0 else 100.0 * abs(dip[i] - dim[i]) / s
    return dip, dim, rma(dx, n)

def obv(closes, vols):
    out = [None] * len(closes)
    cur = 0.0
    prev = None
    for i in range(len(closes)):
        c, v = closes[i], vols[i]
        if c is None or v is None:
            continue
        if prev is not None:
            if c > prev:
                cur += v
            elif c < prev:
                cur -= v
        out[i] = cur
        prev = c
    return out

def dpo(closes, n=20):
    shift = n // 2 + 1
    ma = sma(closes, n)
    out = [None] * len(closes)
    for i in range(len(closes)):
        j = i - shift
        if j < 0 or closes[j] is None or ma[i] is None:
            continue
        out[i] = closes[j] - ma[i]
    return out

def vol_tide(rows, short=6, long_n=20):
    size = len(rows)
    net = [None] * size
    amt = [None] * size
    for i, r in enumerate(rows):
        o, c, a = _f((r or {}).get("open")), _f((r or {}).get("close")), _f((r or {}).get("amount"))
        if a is None or o is None or c is None or a <= 0:
            continue
        d = 1.0 if c > o else (-1.0 if c < o else 0.0)
        net[i] = d * a
        amt[i] = a

    wave = [None] * size
    tide = [None] * size
    for n, sink in ((short, wave), (long_n, tide)):
        for i in range(n - 1, size):
            sn, sa = 0.0, 0.0
            ok = True
            for k in range(i - n + 1, i + 1):
                if net[k] is None or amt[k] is None:
                    ok = False
                    break
                sn += net[k]
                sa += amt[k]
            if ok and sa > 0:
                sink[i] = 100.0 * sn / sa
    bar = [None] * size
    for i in range(size):
        if wave[i] is not None and tide[i] is not None:
            bar[i] = wave[i] - tide[i]
    return wave, tide, bar

def compute_all(rows):
    rows = rows or []
    if not rows:
        return {}
    c = _col(rows, "close")
    h = _col(rows, "high")
    l = _col(rows, "low")
    v = _col(rows, "volume")

    out = {}

    for n in PARAMS["ma"]:
        out["ma%d" % n] = [_r(x, 3) for x in sma(c, n)]
    mid, up, low = boll(c, PARAMS["boll"][0], PARAMS["boll"][1])
    out["boll_mid"] = [_r(x, 3) for x in mid]
    out["boll_up"] = [_r(x, 3) for x in up]
    out["boll_low"] = [_r(x, 3) for x in low]
    u, d = td9(c, PARAMS["td9"])
    out["td9_up"] = u
    out["td9_down"] = d

    out["vol"] = [_r(x, 0) for x in v]
    for n in PARAMS["vol_ma"]:
        out["vol_ma%d" % n] = [_r(x, 0) for x in sma(v, n)]

    dif, dea, bar = macd(c, *PARAMS["macd"])
    out["macd_dif"] = [_r(x, 4) for x in dif]
    out["macd_dea"] = [_r(x, 4) for x in dea]
    out["macd_bar"] = [_r(x, 4) for x in bar]

    k, dd, j = kdj(h, l, c, *PARAMS["kdj"])
    out["kdj_k"] = [_r(x, 2) for x in k]
    out["kdj_d"] = [_r(x, 2) for x in dd]
    out["kdj_j"] = [_r(x, 2) for x in j]

    for n in PARAMS["rsi"]:
        out["rsi%d" % n] = [_r(x, 2) for x in rsi(c, n)]
    for n in PARAMS["wr"]:
        out["wr%d" % n] = [_r(x, 2) for x in wr(h, l, c, n)]
    for n in PARAMS["bias"]:
        out["bias%d" % n] = [_r(x, 2) for x in bias(c, n)]

    out["cci"] = [_r(x, 2) for x in cci(h, l, c, PARAMS["cci"])]
    dip, dim, adx = dmi(h, l, c, PARAMS["dmi"])
    out["di_plus"] = [_r(x, 2) for x in dip]
    out["di_minus"] = [_r(x, 2) for x in dim]
    out["adx"] = [_r(x, 2) for x in adx]
    out["atr"] = [_r(x, 4) for x in atr(h, l, c, PARAMS["atr"])]
    out["obv"] = [_r(x, 0) for x in obv(c, v)]
    out["dpo"] = [_r(x, 4) for x in dpo(c, PARAMS["dpo"])]

    wv, td, tb = vol_tide(rows, *PARAMS["tide"])
    out["tide_wave"] = [_r(x, 2) for x in wv]
    out["tide_tide"] = [_r(x, 2) for x in td]
    out["tide_bar"] = [_r(x, 2) for x in tb]

    return out
