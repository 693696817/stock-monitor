import re
import html as _html
import datetime
import requests

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_MAX_BYTES = 1_500_000

_ICP_RE = re.compile(r"[\u4e00-\u9fa5]{0,4}ICP\s*(?:备|证)\s*[0-9]{4,12}\s*号(?:\s*-\s*\d+)?", re.I)
_BEIAN_RE = re.compile(r"[\u4e00-\u9fa5]{0,6}公网安备\s*[0-9]{8,20}\s*号?", re.I)

def _norm_url(url):
    u = (url or "").strip()
    if not u:
        return None
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u.lstrip("/")
    if not re.match(r"^https?://[^/\s]+", u, re.I):
        return None
    return u

def _detect_encoding(resp, raw):
    ct = (resp.headers.get("Content-Type") or "").lower()
    m = re.search(r"charset\s*=\s*[\"']?([\w\-]+)", ct)
    if m:
        return m.group(1)
    head = raw[:4096]
    m = re.search(br"""<meta[^>]+charset\s*=\s*["']?\s*([\w\-]+)""", head, re.I)
    if m:
        try:
            return m.group(1).decode("ascii", "ignore")
        except Exception:
            pass
    m = re.search(br"""charset\s*=\s*["']?\s*([\w\-]+)""", head, re.I)
    if m:
        try:
            return m.group(1).decode("ascii", "ignore")
        except Exception:
            pass
    return resp.apparent_encoding or "utf-8"

def _clean(s, limit=400):
    if not s:
        return None
    s = _html.unescape(str(s))
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    return s[:limit]

def _meta(text, name=None, prop=None):
    if name:
        pat = (r"""<meta[^>]+name\s*=\s*["']?%s["']?[^>]*content\s*=\s*["']([^"']*)["']"""
               % re.escape(name))
        m = re.search(pat, text, re.I)
        if m:
            return _clean(m.group(1))
        pat2 = (r"""<meta[^>]+content\s*=\s*["']([^"']*)["'][^>]*name\s*=\s*["']?%s["']?"""
                % re.escape(name))
        m = re.search(pat2, text, re.I)
        if m:
            return _clean(m.group(1))
    if prop:
        pat = (r"""<meta[^>]+property\s*=\s*["']?%s["']?[^>]*content\s*=\s*["']([^"']*)["']"""
               % re.escape(prop))
        m = re.search(pat, text, re.I)
        if m:
            return _clean(m.group(1))
    return None

def _strip_tags(text):
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return _html.unescape(text)

def _nav_links(text, base):
    out, seen = [], set()
    for m in re.finditer(r"""(?is)<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", text):
        href, inner = m.group(1).strip(), _strip_tags(m.group(2))
        label = _clean(inner, 40)
        if not label or len(label) < 2 or len(label) > 14:
            continue
        if re.match(r"^(javascript:|mailto:|tel:|#)", href, re.I):
            continue
        if label in seen:
            continue
        if re.fullmatch(r"[\d\s\-_.]+", label):
            continue
        if label.lower() in {"more", "更多", "detail", "详情", "next", "prev", "上一页", "下一页"}:
            continue
        seen.add(label)
        if href.startswith("//"):
            href = "http:" + href
        elif href.startswith("/"):
            href = base.rstrip("/") + href
        elif not re.match(r"^https?://", href, re.I):
            href = base.rstrip("/") + "/" + href.lstrip("./")
        out.append({"text": label, "url": href})
        if len(out) >= 18:
            break
    return out

def parse_website(url, timeout=8):
    u = _norm_url(url)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if not u:
        return {"ok": False, "url": url, "error": "官网地址为空或格式不正确", "fetched_at": now}
    try:
        resp = requests.get(u, headers=_HEADERS, timeout=timeout,
                            allow_redirects=True, stream=True)
        raw = b""
        for chunk in resp.iter_content(65536):
            raw += chunk
            if len(raw) >= _MAX_BYTES:
                break
        resp.close()
    except requests.exceptions.SSLError as e:
        return {"ok": False, "url": u, "error": f"SSL 握手失败：{str(e)[:120]}", "fetched_at": now}
    except requests.exceptions.Timeout:
        return {"ok": False, "url": u, "error": f"请求超时（{timeout}s）", "fetched_at": now}
    except Exception as e:
        return {"ok": False, "url": u, "error": f"{type(e).__name__}: {str(e)[:120]}",
                "fetched_at": now}

    status = resp.status_code
    if status >= 400:
        return {"ok": False, "url": u, "final_url": resp.url, "http_status": status,
                "error": f"官网返回 HTTP {status}", "fetched_at": now}

    enc = _detect_encoding(resp, raw)
    try:
        text = raw.decode(enc, errors="replace")
    except (LookupError, TypeError):
        text = raw.decode("utf-8", errors="replace")

    final_url = resp.url or u
    base = re.match(r"^(https?://[^/]+)", final_url)
    base = base.group(1) if base else final_url

    title = None
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if m:
        title = _clean(_strip_tags(m.group(1)), 160)

    desc = _meta(text, name="description") or _meta(text, prop="og:description")
    kw = _meta(text, name="keywords")
    og_title = _meta(text, prop="og:title")
    og_site = _meta(text, prop="og:site_name")

    h1 = None
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", text)
    if m:
        h1 = _clean(_strip_tags(m.group(1)), 120)

    plain = _strip_tags(text)
    plain_compact = re.sub(r"\s+", " ", plain)

    icp = None
    m = _ICP_RE.search(plain_compact)
    if m:
        icp = _clean(m.group(0), 60)
    beian = None
    m = _BEIAN_RE.search(plain_compact)
    if m:
        beian = _clean(m.group(0), 60)

    copyright_txt = None
    m = re.search(r"(?:©|&copy;|Copyright|版权所有)[^。|]{0,80}", plain_compact, re.I)
    if m:
        seg = m.group(0)
        for stop in ("著作权声明", "网络支持", "友情链接", "ICP", "icp", "公网安备"):
            i = seg.find(stop)
            if i > 8:
                seg = seg[:i]
        copyright_txt = _clean(seg, 90)

    langs = []
    if re.search(r"(?i)>\s*(English|EN)\s*<", text):
        langs.append("English")
    if re.search(r"(?i)>\s*(繁體|繁体)", text):
        langs.append("繁體")

    return {
        "ok": True,
        "url": u,
        "final_url": final_url,
        "http_status": status,
        "https": final_url.lower().startswith("https://"),
        "encoding": enc,
        "size_kb": round(len(raw) / 1024, 1),
        "server": _clean(resp.headers.get("Server"), 60),
        "powered_by": _clean(resp.headers.get("X-Powered-By"), 60),
        "title": title,
        "og_title": og_title,
        "site_name": og_site,
        "description": desc,
        "keywords": kw,
        "h1": h1,
        "icp": icp,
        "public_security_record": beian,
        "copyright": copyright_txt,
        "languages": langs,
        "nav": _nav_links(text, base),
        "text_length": len(plain_compact),
        "fetched_at": now,
    }

if __name__ == "__main__":
    import sys
    import json
    target = sys.argv[1] if len(sys.argv) > 1 else "http://www.ganfenglithium.com"
    print(json.dumps(parse_website(target), ensure_ascii=False, indent=2))
