import time
import threading
import requests

try:
    import config
except Exception:
    config = None

BASE = "https://open.lixinger.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Content-Type": "application/json",
    "Accept-Encoding": "gzip, deflate, br, *",
}

class LixingerError(Exception):

    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code

class LixingerClient:
    def __init__(self, token=None, timeout=30):
        self.token = (token or (config and getattr(config, "LIXINGER_TOKEN", "")) or "").strip()
        self.timeout = timeout
        self._lock = threading.Lock()
        self._min_interval = 1.0 / 36.0
        self._last_call = 0.0
        self._minute_count = 0
        self._minute_start = time.time()
        self._sess = requests.Session()
        try:
            from requests.adapters import HTTPAdapter
            self._sess.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0))
        except Exception:
            pass

    def _rate_limit(self):
        with self._lock:
            now = time.time()
            delta = now - self._last_call
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last_call = time.time()
            if now - self._minute_start >= 60:
                self._minute_start = now
                self._minute_count = 0
            self._minute_count += 1
            if self._minute_count > 950:
                sleep = 60 - (time.time() - self._minute_start) + 1.0
                if sleep > 0:
                    time.sleep(sleep)
                self._minute_start = time.time()
                self._minute_count = 0

    def _request(self, path, body):
        if not self.token:
            raise LixingerError("未配置 LIXINGER_TOKEN", code="no_token")
        url = f"{BASE}/api/{path}"
        payload = dict(body)
        payload["token"] = self.token
        self._rate_limit()
        backoff = [1, 2, 4, 8, 16]
        last_err = None
        for attempt in range(6):
            try:
                r = self._sess.post(url, json=payload, headers=HEADERS, timeout=self.timeout)
            except Exception as e:
                last_err = e
                if attempt < 5:
                    time.sleep(backoff[min(attempt, 4)])
                    continue
                raise LixingerError(f"网络异常: {e}")
            sc = r.status_code
            if sc == 429:
                time.sleep(1.0)
                continue
            if 500 <= sc < 600:
                if attempt < 5:
                    time.sleep(backoff[min(attempt, 4)])
                    continue
                raise LixingerError(f"服务端错误 {sc}", status=sc)
            if sc >= 400:
                raise LixingerError(f"HTTP {sc}: {r.text[:200]}", status=sc)
            try:
                j = r.json()
            except Exception as e:
                raise LixingerError(f"响应非 JSON: {e}")
            code = j.get("code")
            if code == 1:
                return j.get("data")
            raise LixingerError(f"业务错误 code={code} msg={j.get('message')}", code=code)
        raise LixingerError(f"重试耗尽: {last_err}")

    def get(self, path, **body):
        return self._request(path, body)

_CLIENT = None

def get_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = LixingerClient()
    return _CLIENT

def reset_client():
    global _CLIENT
    _CLIENT = None
