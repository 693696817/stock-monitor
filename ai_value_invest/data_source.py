
import warnings
import requests
import pandas as pd

from config import (
    TUSHARE_TOKEN,
    DATAHUB_BASE_URL,
    DATAHUB_API_KEY,
)

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

class _ProxyPro:

    def __init__(self, base, key, verify):
        self._base = base
        self._key = key
        self._verify = verify

    def __getattr__(self, api_name):
        def caller(**params):
            return _proxy_call(self._base, self._key, api_name, params, self._verify)
        caller.__name__ = api_name
        return caller

def _proxy_call(base, key, api_name, params, verify):
    resp = requests.get(
        f"{base}/{api_name}",
        params=params,
        headers={"X-API-Key": key},
        timeout=30,
        verify=verify,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(
            f"聚合API[{api_name}] 失败: code={body.get('code')} msg={body.get('msg')}"
        )
    payload = body.get("data") or {}
    fields = payload.get("fields") or []
    items = payload.get("items") or []
    df = pd.DataFrame(items, columns=fields)
    if "limit" in params:
        try:
            df = df.head(int(params["limit"]))
        except (TypeError, ValueError):
            pass
    return df

def _official_pro():
    import tushare as ts
    token = settings.get_setting("TUSHARE_TOKEN", TUSHARE_TOKEN)
    ts.set_token(token)
    return ts.pro_api()

def get_pro():
    if settings.get_active_data_source() == "tushare":
        return _official_pro()
    base, key = _active_proxy()
    return _ProxyPro(base, key, verify=False)

def get_pro_bar():
    if settings.get_active_data_source() == "tushare":
        import tushare as ts
        return ts.pro_bar

    base, key = _active_proxy()
    verify = False

    def _proxy_pro_bar(**params):
        params = dict(params)
        adj = params.pop("adj", None)
        if adj:
            warnings.warn(
                f"聚合API的 pro_bar 不支持 adj={adj!r}（会触发 500），"
                f"已自动回退为未复权日线（daily）。如需前复权，请改用官方 Tushare。"
            )
        return _proxy_call(base, key, "daily", params, verify)

    _proxy_pro_bar.__name__ = "pro_bar"
    return _proxy_pro_bar

def _active_proxy():
    chans = settings.get_data_source_channels()
    active = settings.get_active_data_source()
    chan = next((c for c in chans if c.get("id") == active and c.get("enabled")), None)
    if not chan:
        chan = next((c for c in chans if c.get("enabled")), None)
    if not chan:
        raise RuntimeError(
            "未配置可用的金融数据源代理渠道：请在后台「设置中心」添加并启用一个代理渠道。"
        )
    return chan["base_url"], chan["api_key"]

def fetch_news_datahub(api_name, src, start_date, end_date, limit=100, timeout=20):
    base = (DATAHUB_BASE_URL or "").rstrip("/")
    key = DATAHUB_API_KEY or ""
    if not base or not key:
        return None, "disabled"
    def _fmt(v):
        if hasattr(v, "strftime"):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        s = str(v or "")
        if " " in s:
            return s
        d = "".join(filter(str.isdigit, s))
        if len(d) == 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:8]} 00:00:00"
        return s
    sd, ed = _fmt(start_date), _fmt(end_date)
    try:
        resp = requests.get(
            f"{base}/{api_name}",
            params={
                "src": src,
                "start_date": sd,
                "end_date": ed,
                "limit": limit,
            },
            headers={"X-API-Key": key},
            timeout=timeout,
            verify=False,
        )
    except Exception as e:
        print(f"⚠️ [News] DATAHUB {api_name} 请求异常: {type(e).__name__}: {e}")
        return None, "error"
    try:
        body = resp.json()
    except Exception:
        body = None
    if body is None:
        if resp.status_code != 200:
            print(f"⚠️ [News] DATAHUB {api_name} HTTP {resp.status_code}: {resp.text[:160]}")
        return None, "error"
    code = body.get("code")
    if code != 0:
        msg = str(body.get("msg") or "")
        if ("没有" in msg and "权限" in msg) or ("未" in msg and "权限" in msg) or "无权限" in msg:
            print(f"⚠️ [News] DATAHUB {api_name} 无权限(code={code}): {msg}")
            return None, "no_permission"
        if "频率" in msg or "限频" in msg or "频繁" in msg or "过多" in msg or "超过" in msg:
            print(f"⚠️ [News] DATAHUB {api_name} 限速(code={code}): {msg}")
            return None, "rate_limit"
        print(f"⚠️ [News] DATAHUB {api_name} 不可用(code={code}): {msg}")
        return None, "error"
    payload = body.get("data")
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        fields = payload.get("fields") or []
        items = payload.get("items") or []
        rows = [dict(zip(fields, it)) for it in items] if fields else items
    else:
        rows = []
    if not rows:
        return None, "empty"
    return pd.DataFrame(rows), "ok"

_DEPRECATED_DATAHUB_APIS = frozenset({
})

def fetch_datahub(api_name, params=None, limit=None, timeout=30):
    if api_name in _DEPRECATED_DATAHUB_APIS:
        return None, "deprecated"
    base = (DATAHUB_BASE_URL or "").rstrip("/")
    key = DATAHUB_API_KEY or ""
    if not base or not key:
        return None, "disabled"
    params = dict(params or {})
    if limit is not None:
        params.setdefault("limit", limit)
    try:
        resp = requests.get(
            f"{base}/{api_name}",
            params=params,
            headers={"X-API-Key": key},
            timeout=timeout,
            verify=False,
        )
        resp.raise_for_status()
        body = resp.json()
        code = body.get("code")
        if code != 0:
            msg = str(body.get("msg") or "")
            cstr = str(code)
            if ("无" in msg and "权限" in msg) or "40203" in cstr:
                print(f"⚠️ [DataHub] {api_name} 无权限(code={code}): {msg}")
                return None, "no_permission"
            if "频率" in msg or "限" in msg or "40203" in cstr:
                print(f"⚠️ [DataHub] {api_name} 限速(code={code}): {msg}")
                return None, "rate_limit"
            if "接口名" in msg or "40101" in cstr:
                print(f"⚠️ [DataHub] {api_name} 接口名未开放(code={code}): {msg}")
                return None, "no_permission"
            print(f"⚠️ [DataHub] {api_name} 不可用(code={code}): {msg}")
            return None, "error"
        payload = body.get("data")
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            fields = payload.get("fields") or []
            items = payload.get("items") or []
            rows = [dict(zip(fields, it)) for it in items] if fields else items
        else:
            rows = []
        if not rows:
            return None, "empty"
        df = pd.DataFrame(rows)
        if "limit" in params:
            try:
                df = df.head(int(params["limit"]))
            except (TypeError, ValueError):
                pass
        return df, "ok"
    except Exception as e:
        print(f"⚠️ [DataHub] {api_name} 异常: {type(e).__name__}: {e}")
        return None, "error"

DISCLOSURE_PAGE = 5000
DISCLOSURE_MAX_PAGES = 6

def fetch_disclosure_rows(ts_code=None, end_date=None, start_date=None, limit=None, timeout=45):
    base = {}
    if ts_code:
        base["ts_code"] = ts_code
    if end_date:
        base["end_date"] = end_date
        base["start_date"] = start_date or end_date

    want = int(limit) if limit else None
    page = DISCLOSURE_PAGE if (want is None or want > DISCLOSURE_PAGE) else want
    frames, offset = [], 0
    for _ in range(DISCLOSURE_MAX_PAGES):
        params = dict(base)
        if offset:
            params["offset"] = offset
        df, st = fetch_datahub("disclosure_date", params, limit=page, timeout=timeout)
        if st != "ok" or df is None or getattr(df, "empty", True):
            break
        frames.append(df)
        if len(df) < page:
            break
        offset += page
        if want and offset >= want:
            break
    if not frames:
        return []
    try:
        df = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)
    except Exception:
        df = frames[0]

    def _s(v):
        s = "" if v is None else str(v).strip()
        return "" if s.lower() in ("nan", "none", "nat") else s

    out = []
    for _, r in df.iterrows():
        code = _s(r.get("ts_code"))
        if not code:
            continue
        out.append({
            "ts_code": code,
            "end_date": _s(r.get("end_date")),
            "pre_date": _s(r.get("pre_date")),
            "actual_date": _s(r.get("actual_date")),
            "ann_date": _s(r.get("ann_date")),
        })
    return out
