import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_CHINA_NO_PROXY = (
    "datahubco.com,fuyao.aicubes.cn,aicubes.cn,open.lixinger.com,lixinger.com,"
    "eastmoney.com,push2.eastmoney.com,push2his.eastmoney.com,sinajs.cn,sina.com.cn,"
    "sinajs.com,sinaimg.cn,10jqka.com.cn,iwencai.com,ths.com.cn,gtimg.cn,qq.com,"
    "akshare.akfamily.xyz,akfamily.xyz,"
    "volces.com,volcengineapi.com,bigmodel.cn,zhipuai.cn,qnaigc.com,siliconflow.cn,"
    "aliyuncs.com,dashscope.aliyuncs.com,moonshot.cn,minimaxi.com,minimax.chat,"
    "baidubce.com,jd.com,jdcloud.com,deepseek.com,"
    "localhost,127.0.0.1,0.0.0.0,::1"
)
import os as _os
for _pk in ("NO_PROXY", "no_proxy"):
    _prev = (_os.environ.get(_pk) or "").strip()
    _os.environ[_pk] = f"{_prev},{_CHINA_NO_PROXY}".strip(",") if _prev else _CHINA_NO_PROXY

from fastapi import FastAPI, Request, HTTPException, Response, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse, FileResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from pydantic import BaseModel
import uvicorn
import json
import tushare as ts
import akshare as ak
import asyncio
import threading
import time
import datetime
import os
import re
from urllib.parse import quote
import pandas as pd

from data_service import get_stock_code, get_stock_data_summary, get_market_rank_data, get_market_rank_data_sync, get_news_data, get_opportunities_data, get_risk_data, get_market_overview_datahub, SENTIMENT_ZONES, fetch_watch_quotes_sync, resolve_data_groups, DATA_GROUPS
import data_service
from data_source import get_pro
import fuyao_client
from ai_service import analyze_stock_stream
import ai_service
from report_postprocess import (postprocess_report, strip_ai_opener,
                                extract_backtest_json, BT_MARKER, backtest_block_end,
                                detect_truncation)
from config import PDF_DIR, SESSION_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD
import config
from auth import (
    init_db, create_user, authenticate, get_current_user, find_user_by_identifier,
    set_session_cookie, clear_session_cookie, upgrade_membership,
    record_analysis, get_today_counts, get_analysis_history,
    get_analysis_history_page,
    get_analysis_total, get_invite_count, get_user_by_email,
    update_profile, get_effective_tier, TIERS, to_public, ensure_admin,
    record_login, get_user_by_phone, get_bonus, set_bonus, consume_bonus_atomic,
    update_user_admin, delete_user, count_admins, get_user_by_id, redeem_code,
    deep_quota_state,
    create_user_admin, update_analysis_report, get_analysis_by_id,
    get_analysis_by_id_any, is_phone_email, mask_phone,
    reset_password_by_email, reset_password_by_phone,
    add_watch, remove_watch, list_watch,
    is_watched, list_user_orders, refund_analysis,
)
import auth

from sms_service import send_code, verify_code, is_valid_mobile
from db import (
    insert_feedback, list_feedback, vote_feedback,
    get_admin_stats, list_users, list_analysis_records, update_feedback_status,
    list_login_logs, list_membership_orders, list_invite_records,
    ensure_stocks_table, search_stocks, count_stocks, list_stocks,
    ensure_analysis_status_columns, mark_analysis_failed,
    ensure_analysis_quota_source_column,
    ensure_redeem_codes_table, create_redeem_codes, list_redeem_codes,
    redeem_code_stats, void_redeem_codes, format_redeem_code,
    ensure_notifications_table, create_notification, list_user_notifications,
    count_unread_notifications, mark_notification_read, mark_all_notifications_read,
    list_admin_notifications, delete_notification, scan_membership_expiry,
    notification_visible,
    get_stock_by_ts_code, get_site_stats, list_all_stock_basics,
    list_disclosure_window, list_disclosure_by_stock, get_next_disclosure,
    upsert_market_vote, get_market_vote_stats, get_user_market_vote,
    list_news, increment_news_likes,
    get_user_profile, adjust_bonus, list_bonus_logs,
    get_news_by_gid, delete_news, set_news_pinned, increment_news_views,
    add_alert, list_alerts, get_alert, update_alert, delete_alert,
    count_unread_alerts, list_triggered_alerts, update_watch_meta,
    BACKTEST_PREFERENCES, save_analysis_valuation, list_analysis_valuations,
    get_valuation_summary, get_valuation_detail, delete_analysis_valuation,
    get_user_valuation_dashboard,
)
import db
from data_source import fetch_datahub
import stock_detail_service as stock_detail
import settings
import legal_pages as legal
from settings import init_settings, all_settings, apply_runtime_settings, get_analysis_preferences
from stock_universe import sync_stock_universe, get_sync_state, trigger_sync
from core.refresh import refresh_analysis_preferences, refresh_site_settings, refresh_pricing
from routers.admin import router as admin_router
from core.security import require_admin
from core.serialize import _feedback_to_public, _FEEDBACK_STATUS_MAP, _FEEDBACK_STATUS_REV
from core.guard import _model_meta_wipe_check
from routers.legal import router as legal_router

from core.templates import templates, _sb, _static_version, STATIC_DIR
from core.ratelimit import (_client_ip, _too_many, _rl, _rate_hit,
                            _ip_blacklisted, _is_proxy_hop)

@asynccontextmanager
async def lifespan(app):
    init_db()
    ensure_analysis_status_columns()
    ensure_analysis_quota_source_column()
    ensure_redeem_codes_table()
    ensure_notifications_table()
    init_settings()
    refresh_site_settings(app)
    refresh_pricing(app)
    refresh_analysis_preferences(app)
    ensure_admin(ADMIN_EMAIL, ADMIN_PASSWORD)
    start_notification_scheduler(86400, run_now=True)
    data_service.init_news()
    data_service.init_rank()
    data_service.init_alerts()
    data_service.init_disclosure_sync()
    await _refresh_market_cache()
    warmer = asyncio.create_task(_market_cache_warmer())
    backfiller = asyncio.create_task(_valuation_backfill_worker())
    try:
        yield
    finally:
        warmer.cancel()
        backfiller.cancel()

app = FastAPI(title="A股棱镜", lifespan=lifespan)

def _warn_unreachable_proxy():
    import socket as _sk
    from urllib.parse import urlparse as _up
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        raw = os.environ.get(var) or os.environ.get(var.lower())
        if not raw:
            continue
        try:
            u = _up(raw if "//" in raw else "//" + raw)
            port = u.port
            if not port:
                continue
            with _sk.create_connection((u.hostname or "127.0.0.1", port), timeout=1.5):
                pass
        except Exception:
            print(f"[startup] ⚠️ 代理 {var}={raw} 不可达！所有外部请求（大模型/行情/财务）"
                  f"都会走它并失败。请确认宿主工具是否在跑，或在启动前 unset {var}。",
                  flush=True)

_warn_unreachable_proxy()

_LOGIN_EXEMPT = {
    "/", "/login", "/register", "/pricing", "/doc",
    "/favicon.ico", "/robots.txt", "/sitemap.xml",
    "/privacy", "/terms", "/disclaimer", "/cookies",
    "/refund", "/about", "/contact", "/help",
}

_PUBLIC_PREFIXES = ("/stock/", "/calendar")

@app.middleware("http")
async def require_login_middleware(request: Request, call_next):
    path = request.url.path
    _bl_ip = _client_ip(request)
    if _bl_ip and _ip_blacklisted(_bl_ip):
        _bl_user = get_current_user(request)
        if not (_bl_user and bool(_bl_user.get("is_admin"))):
            return JSONResponse(status_code=403, content={"detail": "访问被拒绝"})
    request.state.seo_noindex = not (
        path.startswith("/static") or path.startswith("/api")
        or path in _LOGIN_EXEMPT or path.startswith(_PUBLIC_PREFIXES)
    )
    if path.startswith("/static") or path.startswith("/api"):
        return await call_next(request)
    if path in _LOGIN_EXEMPT or path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)
    if not get_current_user(request):
        target = request.url.path
        if request.url.query:
            target += "?" + request.url.query
        resp = RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=302)
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp
    return await call_next(request)

app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def static_cache_middleware(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        if "v=" in request.url.query:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "public, max-age=300"
    return resp

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(admin_router)

app.include_router(legal_router)

if not os.path.exists(PDF_DIR):
    os.makedirs(PDF_DIR)

class AnalyzeRequest(BaseModel):
    query: str
    mode: str = "normal"
    model: str = ""
    preference: str = "long_term_value"

class PDFRequest(BaseModel):
    html_content: str
    stock_name: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    user = get_current_user(request)
    try:
        _cnt = await run_in_threadpool(count_stocks)
        stocks_total = (_cnt or {}).get("A") or (_cnt or {}).get("total") or 0
    except Exception:
        stocks_total = 0
    hot_stocks = []
    try:
        rank_data = await run_in_threadpool(data_service.get_market_rank_data_sync)
        hot_stocks = (rank_data or {}).get("hot_stocks", [])[:8]
    except Exception:
        hot_stocks = []
    local_hot_stocks = []
    try:
        if _sb("home.hot_stocks")["options"].get("source") == "local":
            local_hot_stocks = await run_in_threadpool(data_service.get_local_hot_analysis) or []
    except Exception as e:
        print(f"⚠️ [Home] 本站热门分析榜读取失败（热股条降级为同花顺榜）: {e}")
        local_hot_stocks = []
    prefs = getattr(request.app.state, "analysis_preferences", None) or get_analysis_preferences()
    models = getattr(request.app.state, "analysis_models", None) or settings.get_all_ai_models()
    home_user = to_public(user) if user else None
    _bn, _bd = settings.get_register_bonus()
    _qr = settings.get_quota_rules()
    _fdn = _qr.get("free_daily_normal")
    if not isinstance(_fdn, int) or _fdn < 0:
        _fdn = TIERS[0]["normal_daily"]
    return templates.TemplateResponse(
        request,
        "home.html",
        {"request": request, "active_page": "home",
         "is_logged_in": bool(user), "user": home_user,
         "stocks_total": stocks_total,
         "hot_stocks": hot_stocks,
         "local_hot_stocks": local_hot_stocks,
         "analysis_preferences": prefs,
         "analysis_models": models,
         "register_bonus_normal": _bn,
         "register_bonus_deep": _bd,
         "free_daily_normal": _fdn}
    )

@app.get("/analysis", response_class=HTMLResponse)
async def analysis_page(request: Request):
    user = get_current_user(request)
    public_user = to_public(user) if user else None
    if public_user:
        public_user["deep_remain"] = deep_quota_state(
            user["id"], public_user["tier"])[2]["remain"]
    market_data, rank_data = await asyncio.gather(
        run_in_threadpool(get_market_realtime_data),
        run_in_threadpool(get_market_rank_data_sync),
    )
    hot_stocks = (rank_data or {}).get("hot_stocks", [])[:8]
    local_hot_stocks = []
    try:
        if _sb("analysis.hot_stocks")["options"].get("source") == "local":
            local_hot_stocks = await run_in_threadpool(data_service.get_local_hot_analysis) or []
    except Exception as e:
        print(f"⚠️ [Analysis] 本站热门分析榜读取失败（边栏降级为同花顺榜）: {e}")
        local_hot_stocks = []
    return templates.TemplateResponse(
        request,
        "analysis.html",
        {
            "request": request,
            "active_page": "analysis",
            "analysis_models": getattr(request.app.state, "analysis_models", settings.get_all_ai_models()),
            "analysis_preferences": getattr(request.app.state, "analysis_preferences", get_analysis_preferences()),
            "analysis_user": public_user if public_user else None,
            "is_vip": bool(public_user and public_user.get("is_vip")),
            "default_model_id": settings.get_default_ai_model_id(),
            "market_data": market_data,
            "hot_stocks": hot_stocks,
            "local_hot_stocks": local_hot_stocks,
        }
    )

@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    plans = getattr(request.app.state, "pricing", settings.get_pricing_plans()) or []
    sub_plans = [p for p in plans if p.get("type") in ("free", "subscription")]
    payg_plans = [p for p in plans if p.get("type") == "payg"]

    try:
        site_stats = await run_in_threadpool(get_site_stats)
    except Exception:
        site_stats = {"stock_count": 0, "user_count": 0, "report_count": 0, "news_count": 0}
    model_count = len(getattr(request.app.state, "analysis_models", None)
                      or settings.get_all_ai_models() or [])
    pref_count = len(getattr(request.app.state, "analysis_preferences", None)
                     or get_analysis_preferences() or [])

    member = {"logged_in": False, "level": 0, "level_name": "免费版",
              "expiry": "", "active": False, "days_left": 0, "lifetime": False}
    try:
        user = await run_in_threadpool(get_current_user, request)
    except Exception:
        user = None
    if user:
        lvl = int(user.get("membership_level") or 0)
        exp = auth._parse_date(user.get("membership_expiry"))
        today = datetime.date.today()
        active = bool(lvl >= 1 and (exp is None or exp >= today))
        member = {
            "logged_in": True,
            "level": lvl if active else 0,
            "level_name": auth.TIERS.get(lvl if active else 0, {}).get("name", "免费版"),
            "expiry": exp.isoformat() if exp else "",
            "lifetime": bool(active and exp is None),
            "active": active,
            "days_left": (exp - today).days if (active and exp) else 0,
        }

    period_labels = []
    for _p in sub_plans:
        if _p.get("type") == "subscription" and _p.get("prices"):
            period_labels = [str(x.get("label") or "") for x in _p["prices"]]
            break

    return templates.TemplateResponse(
        request,
        "pricing.html",
        {
            "request": request,
            "active_page": "pricing",
            "sub_plans": sub_plans,
            "payg_plans": payg_plans,
            "site_stats": site_stats,
            "model_count": model_count,
            "pref_count": pref_count,
            "member": member,
            "period_labels": period_labels,
        }
    )

_SITEMAP_PATHS = [
    ("/", "1.0", "daily"),
    ("/pricing", "0.8", "weekly"),
    ("/calendar", "0.7", "daily"),
    ("/about", "0.6", "monthly"),
    ("/help", "0.7", "monthly"),
    ("/contact", "0.5", "monthly"),
    ("/privacy", "0.4", "yearly"),
    ("/terms", "0.4", "yearly"),
    ("/disclaimer", "0.4", "yearly"),
    ("/cookies", "0.3", "yearly"),
    ("/refund", "0.3", "yearly"),
]

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "static", "favicon.ico")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="favicon not found")
    return FileResponse(path, media_type="image/vnd.microsoft.icon")

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /api/",
        "Disallow: /profile",
        "Disallow: /analysis/archive/",
        "",
        "Sitemap: /sitemap.xml",
    ]
    return "\n".join(lines)

def _sitemap_lastmod(path: str) -> str:
    try:
        slug = path.lstrip("/")
        if slug in legal.PAGES:
            return legal.UPDATED_AT
    except Exception:
        pass
    template_map = {
        "/": "home.html",
        "/pricing": "pricing.html",
    }
    tpl = template_map.get(path)
    if tpl:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", tpl)
        if os.path.exists(p):
            return datetime.date.fromtimestamp(os.path.getmtime(p)).isoformat()
    return datetime.date.today().isoformat()

_STOCK_SITEMAP = {"ts": 0.0, "rows": []}

def _sitemap_stock_rows():
    now = time.time()
    if _STOCK_SITEMAP["rows"] and now - _STOCK_SITEMAP["ts"] < 6 * 3600:
        return _STOCK_SITEMAP["rows"]
    try:
        rows = list_all_stock_basics() or []
        if rows:
            _STOCK_SITEMAP["rows"] = rows
            _STOCK_SITEMAP["ts"] = now
    except Exception as e:
        print(f"⚠️ [Sitemap] 股票列表读取失败: {e}")
    return _STOCK_SITEMAP["rows"]

@app.get("/sitemap.xml", response_class=Response)
async def sitemap_xml(request: Request):
    site = getattr(request.app.state, "site", {}) or {}
    domain = (site.get("SITE_DOMAIN") or "").rstrip("/")
    if not domain:
        domain = f"{request.url.scheme}://{request.url.netloc}"
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, priority, changefreq in _SITEMAP_PATHS:
        slug = path.lstrip("/")
        if slug in legal.PAGES and not legal.is_indexable(slug):
            continue
        parts.append(
            f"  <url><loc>{domain}{path}</loc><lastmod>{_sitemap_lastmod(path)}</lastmod>"
            f"<changefreq>{changefreq}</changefreq><priority>{priority}</priority></url>"
        )
    for row in _sitemap_stock_rows():
        tsc = str((row or {}).get("ts_code") or "").strip()
        if not tsc:
            continue
        parts.append(
            f"  <url><loc>{domain}/stock/{quote(tsc, safe='')}</loc>"
            f"<changefreq>daily</changefreq><priority>0.6</priority></url>"
        )
    parts.append("</urlset>")
    return Response(content="\n".join(parts), media_type="application/xml")

@app.get("/news", response_class=HTMLResponse)
async def news_page(request: Request):
    return templates.TemplateResponse(
        request,
        "news_flash.html",
        {"request": request, "active_page": "news"}
    )

@app.get("/risks", response_class=HTMLResponse)
async def risks_page(request: Request):
    risk_data = await get_risk_data()
    return templates.TemplateResponse(
        request,
        "risk_warning.html",
        {"request": request, "active_page": "risks", "risk": risk_data}
    )

@app.get("/valuation", response_class=HTMLResponse)
async def valuation_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login?next=/valuation", status_code=302)
    vd = await run_in_threadpool(get_user_valuation_dashboard, user["id"])
    return templates.TemplateResponse(
        request,
        "valuation.html",
        {
            "request": request,
            "active_page": "valuation",
            "user": to_public(user),
            "vd": vd,
        },
    )

@app.get("/hot", response_class=HTMLResponse)
async def hot_page(request: Request):
    rank_data = await get_market_rank_data()
    local_hot = []
    lh_cfg = _sb("hot.local_rank")
    if lh_cfg.get("enabled", True):
        try:
            days = int(lh_cfg.get("options", {}).get("days") or 7)
            limit = int(lh_cfg.get("options", {}).get("limit") or 10)
            local_hot = await run_in_threadpool(data_service.get_local_hot_analysis, days, limit)
        except Exception as e:
            print(f"⚠️ [LocalHot] 获取失败: {e}")
            local_hot = []

    return templates.TemplateResponse(
        request,
        "hot_stocks.html",
        {
            "request": request,
            "active_page": "hot",
            "ranks": rank_data,
            "local_hot": local_hot,
        }
    )

_TS_CODE_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")

def _normalize_ts_code(ts_code: str):
    if not ts_code:
        return None
    ts_code = ts_code.strip().upper()
    m = _TS_CODE_RE.match(ts_code)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    if re.match(r"^\d{6}$", ts_code):
        c = ts_code[0]
        ex = "SH" if c in ("6", "9") else ("BJ" if c in ("4", "8") else "SZ")
        return f"{ts_code}.{ex}"
    return None

@app.get("/stock/{ts_code}", response_class=HTMLResponse)
async def stock_detail_page(request: Request, ts_code: str):
    user = get_current_user(request)
    norm = _normalize_ts_code(ts_code)
    if not norm:
        raise HTTPException(status_code=404, detail="股票代码格式不正确")
    stock_row = await run_in_threadpool(get_stock_by_ts_code, norm)
    stock_name = stock_row.get("name") if stock_row else None
    if not stock_name:
        try:
            pf = await run_in_threadpool(stock_detail.get_profile, norm)
            stock_name = (pf.get("profile") or {}).get("companyName") or norm
        except Exception:
            stock_name = norm
    return templates.TemplateResponse(
        request,
        "stock_detail.html",
        {
            "request": request,
            "active_page": "stock",
            "ts_code": norm,
            "stock_name": stock_name,
            "is_logged_in": bool(user),
            "user": to_public(user) if user else None,
        }
    )

def _stock_guest_rl(request: Request):
    if get_current_user(request):
        return None
    ip = _client_ip(request) or "unknown"
    return _too_many(f"stockapi:ip:{ip}", _rl("stock_api_ip_per_min", 20), 60)

@app.get("/api/stock/{ts_code}/quote")
async def api_stock_quote(request: Request, ts_code: str):
    err = _stock_guest_rl(request)
    if err:
        return JSONResponse(status_code=429, content={"status": "error", "ts_code": ts_code, "msg": err.detail})
    norm = _normalize_ts_code(ts_code)
    if not norm:
        return JSONResponse(status_code=400, content={"status": "error", "msg": "股票代码格式不正确"})
    try:
        q = await run_in_threadpool(stock_detail.get_quote, norm)
        return {"status": "success", "ts_code": norm, "quote": q}
    except Exception as e:
        print(f"⚠️ [StockDetail] quote {norm}: {e}")
        return {"status": "error", "ts_code": norm, "quote": {}, "msg": str(e)}

@app.get("/api/stock/{ts_code}/kline")
async def api_stock_kline(request: Request, ts_code: str, fq: str = "lxr",
                          days: int = 120, period: str = "day"):
    err = _stock_guest_rl(request)
    if err:
        return JSONResponse(status_code=429, content={"status": "error", "ts_code": ts_code, "msg": err.detail})
    norm = _normalize_ts_code(ts_code)
    if not norm:
        return JSONResponse(status_code=400, content={"status": "error", "msg": "股票代码格式不正确"})
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 120
    days = max(1, min(days, 3650))
    try:
        data = await run_in_threadpool(stock_detail.get_kline, norm, fq, days, period)
        return {"status": "success", "ts_code": norm, "fq": fq, **data}
    except Exception as e:
        print(f"⚠️ [StockDetail] kline {norm}: {e}")
        return {"status": "error", "ts_code": norm, "data": [], "error": str(e)}

@app.get("/api/stock/{ts_code}/profile")
async def api_stock_profile(request: Request, ts_code: str):
    err = _stock_guest_rl(request)
    if err:
        return JSONResponse(status_code=429, content={"status": "error", "ts_code": ts_code, "msg": err.detail})
    norm = _normalize_ts_code(ts_code)
    if not norm:
        return JSONResponse(status_code=400, content={"status": "error", "msg": "股票代码格式不正确"})
    try:
        pf = await run_in_threadpool(stock_detail.get_profile, norm)
        return {"status": "success", "ts_code": norm, **pf}
    except Exception as e:
        print(f"⚠️ [StockDetail] profile {norm}: {e}")
        return {"status": "error", "ts_code": norm, "profile": None, "msg": str(e)}

@app.get("/api/stock/{ts_code}/section/{section}")
async def api_stock_section(request: Request, ts_code: str, section: str, force: int = 0):
    norm = _normalize_ts_code(ts_code)
    if not norm:
        return JSONResponse(status_code=400, content={"status": "error", "msg": "股票代码格式不正确"})
    if section not in stock_detail.list_sections():
        return JSONResponse(status_code=404, content={"status": "error", "msg": f"未知板块: {section}"})
    if force:
        u = get_current_user(request)
        force = 1 if (u and u.get("is_admin")) else 0
    try:
        data = await run_in_threadpool(stock_detail.get_section, norm, section, bool(force))
        return {"status": "success", "ts_code": norm, "section": section,
                "forced": bool(force), "data": data}
    except Exception as e:
        print(f"⚠️ [StockDetail] section {section} {norm}: {e}")
        return {"status": "error", "ts_code": norm, "section": section, "data": {}, "msg": str(e)}

@app.get("/api/stock/{ts_code}/disclosure")
async def api_stock_disclosure(request: Request, ts_code: str):
    err = _stock_guest_rl(request)
    if err:
        return JSONResponse(status_code=429, content={"status": "error", "ts_code": ts_code, "msg": err.detail})
    norm = _normalize_ts_code(ts_code)
    if not norm:
        return JSONResponse(status_code=400, content={"status": "error", "msg": "股票代码格式不正确"})
    try:
        data = await run_in_threadpool(stock_detail.get_section, norm, "disclosure", False)
        return {"status": "success", "ts_code": norm, "data": data}
    except Exception as e:
        print(f"⚠️ [StockDetail] disclosure {norm}: {e}")
        return {"status": "error", "ts_code": norm, "data": {}, "msg": str(e)}

def _disclosure_groups(days: int):
    days = max(1, min(int(days or 45), 120))
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=days)).strftime("%Y%m%d")
    end = (today + datetime.timedelta(days=days)).strftime("%Y%m%d")
    try:
        rows = list_disclosure_window(start, end, 800)
    except Exception as e:
        print(f"⚠️ [Disclosure] 日历读取失败: {e}")
        rows = []
    buckets = {}
    for r in rows or []:
        pre = str(r.get("pre_date") or "")
        if not pre:
            continue
        buckets.setdefault(pre, []).append(r)
    groups = []
    for k in sorted(buckets):
        try:
            wd = "周" + "一二三四五六日"[datetime.date(int(k[:4]), int(k[4:6]), int(k[6:])).weekday()]
        except Exception:
            wd = ""
        groups.append({
            "date": k,
            "date_cn": f"{k[:4]}-{k[4:6]}-{k[6:]}",
            "weekday": wd,
            "items": buckets[k],
        })
    return {"days": days, "start": start, "end": end, "groups": groups,
            "total": len(rows or [])}

_PERIOD_TYPE = {"0331": "一季报", "0630": "中报", "0930": "三季报", "1231": "年报"}

@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, days: int = 45):
    user = get_current_user(request)
    data = await run_in_threadpool(_disclosure_groups, days)
    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "request": request,
            "active_page": "calendar",
            "is_logged_in": bool(user),
            "user": to_public(user) if user else None,
            **data,
        },
    )

@app.get("/api/disclosure/calendar")
async def api_disclosure_calendar(days: int = 45, request: Request = None):
    return {"status": "success", **await run_in_threadpool(_disclosure_groups, days)}

MARKET_CACHE = {    "data": None,
    "timestamp": 0
}
MARKET_CACHE_TTL = 30

def get_market_realtime_data():
    global MARKET_CACHE
    now = time.time()
    if MARKET_CACHE["data"] and (now - MARKET_CACHE["timestamp"] < MARKET_CACHE_TTL):
        return MARKET_CACHE["data"]

    try:
        market_data = get_market_overview_datahub(include_fuyao=True)

        MARKET_CACHE["data"] = market_data
        MARKET_CACHE["timestamp"] = time.time()
        print(f"📊 [Market] 数据源=DATAHUB, 交易日={market_data.get('trade_date')}, "
              f"上证={market_data['sh']['price']}({market_data['sh']['change_pct']}%), "
              f"北向={market_data['north_fund']}@{market_data.get('north_date') or '—'}, "
              f"涨/跌/平={market_data['up_count']}/{market_data['down_count']}/{market_data['flat_count']}, "
              f"情绪={market_data['sentiment']}({market_data['sentiment_label']}), "
              f"龙虎榜={market_data['limit_count']}家"
              + (f", 最高连板={(market_data.get('ladder') or {}).get('max_board')}板"
                 f"({(market_data.get('ladder') or {}).get('date')}), "
                 f"人气榜={len(((market_data.get('hot_rank') or {}).get('hot')) or [])}条"
                 if market_data.get("ladder") or market_data.get("hot_rank") else ", 伏尧增强=无"),
              flush=True)
        return market_data

    except Exception as e:
        print(f"Market Data Error: {e}")
        return {
            "sh": _empty_market_index("上证指数"), "sz": _empty_market_index("深证成指"),
            "cy": _empty_market_index("创业板指"),
            "north_fund": "--", "north_is_up": None, "north_date": None,
            "up_count": "-", "down_count": "-", "flat_count": "-", "volume": "-",
            "breadth_total": "-", "breadth_date": None,
            "sh_amount": "-", "sz_amount": "-", "limit_count": "-",
            "sh_hist": [], "north_hist": [],
            "ladder": None, "pools": None, "hot_rank": None, "sentiment_parts": [],
            "sentiment_zones": SENTIMENT_ZONES, "sentiment_zone": None,
            "sentiment": 50, "sentiment_label": "中性", "provider": "金融大数据",
        }

def _empty_market_index(name):
    return {"name": name, "price": "--", "change_pct": "--", "change_val": "--", "is_up": None, "history": []}

from fastapi.concurrency import run_in_threadpool

_MARKET_WARM_INTERVAL = 25

async def _refresh_market_cache():
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(get_market_overview_datahub, True), timeout=30
        )
    except asyncio.TimeoutError:
        print("⚠️ [Market] 拉取超时（>30s），保留旧缓存下轮再试")
        return
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"⚠️ [Market] 拉取失败：{e}")
        return
    MARKET_CACHE["data"] = data
    MARKET_CACHE["timestamp"] = time.time()

async def _market_cache_warmer():
    while True:
        await asyncio.sleep(_MARKET_WARM_INTERVAL)
        await _refresh_market_cache()

def _secs_until_next_backfill_slot() -> float:
    import datetime as _dt
    now = _dt.datetime.now()
    target = now.replace(hour=15, minute=40, second=0, microsecond=0)
    d = now
    while True:
        cand = target if d.weekday() < 5 else None
        if cand is not None and cand > now:
            return (cand - now).total_seconds()
        d = (d + _dt.timedelta(days=1))
        target = d.replace(hour=15, minute=40, second=0, microsecond=0)

async def _valuation_backfill_worker():
    import backfill_valuation as _bf
    import db as _db
    while True:
        try:
            rows = await asyncio.to_thread(_db.list_valuations_for_backfill, 200)
            if rows:
                print(f"[Backfill] 待回填 {len(rows)} 条，开始处理", flush=True)
                for r in rows:
                    try:
                        st, msg = await asyncio.to_thread(_bf.backfill_one, r, False)
                        if st in ("ok", "error"):
                            print(f"[Backfill] id={r.get('id')} {r.get('stock_code')} "
                                  f"{st} {str(msg)[:80]}", flush=True)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"[Backfill] id={r.get('id')} 异常: {e}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[Backfill] 轮询失败: {e}", flush=True)
        await asyncio.sleep(_secs_until_next_backfill_slot())

@app.get("/market", response_class=HTMLResponse)
async def market_page(request: Request):
    data = await run_in_threadpool(get_market_realtime_data)

    return templates.TemplateResponse(
        request,
        "market_overview.html",
        {
            "request": request,
            "active_page": "market",
            "market": data
        }
    )

@app.get("/opportunities", response_class=HTMLResponse)
async def opp_page(request: Request):
    opp_data = await get_opportunities_data()
    return templates.TemplateResponse(
        request,
        "opportunities.html",
        {"request": request, "active_page": "opportunities", "opp": opp_data}
    )

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "active_page": "login", "hide_nav": True, "hide_footer": True}
    )

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    try:
        _reg_policy = settings.get_register_policy() or {}
    except Exception:
        _reg_policy = {"sms_required": True, "invite_required": False, "password_min_len": 6}
    return templates.TemplateResponse(
        request,
        "register.html",
        {"request": request, "active_page": "register", "hide_nav": True, "hide_footer": True,
         "reg_policy": _reg_policy}
    )

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    tier = get_effective_tier(user)
    normal_used, deep_used = get_today_counts(user["id"])
    bonus_normal, bonus_deep = get_bonus(user["id"])
    normal_remain = max(0, tier["normal_daily"] - normal_used) + bonus_normal
    _allowed_d, _reason_d, _dq = deep_quota_state(
        user["id"], tier, deep_used_today=deep_used, bonus_deep=bonus_deep)
    deep_remain = _dq["remain"]
    history = get_analysis_history(user["id"], 10)
    orders = list_user_orders(user["id"], 20)
    watchlist = list_watch(user["id"], 30)
    unread_alerts = count_unread_alerts(user["id"])
    user = dict(user)
    user["has_email"] = bool(user.get("email")) and not is_phone_email(user.get("email"))
    user["account"] = mask_phone(user.get("phone") or "")
    try:
        valuation_dashboard = get_user_valuation_dashboard(user["id"], limit=1)
    except Exception:
        valuation_dashboard = None
    try:
        holdings_research = db.get_user_holdings_with_research(user["id"])
    except Exception:
        holdings_research = []
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "request": request,
            "active_page": "profile",
            "user": user,
            "valuation_dashboard": valuation_dashboard,
            "holdings_research": holdings_research,
            "tier": tier,
            "is_vip": tier["level"] >= 1,
            "expiry": user["membership_expiry"] if tier["level"] >= 1 else None,
            "normal_used": normal_used,
            "normal_limit": tier["normal_daily"],
            "normal_remain": normal_remain,
            "bonus_normal": bonus_normal,
            "deep_used": deep_used,
            "deep_limit": tier["deep_daily"],
            "deep_remain": deep_remain,
            "bonus_deep": bonus_deep,
            "deep_monthly_quota": _dq["monthly_quota"],
            "deep_monthly_used": _dq["monthly_used"],
            "deep_monthly_rem": _dq["monthly_rem"],
            "total_analyses": get_analysis_total(user["id"]),
            "invite_count": get_invite_count(user["id"]),
            "history": history,
            "orders": orders,
            "watchlist": watchlist,
            "unread_alerts": unread_alerts,
        }
    )

@app.get("/api/profile/history")
async def api_profile_history(request: Request, page: int = 1, per_page: int = 10, mode: str = "all"):
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"status": "error", "msg": "请先登录"})
    per_page = min(max(per_page, 5), 50)
    page = max(page, 1)
    try:
        total, rows = await run_in_threadpool(
            get_analysis_history_page, user["id"], page, per_page,
            None if mode not in ("normal", "deep") else mode,
        )
    except Exception as e:
        print(f"⚠️ [Profile] 历史分页查询失败: {e}")
        total, rows = 0, []
    return {
        "status": "success",
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [
            {
                "id": r.get("id"),
                "stock_name": r.get("stock_name"),
                "stock_code": r.get("stock_code"),
                "mode": r.get("mode"),
                "model_id": r.get("model_id") or "默认",
                "preference": r.get("preference") or "-",
                "created_at": (r.get("created_at") or "")[:16],
            } for r in rows
        ],
    }

@app.get("/analysis/archive/{rid}", response_class=HTMLResponse)
async def analysis_archive_page(rid: int, request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request, "analysis_archive.html",
        {"request": request, "rid": rid, "active_page": "archive"},
    )

@app.get("/doc", response_class=HTMLResponse)
async def pdoc_page(request: Request):
    return templates.TemplateResponse(
        request,
        "dev_docs.html",
        {"request": request, "active_page": "doc"}
    )

@app.get("/api/analysis-options")
async def api_analysis_options(request: Request):
    user = get_current_user(request)
    public_user = to_public(user) if user else None
    if user:
        normal_used, deep_used = get_today_counts(user["id"])
        bonus_normal, bonus_deep = get_bonus(user["id"])
        public_user["normal_used"] = normal_used
        public_user["deep_used"] = deep_used
        public_user["bonus_normal"] = bonus_normal
        public_user["bonus_deep"] = bonus_deep
        public_user["deep_remain"] = deep_quota_state(
            user["id"], public_user["tier"],
            deep_used_today=deep_used, bonus_deep=bonus_deep)[2]["remain"]
        public_user["unlimited"] = bool(user.get("is_admin"))
        if not public_user["unlimited"]:
            try:
                public_user["unlimited"] = int(user.get("id") or 0) in settings.get_admin_uid_whitelist()
            except Exception:
                pass
        public_user["is_admin"] = bool(user.get("is_admin"))
    models = getattr(request.app.state, "analysis_models", settings.get_all_ai_models()) or []
    preferences = getattr(request.app.state, "analysis_preferences", get_analysis_preferences()) or []
    health = settings.get_model_health()
    for m in models:
        h = health.get(m.get("id")) or {}
        m["health_ok"] = h.get("ok")
        m["health_msg"] = h.get("error") or ""
        m["health_at"] = h.get("checked_at") or ""
    return JSONResponse(
        content={
            "status": "success",
            "models": models,
            "preferences": preferences,
            "user": public_user,
            "default_model_id": settings.get_default_ai_model_id(),
        },
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/api/market-snapshot")
async def api_market_snapshot():
    market_data, rank_data = await asyncio.gather(
        run_in_threadpool(get_market_realtime_data),
        run_in_threadpool(get_market_rank_data_sync),
    )
    return {
        "status": "success",
        "market": market_data,
        "hot_stocks": (rank_data or {}).get("hot_stocks", [])[:8],
        "trade_date": market_data.get("trade_date"),
    }

_ANALYSIS_LOCKS = {}
_ANALYSIS_LOCK_TTL = 300
_ANALYSIS_LOCK_MUTEX = threading.Lock()

def _acquire_analysis_lock(uid):
    now = time.time()
    with _ANALYSIS_LOCK_MUTEX:
        started = _ANALYSIS_LOCKS.get(uid)
        if started is not None and now - started < _ANALYSIS_LOCK_TTL:
            return None
        _ANALYSIS_LOCKS[uid] = now
        return now

def _release_analysis_lock(uid, token):
    if not token:
        return
    with _ANALYSIS_LOCK_MUTEX:
        if _ANALYSIS_LOCKS.get(uid) == token:
            _ANALYSIS_LOCKS.pop(uid, None)

_PANEL_METRIC_PATTERNS = {
    "price_now":  re.compile(r"当前价格\s*[:：]\s*(-?[\d.]+)"),
    "pe_ttm_now": re.compile(r"PE\s*\(TTM\)\s*[:：]\s*(-?[\d.]+)"),
    "pb_now":     re.compile(r"PB\s*\(市净率\)\s*[:：]\s*(-?[\d.]+)"),
    "mc_now":     re.compile(r"总市值\s*[:：]\s*(-?[\d.]+)"),
}

def _extract_panel_metrics(panel_text: str) -> dict:
    out = {}
    if not panel_text:
        return out
    for key, pat in _PANEL_METRIC_PATTERNS.items():
        m = pat.search(panel_text)
        if not m:
            continue
        try:
            v = float(m.group(1))
            if v != 0 or key in ("pe_ttm_now", "pb_now"):
                out[key] = v
            elif key in ("mc_now", "price_now") and v > 0:
                out[key] = v
        except (ValueError, IndexError):
            continue
    return out

_CONCLUSION_SENTINEL = "【投资结论】"

_CONCL_PATTERNS = {
    "valuation_low":  re.compile(r"合理市值区间\s*[:：]\s*(-?[\d,.]+)\s*[~～\-–—―到至]\s*(-?[\d,.]+)"),
    "valuation_high": re.compile(r"合理市值区间\s*[:：]\s*(-?[\d,.]+)\s*[~～\-–—―到至]\s*(-?[\d,.]+)"),
    "score":          re.compile(r"性价比评分\s*[:：]\s*(-?[\d.]+)"),
    "verdict":        re.compile(r"投资结论\s*[:：]\s*(低估|合理|高估|回避)"),
    "confidence":     re.compile(r"置信度\s*[:：]\s*(\d+)"),
    "horizon":        re.compile(r"建议持有\s*[:：]\s*(\d+m|\d+个月|\d+年)"),
    "key_reason":     re.compile(r"核心依据\s*[:：]\s*(.+)"),
}

_CONCL_TAIL_RATIO = 0.70
_CONCL_MAX_BLOCK = 2000

def _conclusion_span(report_md: str):
    if not report_md:
        return None
    idx = report_md.find(_CONCLUSION_SENTINEL)
    if idx < 0:
        return None
    total = len(report_md)
    if idx >= total * _CONCL_TAIL_RATIO:
        return (idx, total)
    after = idx + len(_CONCLUSION_SENTINEL)
    m = re.search(r"\n#{1,6}\s", report_md[after:])
    end = (after + m.start()) if m else min(after + _CONCL_MAX_BLOCK, total)
    return (idx, min(end, total))

def _extract_conclusion(report_md: str) -> dict:
    out = {}
    if not report_md:
        return out
    span = _conclusion_span(report_md)
    if not span:
        return out
    idx, end = span
    block = report_md[idx + len(_CONCLUSION_SENTINEL):end]
    out["_raw_block"] = block.strip()[:2000]

    def _set_range(low, high):
        try:
            low = float(low)
            high = float(high)
        except (TypeError, ValueError):
            return
        if low > high:
            low, high = high, low
        if low < 1 or high > 100_000_000 or low <= 0:
            return
        out["valuation_low"] = low
        out["valuation_high"] = high
        out["valuation_mid"] = round((low + high) / 2.0, 2)

    m = _CONCL_PATTERNS["valuation_low"].search(block)
    if m:
        _set_range(m.group(1).replace(",", ""), m.group(2).replace(",", ""))
    if "valuation_low" not in out:
        for line in block.splitlines():
            line = line.strip()
            if "合理市值" not in line and "合理估值" not in line:
                continue
            clean = re.sub(r"[（(][^（）()]*[）)]", "", line)
            clean = clean.replace(",", "")
            nums = re.findall(r"\d+(?:\.\d+)?", clean)
            if len(nums) >= 2:
                _set_range(nums[0], nums[1])
                break
    for key in ("score", "verdict", "confidence", "horizon", "key_reason"):
        m = _CONCL_PATTERNS[key].search(block)
        if not m:
            continue
        raw = m.group(1).strip()
        if key == "score":
            try:
                v = float(raw)
                if 0 <= v <= 10:
                    out[key] = round(v, 1)
            except ValueError:
                pass
        elif key == "confidence":
            try:
                v = int(raw)
                if 1 <= v <= 5:
                    out[key] = v
            except ValueError:
                pass
        elif key == "verdict":
            if raw in ("低估", "合理", "高估", "回避"):
                out[key] = raw
        elif key == "horizon":
            if raw.endswith("m"):
                out[key] = raw
            elif "个月" in raw:
                num = raw.replace("个月", "").strip()
                try:
                    out[key] = f"{int(num)}m"
                except ValueError:
                    pass
            elif "年" in raw:
                try:
                    out[key] = f"{int(raw.replace('年', '').strip()) * 12}m"
                except ValueError:
                    pass
        elif key == "key_reason":
            out[key] = raw[:255]
    return out

def _strip_conclusion_block(report_md: str) -> str:
    if not report_md:
        return report_md
    span = _conclusion_span(report_md)
    if not span:
        return report_md
    idx, end = span
    head = report_md[:idx]
    m = re.search(r"\n#{1,6}\s*投资结论速览[^\n]*\s*$", head)
    if m:
        return report_md[:m.start()].rstrip() + "\n"
    kept = report_md[end:]
    return (report_md[:idx].rstrip() + ("\n\n" + kept.lstrip("\n") if kept.strip() else "")).rstrip() + "\n"

_FINAL_MIN_CHARS = 1500
_FINAL_MIN_CHARS_OK = 800
_FINAL_MIN_HEADINGS = 3
_CONCL_CUT_RATIO = 0.60
_FINAL_HEADING_RE = re.compile(r"^#{1,6}\s+", re.M)
_TRUNC_MARK = "生成过程中被截断"
_DRAFT_MARKERS = (
    "we need to", "we need answer", "let's ", "wait outline", "i need to",
    "okay,", "alright,", "thinking process", "then a blockquote",
    "we must follow", "the outline says",
)

def _final_report_problem(full_md: str, body_md: str):
    body = (body_md or "").strip()
    if not body:
        return "正文为空"
    n_head = len(_FINAL_HEADING_RE.findall(body))
    structured = n_head >= _FINAL_MIN_HEADINGS
    floor = _FINAL_MIN_CHARS_OK if structured else _FINAL_MIN_CHARS
    if len(body) < floor:
        return (f"正文过短（{len(body)} 字"
                + ("，且无完整章节结构" if not structured else "") + "）")
    if not structured:
        return f"章节结构不完整（仅 {n_head} 个标题）"
    full_len = len((full_md or "").strip())
    if full_len and (full_len - len(body)) > full_len * _CONCL_CUT_RATIO:
        return f"结论块切掉了 {int((full_len - len(body)) / full_len * 100)}% 的正文"
    if (_TRUNC_MARK in body
            or detect_truncation(body)
            or ("最后" in body[-14:] and not re.search(r"[。！？）)]\s*$", body))):
        return "正文疑似被输出预算截断（结尾未完结）"
    head = body[:400].lower()
    for mk in _DRAFT_MARKERS:
        if mk in head:
            return f"正文开头是模型的规划草稿（命中「{mk}」）"
    return None

@app.post("/api/analyze")
async def analyze_stock(req: AnalyzeRequest, request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse(
            status_code=401,
            content={"error": "请先登录后再使用 AI 分析，<a href='/login'>去登录</a>"},
        )

    tier = get_effective_tier(user)
    is_vip = tier["level"] >= 1
    is_admin = bool(user.get("is_admin"))
    quota_free = is_admin or (int(user.get("id") or 0) in settings.get_admin_uid_whitelist())

    _ip_cap = _rl("analyze_ip_per_day", 0)
    if _ip_cap > 0 and not quota_free:
        err = _too_many(f"analyze:ip:{_client_ip(request)}", _ip_cap, 86400)
        if err:
            raise err

    preferences = getattr(request.app.state, "analysis_preferences", get_analysis_preferences()) or []
    pref = next((p for p in preferences if p.get("id") == req.preference), None)
    if not pref:
        return JSONResponse(
            status_code=400,
            content={"error": f"未知的投资偏好: {req.preference}"},
        )
    if pref.get("vip_only") and not is_vip:
        return JSONResponse(
            status_code=403,
            content={"error": f"「{pref.get('name')}」为 VIP 专属投资偏好，请 <a href='/pricing'>升级会员</a>"},
        )

    model_id = (req.model or "").strip()
    models = getattr(request.app.state, "analysis_models", settings.get_all_ai_models()) or []
    model = None
    if model_id:
        model = next((m for m in models if m.get("id") == model_id and m.get("enabled")), None)
        if not model:
            return JSONResponse(
                status_code=400,
                content={"error": f"未找到可用的模型: {model_id}"},
            )
    else:
        _chan, model = settings.resolve_ai_model(None)
        if model:
            model_id = model.get("id") or ""
        if not model:
            return JSONResponse(
                status_code=400,
                content={"error": "未配置可用的 AI 模型，请联系管理员在后台「系统设置 → AI 大模型」中添加并启用模型。"},
            )
    if model.get("vip_only") and not is_vip:
        return JSONResponse(
            status_code=403,
            content={"error": f"「{model.get('alias') or model.get('name')}」为 VIP 专属模型，请 <a href='/pricing'>升级会员</a>"},
        )

    mode = "deep" if pref.get("is_deep") else "normal"
    normal_used, deep_used = get_today_counts(user["id"])
    bonus_normal, bonus_deep = get_bonus(user["id"])

    if not quota_free:
        if mode == "deep":
            allowed, reason, dq = deep_quota_state(user["id"], tier)
            if not allowed:
                if reason == "vip_only":
                    return JSONResponse(
                        status_code=403,
                        content={"error": "深度分析为会员专属功能，请 <a href='/pricing'>升级会员</a>"},
                    )
                parts = []
                if dq["daily_quota"] > 0:
                    parts.append(f"每日 {dq['daily_quota']} 次")
                if dq["monthly_quota"] > 0:
                    parts.append(f"每月体验 {dq['monthly_quota']} 次")
                if dq["bonus_deep"] > 0:
                    parts.append(f"赠送 {dq['bonus_deep']} 次")
                scope = " + ".join(parts) or "当前套餐"
                return JSONResponse(
                    status_code=403,
                    content={"error": f"深度分析次数已用尽（{scope}），<a href='/pricing'>升级会员</a>解锁更多"},
                )
        else:
            daily_rem = max(0, tier["normal_daily"] - normal_used)
            if daily_rem + bonus_normal <= 0:
                return JSONResponse(
                    status_code=403,
                    content={"error": f"今日普通分析次数已用尽（每日 {tier['normal_daily']} 次 + 赠送 {bonus_normal} 次），<a href='/pricing'>升级会员</a>解锁更多"},
                )

    lock_token = _acquire_analysis_lock(user["id"])
    if lock_token is None:
        return JSONResponse(
            status_code=409,
            content={"error": "上一次分析还在进行中，请等它跑完再开始新的分析。重复提交不会更快，只会多消耗额度。"},
        )

    def _abort_locked(msg):
        _release_analysis_lock(user["id"], lock_token)

        async def error_gen():
            yield msg

        return StreamingResponse(error_gen(), media_type="text/html")

    try:
        ts_code, name = await get_stock_code(req.query)

        if not ts_code:
            return _abort_locked("<div class='alert alert-danger'>❌ 未找到该股票，请检查输入。</div>")

        try:
            stock_row = await run_in_threadpool(get_stock_by_ts_code, ts_code)
            if stock_row is None:
                return _abort_locked(
                    "<div class='alert alert-danger'>"
                    f"❌ 未在 A 股股票库中找到 {ts_code}，请确认代码是否正确。"
                    "</div>"
                )
            if stock_row.get("name"):
                name = stock_row["name"]
        except Exception as e:
            print(f"[analyze] 股票存在性校验异常（放行）: {e}")
    except Exception:
        _release_analysis_lock(user["id"], lock_token)
        raise

    _ERR_TAG = "[系统错误]"
    _ERR_RE = re.compile(r"\*\*\[系统错误\]\*\*[^\n]*|\[系统错误\][^\n]*")
    _HEAD_RELEASE_RE = re.compile(r"(?:^|\n)#{1,6}\s")
    _HEAD_BUF_LIMIT = 1200
    _CONCL_HOLD = max(0, len(_CONCLUSION_SENTINEL) - 1)

    _HB_INTERVAL = 5.0
    _HB_INTERVAL_MID = 15.0
    _HB_BEAT = "\n"
    _HB_BEAT_MID = "\u200b"

    async def _analyze_stream():
        record_id = None
        bonus_consumed = 0
        buf = []
        failed_reason = None
        head_buf = []
        head_done = False
        data_summary = None
        bt_started = False
        bt_buf = []
        hold = ""
        t0 = time.time()
        interrupted = False
        _pending_task = None
        _panel_task = None

        def _flush_head():
            nonlocal head_done
            if head_done or not head_buf:
                head_done = True
                return None
            text = "".join(head_buf)
            head_buf.clear()
            head_done = True
            return strip_ai_opener(text)

        try:
            _t_panel = time.time()
            panel_metrics = {}
            _panel_task = asyncio.ensure_future(
                get_stock_data_summary(ts_code, preference_id=pref.get("id"),
                                       metrics_sink=panel_metrics))
            while True:
                try:
                    data_summary = await asyncio.wait_for(
                        asyncio.shield(_panel_task), timeout=_HB_INTERVAL)
                    break
                except asyncio.TimeoutError:
                    yield _HB_BEAT
            print(f"[analyze] 数据面板就绪 {time.time() - _t_panel:.1f}s "
                  f"{len(data_summary or '')}字 pref={pref.get('id')} code={ts_code}", flush=True)

            _ds_head_only = bool(re.match(
                r"^【股票数据面板:[^】]*】\s*$", str(data_summary or "").strip()))
            if (not str(data_summary or "").strip()
                    or str(data_summary).startswith("数据获取服务暂时不可用")
                    or _ds_head_only):
                yield (
                    "<div class='alert alert-danger'>"
                    "❌ 数据源暂时不可用（本次未能拉取到任何行情/财务数据），"
                    "为避免生成无效报告已中止分析，未消耗您的配额，请稍后重试。</div>"
                )
                return

            bonus_consumed = 0
            if not quota_free:
                try:
                    if consume_bonus_atomic(user["id"], mode):
                        bonus_consumed = 1
                except Exception as e:
                    print(f"[analyze] 原子扣减赠送余量失败（按每日额度处理）: {e}")
            model_label = model.get("alias") or model.get("model_id") or (model_id or None)
            try:
                record_id = record_analysis(
                    user["id"], name, ts_code, mode, model_id=model_label,
                    preference=pref.get("id"),
                    quota_source=("bonus" if bonus_consumed else "daily"),
                )
            except Exception as e:
                if bonus_consumed:
                    try:
                        auth.restore_bonus(user["id"], mode)
                    except Exception as e2:
                        print(f"[analyze] 回补赠送失败（需人工核查 uid={user['id']}）: {e2}", flush=True)
                print(f"[analyze] 落分析记录失败（已回补赠送）: {e}", flush=True)
                raise

            raw_gen = analyze_stock_stream(name, ts_code, data_summary, model_id=model_id or None, preference_id=pref.get("id"), allow_vip=bool(quota_free or is_vip))

            _it = raw_gen.__aiter__()
            _END = object()

            async def _anext_or_end():
                try:
                    return await _it.__anext__()
                except StopAsyncIteration:
                    return _END

            _pending_task = asyncio.ensure_future(_anext_or_end())
            _t_first = time.time()
            _got_first = False

            while True:
                try:
                    chunk = await asyncio.wait_for(
                        asyncio.shield(_pending_task),
                        timeout=(_HB_INTERVAL if not _got_first else _HB_INTERVAL_MID))
                except asyncio.TimeoutError:
                    yield _HB_BEAT if not _got_first else _HB_BEAT_MID
                    continue

                if chunk is _END:
                    break
                if not _got_first:
                    _got_first = True
                    print(f"[analyze] 模型首字节 {time.time() - _t_first:.1f}s "
                          f"pref={pref.get('id')} model={model.get('alias')}", flush=True)
                _pending_task = asyncio.ensure_future(_anext_or_end())

                buf.append(chunk)
                if failed_reason is None and _ERR_TAG in chunk:
                    m = _ERR_RE.search(chunk)
                    raw = m.group(0) if m else _ERR_TAG
                    failed_reason = re.sub(r"\*+", "", raw).strip()[:250]
                    out = _flush_head()
                    if out:
                        yield out
                    if hold:
                        yield hold
                        hold = ""
                    yield chunk
                    continue
                if not head_done:
                    head_buf.append(chunk)
                    if (_HEAD_RELEASE_RE.search("".join(head_buf))
                            or sum(len(x) for x in head_buf) >= _HEAD_BUF_LIMIT):
                        out = _flush_head()
                        if out:
                            yield out
                    continue
                if bt_started:
                    bt_buf.append(chunk)
                    continue
                combined = hold + chunk
                idx = combined.find(_CONCLUSION_SENTINEL)
                if idx >= 0:
                    bt_started = True
                    front = combined[:idx]
                    if front:
                        yield front
                    bt_buf.append(combined[idx + len(_CONCLUSION_SENTINEL):])
                    hold = ""
                    continue
                if len(combined) > _CONCL_HOLD:
                    out, hold = combined[:-_CONCL_HOLD], combined[-_CONCL_HOLD:]
                    if out:
                        yield out
                else:
                    hold = combined
            bt_buf.clear()
            bt_started = False
            out = _flush_head()
            if out:
                yield out
            if hold:
                yield hold
                hold = ""
        except GeneratorExit:
            interrupted = True
            raise
        except Exception as e:
            err = str(e)
            failed_reason = f"[系统错误] {err[:200]}"
            yield f"\n\n**[系统错误] 分析异常：{err}**"
        finally:
            _release_analysis_lock(user["id"], lock_token)
            if _panel_task is not None:
                _panel_task.cancel()
            if _pending_task is not None:
                _pending_task.cancel()
            full_md = "".join(buf)
            if failed_reason is None and record_id and not full_md.strip():
                failed_reason = "[系统错误] AI 无输出（上游模型超时或返回空内容，非股票代码问题）"
            if interrupted and failed_reason is None and record_id and full_md.strip():
                failed_reason = "[已中断] 生成未完成（用户取消或连接中断），本次不扣次数"
            bt_obj = None
            body_md = full_md
            _final_problem = None
            if (pref.get("id") or "") in BACKTEST_PREFERENCES:
                bt_obj = _extract_conclusion(full_md)
                body_md = _strip_conclusion_block(full_md)
            if full_md.strip():
                _final_problem = _final_report_problem(full_md, body_md)
                if _final_problem and failed_reason is None and record_id:
                    failed_reason = (
                        f"[系统错误] 报告不完整（{_final_problem}），"
                        f"已为你退回本次次数，建议换一个模型重试")
            if failed_reason and record_id:
                try:
                    ok = refund_analysis(
                        user["id"], record_id, mode, bonus_consumed, failed_reason
                    )
                    if ok:
                        print(f"[analyze] 分析失败已退配额 record={record_id} "
                              f"user={user['id']} reason={failed_reason[:80]}", flush=True)
                except BaseException as e:
                    print(f"[analyze] 退配额失败 record={record_id}: {e}", flush=True)
            if full_md.strip():
                try:
                    cleaned = postprocess_report(body_md)
                    update_analysis_report(record_id, cleaned)
                    if ((pref.get("id") or "") in BACKTEST_PREFERENCES
                            and not interrupted and not _final_problem):
                        try:
                            metrics = {k: v for k, v in (panel_metrics or {}).items()
                                       if v is not None and k != "completeness"}
                            _fb = _extract_panel_metrics(data_summary)
                            for _k, _v in _fb.items():
                                metrics.setdefault(_k, _v)
                            bt_for_db = {
                                "valuation_low": bt_obj.get("valuation_low"),
                                "valuation_high": bt_obj.get("valuation_high"),
                                "valuation_mid": bt_obj.get("valuation_mid"),
                                "score": bt_obj.get("score"),
                                "confidence": bt_obj.get("confidence"),
                                "verdict": bt_obj.get("verdict"),
                                "horizon": bt_obj.get("horizon"),
                                "key_reason": bt_obj.get("key_reason"),
                                "mc_now": metrics.get("mc_now"),
                                "price_now": metrics.get("price_now"),
                                "pe_ttm_now": metrics.get("pe_ttm_now"),
                                "pb_now": metrics.get("pb_now"),
                                "upside_pct": None,
                                "raw": bt_obj.get("_raw_block"),
                            }
                            mc = bt_for_db.get("mc_now")
                            mid = bt_for_db.get("valuation_mid")
                            if mc not in (None, 0) and mid is not None:
                                bt_for_db["upside_pct"] = round(
                                    (mid - mc) / abs(mc) * 100.0, 2)
                            has_any = any(v is not None for k, v in bt_for_db.items()
                                          if k != "raw")
                            if has_any:
                                groups = resolve_data_groups(pref.get("id"))
                                detail = {
                                    "query": req.query,
                                    "mode": mode,
                                    "preference": pref.get("id"),
                                    "preference_name": pref.get("name"),
                                    "data_groups": [
                                        {"id": g,
                                         "title": (DATA_GROUPS.get(g) or {}).get("title", g),
                                         "fields": list((DATA_GROUPS.get(g) or {}).get("fields") or [])}
                                        for g in groups
                                    ],
                                    "panel_chars": len(data_summary or ""),
                                    "model_alias": model.get("alias"),
                                    "model_id_internal": model.get("id"),
                                    "is_deep": bool(pref.get("is_deep")),
                                }
                                vid = save_analysis_valuation(
                                    record_id=record_id,
                                    user_id=user["id"],
                                    stock_name=name,
                                    stock_code=ts_code,
                                    model=model_label,
                                    model_id=model.get("id") or model_id or None,
                                    preference=pref.get("id"),
                                    bt=bt_for_db,
                                    panel_text=data_summary,
                                    detail=detail,
                                    fallback=0,
                                    duration_ms=int((time.time() - t0) * 1000),
                                )
                                if vid:
                                    print(f"[analyze] 回测台账已记录 id={vid} record={record_id} "
                                          f"{name}/{ts_code} mc={bt_for_db.get('mc_now')}亿 "
                                          f"price={bt_for_db.get('price_now')} "
                                          f"score={bt_for_db.get('score')} "
                                          f"区间={bt_for_db.get('valuation_low')}~{bt_for_db.get('valuation_high')}亿",
                                          flush=True)
                        except BaseException as e:
                            print(f"[analyze] 回测台账落库失败 record={record_id}: {e}", flush=True)
                except BaseException as e:
                    print(f"[analyze] 保存研报全文失败: {e}", flush=True)

    return StreamingResponse(
        _analyze_stream(),
        media_type="text/html"
    )

@app.post("/api/export-pdf")
async def export_pdf(req: PDFRequest, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再导出 PDF")
    tier = get_effective_tier(user)
    if not tier["pdf"]:
        raise HTTPException(status_code=403, detail="PDF 导出为会员专属功能，请升级会员")
    try:
        _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        try:
            from weasyprint import HTML as _WP_HTML
            _engine = "weasyprint"
        except Exception:
            from xhtml2pdf import pisa
            _engine = "xhtml2pdf"

        if "免责声明" in (req.html_content or ""):
            _PDF_DISCLAIMER = ""
        else:
            _PDF_DISCLAIMER = (
                '<hr/><div style="margin-top:24px; font-size:11px; color:#666; line-height:1.6;">'
                '<strong>免责声明</strong><br/>本报告由「A股棱镜」的 AI 模型自动生成，'
                '属于公开信息整理与算法推演结果，不构成证券投资建议、买卖要约或收益承诺；'
                '引用数据来自第三方公开渠道，不保证准确完整，请以交易所及上市公司公告为准。'
                '股市有风险，入市需谨慎。</div>'
            )

        if _engine == "weasyprint":
            _font_face = ""
            body_font = '"Noto Sans CJK SC", "WenQuanYi Zen Hei", sans-serif'
        else:
            _use_cjk = os.path.exists(os.path.join(_BASE_DIR, "fonts", "DroidSansFallbackFull.ttf"))
            if _use_cjk:
                _font_face = '@font-face { font-family: "CJK"; src: url("fonts/DroidSansFallbackFull.ttf"); }'
                body_font = '"CJK", sans-serif'
            else:
                _font_face = ""
                body_font = '"SimHei", "Microsoft YaHei", sans-serif'

        pdf_css = f'''
            {_font_face}
            @page {{ size: A4; margin: 1.8cm 1.6cm;
                     @bottom-center {{ content: counter(page) " / " counter(pages); font-size: 9px; color: #9ca3af; }} }}
            * {{ box-sizing: border-box; }}
            body {{ font-family: {body_font}; color: #1f2937; line-height: 1.75; font-size: 12px; }}
            h1 {{ font-family: {body_font}; font-size: 22px; color: #111827; }}
            h2 {{ font-family: {body_font}; font-size: 16px; color: #1e3a8a;
                 border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin: 26px 0 14px;
                 page-break-after: avoid; }}
            h3 {{ font-family: {body_font}; font-size: 14px; color: #374151; margin: 18px 0 8px;
                 page-break-after: avoid; }}
            strong {{ color: #111827; }}
            .text-danger {{ color: #d9534f; }}
            .text-success {{ color: #5cb85c; }}
            table {{ width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 11px; }}
            th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; }}
            th {{ background-color: #eff6ff; color: #1e3a8a; }}
            tr {{ page-break-inside: avoid; }}
            p {{ margin: 0 0 10px; text-align: justify; }}
            ul, ol {{ margin: 0 0 12px; padding-left: 22px; }}
            li {{ margin-bottom: 4px; }}
            blockquote {{ border-left: 4px solid #93c5fd; margin: 12px 0; padding: 8px 14px;
                          background: #f8fafc; color: #475569; }}
            code {{ font-family: monospace; background: #f1f5f9; padding: 1px 4px;
                    border-radius: 3px; font-size: 11px; }}
            pre {{ background: #f1f5f9; padding: 10px; border-radius: 4px; font-size: 11px;
                   white-space: pre-wrap; word-wrap: break-word; }}
            hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 18px 0; }}
            img {{ max-width: 100%; }}
        '''

        full_html = f"""
        <html>
        <head><meta charset="UTF-8"></head>
        <body>
            <div style="text-align:center; margin-bottom: 30px; border-bottom: 2px solid #e5e7eb; padding-bottom: 14px;">
                <h1 style="font-size: 22px; margin-bottom: 6px;">{req.stock_name} 投资分析报告</h1>
                <p style="color:#6b7280; font-size: 13px;">A股棱镜 | {pd.Timestamp.now().strftime('%Y-%m-%d')}</p>
            </div>
            {req.html_content}
            {_PDF_DISCLAIMER}
        </body>
        </html>
        """

        styled_html = full_html.replace("<head>", f"<head><style>{pdf_css}</style>", 1)
        raw_name = f"{req.stock_name}_{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}.pdf"
        filename = "".join(c for c in raw_name if (c.isalnum() or c in "._-"))
        if not filename.endswith(".pdf"):
            filename += ".pdf"
        filepath = os.path.join(PDF_DIR, filename)
        if _engine == "weasyprint":
            _WP_HTML(string=styled_html, base_url=_BASE_DIR + os.sep).write_pdf(filepath)
        else:
            with open(filepath, "wb") as out:
                pdf_err = pisa.CreatePDF(styled_html, dest=out, path=_BASE_DIR)
            if getattr(pdf_err, "err", False):
                raise RuntimeError("xhtml2pdf 转换错误")
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            raise RuntimeError("PDF 生成失败（空文件或转换错误）")
        print(f"[PDF] engine={_engine} file={filename} size={os.path.getsize(filepath)}")
        return {"download_url": f"/api/export-pdf/download/{filename}", "filename": filename}

    except ImportError:
        raise HTTPException(status_code=400, detail="服务端 PDF 组件不可用，请使用浏览器「打印」（Ctrl/Cmd+P）并选择「另存为 PDF」")
    except Exception as e:
        print(f"PDF Error: {e}")
        raise HTTPException(status_code=500, detail=f"PDF生成失败: {str(e)[:200]}")

@app.get("/api/export-pdf/download/{filename}")
async def download_pdf(filename: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再下载")
    import re as _re
    safe = "".join(c for c in filename if (c.isalnum() or c in "._-"))
    if not safe or safe != filename or not safe.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="非法文件名")
    filepath = os.path.join(PDF_DIR, safe)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    return FileResponse(filepath, media_type="application/pdf", filename=safe)

class FeedbackModel(BaseModel):
    type: str = "other"
    title: str
    desc: str

@app.get("/feedback", response_class=HTMLResponse)
async def feedback_page(request: Request):
    return templates.TemplateResponse(request, "feedback.html", {"request": request})

@app.get("/api/feedback/list")
async def get_feedback_list():
    try:
        _, rows = list_feedback(page=1, per_page=200)
        return [_feedback_to_public(r) for r in rows]
    except Exception as e:
        print(f"Feedback list error: {e}")
        return []

@app.post("/api/feedback/submit")
async def submit_feedback(fb: FeedbackModel, request: Request):
    user = get_current_user(request)
    user_id = user["id"] if user else None
    ftype = fb.type if fb.type in ("bug", "feature", "data", "other") else "other"
    insert_feedback(
        user_id=user_id,
        title=fb.title.strip()[:255],
        content=fb.desc,
        feedback_type=ftype,
        contact=None,
    )
    return {"status": "success", "msg": "反馈已提交，感谢您的贡献！"}

@app.post("/api/feedback/vote/{item_id}")
async def api_vote_feedback(item_id: int):
    votes = vote_feedback(item_id)
    if votes is None:
        return {"status": "error", "msg": "未找到该反馈"}
    return {"status": "success", "votes": votes}

@app.get("/api/stocks/search")
async def api_stocks_search(q: str = "", limit: int = 10):
    results = await run_in_threadpool(search_stocks, q, limit)
    return {"status": "success", "query": q, "results": results}

@app.post("/api/redeem")
async def api_redeem(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    exc = (_too_many(f"redeem:u:{user['id']}", 10, 600)
           or _too_many(f"redeem:ip:{_client_ip(request)}", 30, 600))
    if exc:
        raise exc
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    code = str(body.get("code") or "").strip()
    if not code:
        return {"status": "fail", "message": "请输入兑换码"}
    ok, msg, info = redeem_code(user["id"], code)
    if not ok:
        return {"status": "fail", "message": msg}
    try:
        info["user"] = to_public(get_user_by_id(user["id"]) or {})
    except Exception:
        pass
    return {"status": "success", "message": msg, "info": info}

@app.get("/api/notifications")
async def api_notifications(request: Request, limit: int = 20):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        rows = list_user_notifications(user["id"], limit=limit)
        unread = count_unread_notifications(user["id"])
        return {"status": "success", "rows": rows, "unread": unread}
    except Exception as e:
        print(f"notifications list error: {e}")
        raise HTTPException(status_code=500, detail="读取失败")

@app.post("/api/notifications/read")
async def api_notification_read(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    try:
        nid = int(body.get("id") or 0)
    except Exception:
        raise HTTPException(status_code=400, detail="参数错误")
    if nid <= 0:
        raise HTTPException(status_code=400, detail="参数错误")
    ok = notification_visible(nid, user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="通知不存在")
    mark_notification_read(user["id"], nid)
    return {"status": "success", "unread": count_unread_notifications(user["id"])}

@app.post("/api/notifications/read-all")
async def api_notifications_read_all(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    n = mark_all_notifications_read(user["id"])
    return {"status": "success", "marked": n, "unread": 0}

_NOTIFY_SCHEDULER_STARTED = False

def start_notification_scheduler(interval=86400, run_now=True):
    global _NOTIFY_SCHEDULER_STARTED
    if _NOTIFY_SCHEDULER_STARTED:
        return
    _NOTIFY_SCHEDULER_STARTED = True

    def _loop():
        while True:
            time.sleep(interval)
            try:
                created, scanned = scan_membership_expiry()
                if created:
                    print(f"🔔 [Notify] 会员到期提醒已推送 {created} 条（扫描 {scanned} 人）")
            except Exception as e:
                print(f"⚠️ [Notify] 到期扫描异常: {e}")

    if run_now:
        try:
            created, scanned = scan_membership_expiry()
            if created:
                print(f"🔔 [Notify] 启动补跑：会员到期提醒 {created} 条（扫描 {scanned} 人）")
        except Exception as e:
            print(f"⚠️ [Notify] 启动补跑失败: {e}")
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"🔔 [Notify] 会员到期扫描已启动（每 {interval}s）")

@app.get("/api/news")
async def get_news(src: str = "gelonghui", limit: int = 50, offset: int = 0):
    limit = min(200, max(1, int(limit)))
    offset = max(0, int(offset))
    if offset == 0:
        news_data = await get_news_data(src=src, limit=limit)
        provider = data_service.NEWS_CACHE.get("provider") or "金融大数据"
        notice = data_service.NEWS_CACHE.get("notice", "") or ""
        try:
            gids = [int(it.get("gid", 0)) for it in (news_data or []) if it.get("gid")]
            if gids:
                increment_news_views(gids)
        except Exception as e:
            print(f"⚠️ [News] 浏览量计数失败: {e}")
        return {"status": "success", "data": news_data, "provider": provider,
                "notice": notice, "offset": 0}
    total = 0
    try:
        total, rows = list_news(limit=limit, offset=offset)
        items = [data_service._row_to_news_item(r) for r in rows]
    except Exception as e:
        print(f"⚠️ [News] 历史读取失败: {e}")
        items = []
    return {"status": "success", "data": items, "provider": "金融大数据",
            "notice": "", "offset": offset, "total": total}

class NewsLikeRequest(BaseModel):
    gid: int
    action: str = "like"

@app.post("/api/news/like")
async def news_like(req: NewsLikeRequest):
    try:
        delta = 1 if req.action == "like" else -1
        likes = increment_news_likes(req.gid, delta)
        for it in (data_service.NEWS_CACHE.get("data") or []):
            if int(it.get("gid", 0)) == int(req.gid):
                it["likes"] = likes
                break
        return {"status": "success", "gid": req.gid, "likes": likes,
                "liked": req.action == "like"}
    except Exception as e:
        print(f"⚠️ [News] 点赞失败: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "msg": "点赞失败"})

class RegisterRequest(BaseModel):
    password: str
    phone: str = ""
    invite_code: str = ""
    nickname: str = ""
    code: str = ""
    email: str = ""

class LoginRequest(BaseModel):
    email: str = ""
    password: str = ""
    phone: str = ""
    code: str = ""

class UpgradeRequest(BaseModel):
    plan: str

class ProfileUpdateRequest(BaseModel):
    nickname: str = ""
    phone: str = ""
    code: str = ""

class SMSRequest(BaseModel):
    mobile: str
    scene: str

class SMSVerifyRequest(BaseModel):
    mobile: str
    code: str
    scene: str

@app.post("/api/register")
async def api_register(req: RegisterRequest, response: Response, request: Request):
    ip = _client_ip(request)
    err = _too_many(f"register:ip:{ip}", _rl("register_ip_per_hour", 10), 3600)
    if err:
        raise err
    try:
        _policy = settings.get_register_policy() or {}
    except Exception:
        _policy = {}
    sms_required = _policy.get("sms_required", True)
    invite_required = bool(_policy.get("invite_required")) or not sms_required
    phone = (req.phone or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请填写手机号")
    if not is_valid_mobile(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    if sms_required:
        if not req.code:
            raise HTTPException(status_code=400, detail="请填写短信验证码")
        ok, msg = verify_code(phone, req.code, "register")
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
    if invite_required and not (req.invite_code or "").strip():
        raise HTTPException(status_code=400, detail="当前注册需要邀请码，请向管理员获取")
    try:
        user = create_user(phone, req.password, req.invite_code or None,
                           req.nickname or None, require_invite=invite_required)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    set_session_cookie(response, user["id"], request=request)
    return {"status": "success", "user": to_public(user), "msg": "注册成功"}

@app.post("/api/login")
async def api_login(req: LoginRequest, request: Request, response: Response):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    err = _too_many(f"login:ip:{ip}", _rl("login_ip_per_min", 10), 60)
    if err:
        raise err

    if (req.phone or "").strip() and (req.code or "").strip():
        phone = req.phone.strip()
        if not is_valid_mobile(phone):
            raise HTTPException(status_code=400, detail="手机号格式不正确")
        ok, msg = verify_code(phone, req.code, "login")
        if not ok:
            record_login(None, phone, False, ip, ua, "验证码错误")
            raise HTTPException(status_code=400, detail=msg)
        user = get_user_by_phone(phone)
        if not user:
            record_login(None, phone, False, ip, ua, "手机号未注册")
            raise HTTPException(status_code=401, detail="该手机号尚未注册")
        if int(user.get("status") or 0) != 1:
            record_login(user["id"], user.get("email"), False, ip, ua, "账号已封禁")
            raise HTTPException(status_code=403, detail="该账号已被禁用，如有疑问请联系客服")
        record_login(user["id"], user.get("email"), True, ip, ua, "登录成功")
        set_session_cookie(response, user["id"], request=request)
        return {"status": "success", "user": to_public(user), "msg": "登录成功"}

    ident = (req.email or "").strip()
    err = _too_many(f"login:acct:{ident.lower()}", _rl("login_acct_per_min", 5), 60)
    if err:
        raise err
    existing = find_user_by_identifier(ident)
    user = authenticate(ident, req.password)
    if not user:
        reason = "账号不存在" if not existing else ("密码错误" if (existing and int(existing.get("status") or 0) == 1) else "账号已封禁")
        record_login(existing.get("id") if existing else None, ident, False, ip, ua, reason)
        raise HTTPException(status_code=401, detail="账号或密码错误")
    record_login(user["id"], user.get("email") or ident, True, ip, ua, "登录成功")
    set_session_cookie(response, user["id"], request=request)
    return {"status": "success", "user": to_public(user), "msg": "登录成功"}

@app.post("/api/logout")
async def api_logout(request: Request, response: Response):
    user = get_current_user(request)
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")
    if user:
        record_login(user["id"], user.get("email"), True, ip, ua, "退出登录")
    clear_session_cookie(response)
    return {"status": "success", "msg": "已退出登录"}

@app.get("/api/me")
async def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"status": "unauthenticated"}
    return {"status": "success", "user": to_public(user)}

@app.post("/api/membership/upgrade")
async def api_upgrade(req: UpgradeRequest, request: Request, response: Response):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    raise HTTPException(
        status_code=403,
        detail="线上不开通直接开通通道。请在合作店铺购买会员卡密后，"
               "到「个人中心 → 会员与订单」兑换，权益即时到账。")

@app.post("/api/profile/update")
async def api_profile_update(req: ProfileUpdateRequest, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    nickname = (req.nickname or "").strip()
    if len(nickname) < 2:
        raise HTTPException(status_code=400, detail="昵称至少 2 个字符")
    new_phone = (req.phone or "").strip()
    old_phone = (user.get("phone") or "")
    phone_verified = None
    if new_phone and new_phone != old_phone:
        if not is_valid_mobile(new_phone):
            raise HTTPException(status_code=400, detail="手机号格式不正确")
        if not req.code:
            raise HTTPException(status_code=400, detail="更换手机号需先获取并填写短信验证码")
        ok, msg = verify_code(new_phone, req.code, "bind")
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        phone_verified = 1
    update_profile(user["id"], nickname, new_phone or None, phone_verified)
    return {"status": "success", "user": to_public(get_current_user(request))}

@app.post("/api/sms/send")
async def api_sms_send(req: SMSRequest, request: Request):
    ip = _client_ip(request)
    err = _too_many(f"sms:ip:{ip}", _rl("sms_ip_per_hour", 20), 3600)
    if err:
        raise err
    ok, msg = send_code(req.mobile, req.scene, ip)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": msg}

@app.post("/api/sms/verify")
async def api_sms_verify(req: SMSVerifyRequest, request: Request):
    ip = _client_ip(request)
    err = _too_many(f"smsverify:ip:{ip}", _rl("smsverify_ip_per_min", 20), 60)
    if err:
        raise err
    err = _too_many(f"smsverify:acct:{req.mobile}", _rl("smsverify_acct_per_600s", 20), 600)
    if err:
        raise err
    ok, msg = verify_code(req.mobile, req.code, req.scene)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": msg}

class PasswordResetRequest(BaseModel):
    phone: str
    email: str = ""

class PasswordResetConfirm(BaseModel):
    phone: str
    code: str
    new_password: str
    email: str = ""

@app.post("/api/password/reset/request")
async def api_password_reset_request(req: PasswordResetRequest, request: Request):
    ip = _client_ip(request)
    err = _too_many(f"pwdreset:ip:{ip}", _rl("pwdreset_ip_per_hour", 10), 3600)
    if err:
        raise err
    phone = (req.phone or "").strip()
    if not is_valid_mobile(phone):
        raise HTTPException(status_code=400, detail="请输入正确的手机号")
    user = get_user_by_phone(phone)
    if not user:
        return {"status": "success", "phone_bound": False,
                "msg": "若该手机号已注册，验证码将发送至该号码"}
    ok, msg = send_code(phone, "reset", ip)
    if not ok:
        return {"status": "success", "phone_bound": True, "sms_sent": False,
                "msg": f"验证码发送失败：{msg}"}
    masked = (phone[:3] + "****" + phone[-4:]) if len(phone) >= 7 else "****"
    return {"status": "success", "phone_bound": True, "sms_sent": True,
            "masked_phone": masked, "msg": "验证码已发送至该手机号"}

@app.post("/api/password/reset/confirm")
async def api_password_reset_confirm(req: PasswordResetConfirm, request: Request):
    ip = _client_ip(request)
    err = _too_many(f"pwdreset2:ip:{ip}", _rl("pwdreset_confirm_per_min", 5), 60)
    if err:
        raise err
    phone = (req.phone or "").strip()
    if not is_valid_mobile(phone):
        raise HTTPException(status_code=400, detail="请输入正确的手机号")
    if not req.code or len(req.code) != 6:
        raise HTTPException(status_code=400, detail="请输入 6 位验证码")
    if not req.new_password or len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if not get_user_by_phone(phone):
        raise HTTPException(status_code=400, detail="该手机号未注册")
    ok, msg = verify_code(phone, req.code, "reset")
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    ok2, msg2 = reset_password_by_phone(phone, req.new_password)
    if not ok2:
        raise HTTPException(status_code=400, detail=msg2)
    return {"status": "success", "msg": "密码重置成功，请使用新密码登录"}

@app.get("/api/analysis/{rid}")
async def api_analysis_detail(rid: int, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    is_admin = bool(user.get("is_admin"))
    rec = get_analysis_by_id_any(rid) if is_admin else get_analysis_by_id(user["id"], rid)
    if not rec:
        raise HTTPException(status_code=404, detail="记录不存在")
    safe = {k: rec.get(k) for k in ("id", "stock_name", "stock_code", "mode",
                                    "model_id", "preference", "report_md", "created_at",
                                    "status", "error_msg")}
    safe["is_owner"] = int(rec.get("user_id") == user["id"])
    if is_admin and not safe["is_owner"]:
        safe["owner_email"] = rec.get("owner_email")
        safe["owner_nickname"] = rec.get("owner_nickname")
    return {"status": "success", "record": safe}

@app.get("/api/my/orders")
async def api_my_orders(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    orders = list_user_orders(user["id"], 50)
    tier = get_effective_tier(user)
    return {"status": "success",
            "is_vip": user.get("membership_level", 0) >= 1,
            "membership_level": user.get("membership_level", 0),
            "membership_expiry": user.get("membership_expiry"),
            "tier_name": tier["name"],
            "orders": orders}

class WatchModel(BaseModel):
    ts_code: str
    stock_name: str = ""
    note: str = ""

class AlertModel(BaseModel):
    ts_code: str
    stock_name: str = ""
    metric: str = "total_mv"
    operator: str = "gte"
    threshold: float = 0
    threshold2: float | None = None

class WatchMetaModel(BaseModel):
    ts_code: str
    group_name: str | None = None
    note: str | None = None
    cost: float | None = None
    quantity: int | None = None

@app.get("/api/watchlist")
async def api_watchlist(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return {"status": "success", "items": list_watch(user["id"])}

@app.get("/api/watchlist/quotes")
async def api_watchlist_quotes(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    codes_param = (request.query_params.get("codes") or "").strip()
    if codes_param:
        codes = [c.strip().upper() for c in codes_param.split(",") if c.strip()]
    else:
        items = list_watch(user["id"], 50)
        codes = [it["ts_code"] for it in items]
    if not codes:
        return {"status": "success", "quotes": {}}
    quotes = await run_in_threadpool(fetch_watch_quotes_sync, codes)
    return {"status": "success", "quotes": quotes}

@app.post("/api/watchlist")
async def api_watchlist_add(req: WatchModel, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    q = (req.ts_code or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="缺少股票代码")
    try:
        tsc, name = await get_stock_code(q)
    except Exception:
        tsc, name = None, None
    if not tsc:
        raise HTTPException(status_code=400, detail="无法识别该股票，请检查代码或名称")

    row = await run_in_threadpool(get_stock_by_ts_code, tsc)
    if row:
        display_name = (req.stock_name or "").strip() or row.get("name") or name or tsc
    else:
        try:
            _df, _st = await run_in_threadpool(
                lambda: fetch_datahub("daily", {"ts_code": tsc, "limit": 1}, timeout=15)
            )
        except Exception:
            _df = None
        if _df is None or getattr(_df, "empty", True):
            raise HTTPException(status_code=404, detail=f"未找到该股票（{tsc}），请检查代码是否正确")
        display_name = (req.stock_name or "").strip() or name or tsc

    try:
        existed = any(it.get("ts_code") == tsc for it in (list_watch(user["id"], 100) or []))
    except Exception:
        existed = False
    if existed:
        return {"status": "success", "msg": "已在自选中", "watched": True,
                "ts_code": tsc, "stock_name": display_name, "duplicate": True}

    ok, msg = add_watch(user["id"], tsc, display_name, req.note or None)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": msg, "watched": True,
            "ts_code": tsc, "stock_name": display_name, "duplicate": False}

@app.post("/api/watchlist/remove")
async def api_watchlist_remove(req: WatchModel, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    q = (req.ts_code or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="缺少股票代码")
    try:
        tsc, _ = await get_stock_code(q)
    except Exception:
        tsc = None
    target = tsc or q
    ok, msg = remove_watch(user["id"], target)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": msg, "watched": False, "ts_code": target}

@app.get("/api/watchlist/goals")
async def api_watchlist_goals(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    codes = [w.get("ts_code") for w in (list_watch(user["id"], 100) or []) if w.get("ts_code")]
    data = await run_in_threadpool(data_service.evaluate_watch_goals, user["id"], codes)
    return {"status": "success", **data}

@app.get("/api/watchlist/check")
async def api_watchlist_check(ts_code: str = "", request: Request = None):
    user = get_current_user(request)
    if not user:
        return {"status": "success", "logged_in": False, "watched": False,
                "ts_code": "", "stock_name": ""}
    q = (ts_code or "").strip()
    if not q:
        return {"status": "success", "logged_in": True, "watched": False,
                "ts_code": "", "stock_name": ""}
    try:
        tsc, name = await get_stock_code(q)
    except Exception:
        tsc, name = None, None
    if not tsc:
        return {"status": "success", "logged_in": True, "watched": False,
                "ts_code": "", "stock_name": ""}
    watched = is_watched(user["id"], tsc)
    return {"status": "success", "logged_in": True, "watched": watched,
            "ts_code": tsc, "stock_name": name or tsc}

@app.get("/api/alerts")
async def api_alerts(request: Request, ts_code: str = ""):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    items = list_alerts(user["id"], ts_code or None)
    return {"status": "success", "items": items}

@app.post("/api/alerts")
async def api_alerts_add(req: AlertModel, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if not (req.ts_code or "").strip():
        raise HTTPException(status_code=400, detail="缺少股票代码")
    try:
        tsc, name = await get_stock_code(req.ts_code.strip())
    except Exception:
        tsc, name = None, None
    if not tsc:
        raise HTTPException(status_code=400, detail="无法识别该股票")
    stock_name = (req.stock_name or "").strip() or name or tsc
    ok, msg, aid = add_alert(user["id"], tsc, stock_name, req.metric, req.operator,
                             req.threshold, req.threshold2)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": msg, "id": aid}

@app.post("/api/alerts/{aid}/toggle")
async def api_alerts_toggle(aid: int, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    a = get_alert(aid, user["id"])
    if not a:
        raise HTTPException(status_code=404, detail="提醒不存在")
    new_enabled = 0 if a.get("enabled") else 1
    fields = {"enabled": new_enabled}
    if new_enabled:
        fields["triggered"] = 0
        fields["triggered_at"] = None
    update_alert(aid, user["id"], **fields)
    return {"status": "success", "enabled": bool(new_enabled)}

@app.post("/api/alerts/{aid}/delete")
async def api_alerts_delete(aid: int, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    deleted = delete_alert(aid, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return {"status": "success", "msg": "已删除"}

@app.get("/api/alerts/unread")
async def api_alerts_unread(request: Request):
    user = get_current_user(request)
    if not user:
        return {"status": "success", "count": 0, "items": []}
    return {"status": "success",
            "count": count_unread_alerts(user["id"]),
            "items": list_triggered_alerts(user["id"], 20)}

@app.post("/api/watchlist/meta")
async def api_watchlist_meta(req: WatchMetaModel, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if not (req.ts_code or "").strip():
        raise HTTPException(status_code=400, detail="缺少股票代码")
    fields = {}
    if req.group_name is not None:
        fields["group_name"] = (req.group_name or "").strip()[:32]
    if req.note is not None:
        fields["note"] = (req.note or "").strip()[:255] or None
    if req.cost is not None:
        fields["cost"] = req.cost
    if req.quantity is not None:
        fields["quantity"] = req.quantity
    ok, msg = update_watch_meta(user["id"], req.ts_code.strip(), **fields)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": "已更新"}

class MarketVoteModel(BaseModel):
    vote: int = 1
    trade_date: str = ""

@app.get("/api/market-vote")
async def api_market_vote_get(request: Request, trade_date: str = ""):
    td = (trade_date or "").strip()
    if not td:
        try:
            td = await run_in_threadpool(data_service._latest_trade_date_datahub)
        except Exception:
            td = ""
    stats = await run_in_threadpool(get_market_vote_stats, td)
    user = get_current_user(request)
    mine = None
    if user and td:
        mine = await run_in_threadpool(get_user_market_vote, user["id"], td)
    return {"status": "success", "trade_date": td, "logged_in": bool(user),
            "mine": mine, **stats}

@app.post("/api/market-vote")
async def api_market_vote_post(req: MarketVoteModel, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再投票")
    td = (req.trade_date or "").strip()
    if not td:
        try:
            td = await run_in_threadpool(data_service._latest_trade_date_datahub)
        except Exception:
            td = ""
    if not td:
        raise HTTPException(status_code=400, detail="无法确定交易日，请稍后再试")
    vote = 1 if int(req.vote) == 1 else 0
    ok = await run_in_threadpool(upsert_market_vote, user["id"], td, vote)
    if not ok:
        raise HTTPException(status_code=500, detail="投票保存失败，请稍后重试")
    stats = await run_in_threadpool(get_market_vote_stats, td)
    return {"status": "success", "msg": "已记录您的观点", "trade_date": td,
            "mine": vote, **stats}

if __name__ == "__main__":
    reload_flag = os.environ.get("RELOAD", "1") != "0"
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=reload_flag)
