import threading
import time

from fastapi import HTTPException, Request

import settings

_RATE_BUCKETS: dict = {}
_RATE_LOCK = threading.Lock()

def _rate_hit(key: str, limit: int, window_sec: int):
    now = time.time()
    with _RATE_LOCK:
        if len(_RATE_BUCKETS) > 10000:
            for k in [k for k, v in _RATE_BUCKETS.items() if now - v[0] > window_sec * 2]:
                _RATE_BUCKETS.pop(k, None)
        start, cnt = _RATE_BUCKETS.get(key, (now, 0))
        if now - start > window_sec:
            start, cnt = now, 0
        cnt += 1
        _RATE_BUCKETS[key] = (start, cnt)
        if cnt > limit:
            return False, int(window_sec - (now - start)) + 1
        return True, 0

def _is_proxy_hop(ip: str) -> bool:
    try:
        import ipaddress
        a = ipaddress.ip_address((ip or "").strip())
        return bool(a.is_loopback or a.is_private or a.is_link_local)
    except ValueError:
        return False

def _client_ip(request: Request) -> str:
    direct = request.client.host if request.client else ""
    xff = request.headers.get("x-forwarded-for", "")
    if xff and _is_proxy_hop(direct):
        first = xff.split(",")[0].strip()
        if first:
            return first
    return direct

def _too_many(key: str, limit: int, window_sec: int):
    ok, retry = _rate_hit(key, limit, window_sec)
    if not ok:
        return HTTPException(status_code=429, detail=f"操作过于频繁，请 {max(retry, 1)} 秒后再试")
    return None

def _rl(name: str, default: int) -> int:
    try:
        v = int(str((settings.get_rate_limits() or {}).get(name) or "").strip() or default)
        return v if v >= 0 else default
    except Exception:
        return default

def _ip_blacklisted(ip: str) -> bool:
    raw = str((settings.get_rate_limits() or {}).get("ip_blacklist") or "")
    if not raw.strip():
        return False
    entries = {e.strip() for e in raw.split(",") if e.strip()}
    return (ip or "").strip() in entries
