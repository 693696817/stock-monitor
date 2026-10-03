import asyncio
import datetime
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import ai_service
import config
import data_service
import fuyao_client
import settings
from auth import (
    count_admins,
    create_user_admin,
    delete_user,
    get_current_user,
    get_user_by_id,
    is_phone_email,
    mask_phone,
    set_session_cookie,
    to_public,
    update_user_admin,
)
from data_service import get_stock_data_summary
from data_source import get_pro
from db import (
    BACKTEST_PREFERENCES,
    adjust_bonus,
    count_stocks,
    create_notification,
    create_redeem_codes,
    delete_analysis_valuation,
    delete_news,
    delete_notification,
    format_redeem_code,
    get_admin_stats,
    get_news_by_gid,
    get_user_profile,
    get_valuation_detail,
    get_valuation_summary,
    list_admin_notifications,
    list_analysis_records,
    list_analysis_valuations,
    list_bonus_logs,
    list_feedback,
    list_invite_records,
    list_login_logs,
    list_membership_orders,
    list_news,
    list_redeem_codes,
    list_stocks,
    list_users,
    redeem_code_stats,
    scan_membership_expiry,
    set_news_pinned,
    update_feedback_status,
    void_redeem_codes,
)
from settings import all_settings, apply_runtime_settings, get_analysis_preferences
from stock_universe import get_sync_state, trigger_sync

from core.guard import _model_meta_wipe_check
from core.refresh import (refresh_analysis_preferences, refresh_pricing,
                          refresh_site_settings)
from core.security import require_admin
from core.serialize import _FEEDBACK_STATUS_REV, _feedback_to_public
from core.templates import STATIC_DIR, templates

router = APIRouter(tags=["后台管理"])

class AdminUserCreateModel(BaseModel):
    email: str
    password: str
    nickname: str = ""
    phone: str = ""
    phone_verified: int = 0
    membership_level: int = 0
    membership_expiry: str = ""
    points: int = 0
    is_admin: int = 0
    status: int = 1

class AdminUserUpdateModel(BaseModel):
    email: str = ""
    nickname: str = ""
    phone: str = ""
    phone_verified: int = 0
    membership_level: int = 0
    membership_expiry: str = ""
    points: int = 0
    is_admin: int | None = None
    status: int | None = None
    password: str = ""
    new_uid: int | None = None

class BonusAdjustModel(BaseModel):
    delta_normal: int = 0
    delta_deep: int = 0
    reason: str = ""

class ModelTestModel(BaseModel):
    model_id: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    alias: str = ""

class PanelPreviewModel(BaseModel):
    ts_code: str
    preference_id: str = ""
    groups: list = None

class FeedbackStatusModel(BaseModel):
    status: str

class SidebarModulesModel(BaseModel):
    modules: dict

class SettingsUpdateModel(BaseModel):
    settings: dict

class SettingsImportModel(BaseModel):
    settings: dict
    mode: str = "merge"

class NewsPinModel(BaseModel):
    pinned: bool = True
_MAX_PROBE_CONCURRENCY = 3

@router.post("/api/admin/stocks/sync")
async def api_admin_stocks_sync(request: Request):
    require_admin(request)
    started = trigger_sync()
    return {"status": "started" if started else "skipped",
            "message": "同步任务已启动" if started else "已有同步任务进行中"}

@router.get("/api/admin/stocks/status")
async def api_admin_stocks_status(request: Request):
    require_admin(request)
    state = get_sync_state()
    counts = await run_in_threadpool(count_stocks)
    return {"status": "success", "sync": state, "counts": counts}

@router.get("/api/admin/stocks/list")
async def api_admin_stocks_list(request: Request, page: int = 1, per_page: int = 20,
                                market: str = "", q: str = "", status: str = "L"):
    require_admin(request)
    try:
        total, rows = await run_in_threadpool(
            list_stocks, page, per_page, market or None, q or None, status or "L"
        )
        pages = (total + per_page - 1) // per_page if per_page else 1
        for r in rows:
            if r.get("updated_at") is not None:
                r["updated_at"] = str(r["updated_at"])
        return {"status": "success", "total": total, "page": page,
                "per_page": per_page, "pages": pages, "rows": rows}
    except Exception as e:
        print(f"admin stocks-list error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_dashboard.html",
                                      {"request": request, "active_page": "admin", "admin_active": "dashboard"})

@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_users.html",
                                      {"request": request, "active_page": "admin", "admin_active": "users"})

@router.get("/admin/records", response_class=HTMLResponse)
async def admin_records_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_records.html",
                                      {"request": request, "active_page": "admin", "admin_active": "records"})

@router.get("/admin/feedback", response_class=HTMLResponse)
async def admin_feedback_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_feedback.html",
                                      {"request": request, "active_page": "admin", "admin_active": "feedback"})

@router.get("/admin/sidebar", response_class=HTMLResponse)
async def admin_sidebar_page(request: Request):
    require_admin(request)
    import sidebar_modules as smod
    cfg = settings.get_sidebar_modules()
    return templates.TemplateResponse(request, "admin_sidebar.html", {
        "request": request,
        "active_page": "admin",
        "admin_active": "sidebar",
        "modules": cfg["modules"],
        "placements": smod.PLACEMENTS,
        "by_placement": cfg["placements"],
        "defs": {m["key"]: m for m in smod.MODULES},
    })

@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_settings.html",
                                      {"request": request, "active_page": "admin", "admin_active": "settings"})

@router.get("/api/admin/stats")
async def api_admin_stats(request: Request):
    require_admin(request)
    try:
        return get_admin_stats()
    except Exception as e:
        print(f"admin stats error: {e}")
        raise HTTPException(status_code=500, detail="统计失败")

@router.get("/api/admin/users")
async def api_admin_users(request: Request, page: int = 1, per_page: int = 20):
    require_admin(request)
    try:
        total, rows = list_users(page=page, per_page=per_page)
        return {"total": total, "rows": rows, "page": page, "per_page": per_page}
    except Exception as e:
        print(f"admin users error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.post("/api/admin/users/create")
async def api_admin_user_create(body: AdminUserCreateModel, request: Request):
    require_admin(request)
    ok, msg, user = create_user_admin(
        email=body.email,
        password=body.password,
        nickname=body.nickname or None,
        phone=body.phone or None,
        phone_verified=body.phone_verified,
        membership_level=body.membership_level,
        membership_expiry=body.membership_expiry or None,
        points=body.points,
        is_admin=body.is_admin,
        status=body.status,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": msg, "user": to_public(user) if user else None}

@router.post("/api/admin/users/{uid}")
async def api_admin_user_update(uid: int, body: AdminUserUpdateModel, request: Request):
    admin = require_admin(request)
    if admin["id"] == uid and body.is_admin == 0:
        raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
    ok, msg = update_user_admin(
        uid,
        email=body.email or None,
        nickname=body.nickname,
        phone=body.phone,
        phone_verified=body.phone_verified,
        membership_level=body.membership_level,
        membership_expiry=body.membership_expiry or None,
        points=body.points,
        is_admin=body.is_admin,
        status=body.status,
        password=body.password or None,
        new_uid=body.new_uid,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    response = JSONResponse({"status": "success", "msg": msg})
    if admin["id"] == uid and body.new_uid is not None and body.new_uid != uid:
        set_session_cookie(response, body.new_uid, request=request)
    return response

@router.post("/api/admin/users/{uid}/delete")
async def api_admin_user_delete(uid: int, request: Request):
    admin = require_admin(request)
    if admin["id"] == uid:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    target = get_user_by_id(uid)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.get("is_admin") and count_admins() <= 1:
        raise HTTPException(status_code=400, detail="不能删除最后一个管理员")
    ok, msg = delete_user(uid)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": msg}

@router.get("/api/admin/user/{uid}")
async def api_admin_user_profile(uid: int, request: Request):
    require_admin(request)
    profile = get_user_profile(uid)
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在")
    user = profile["user"]
    for k in ("password_hash", "salt"):
        user.pop(k, None)
    email = user.get("email") or ""
    user["email_display"] = (user.get("phone") + "（手机账号）") if is_phone_email(email) else email
    user["phone_masked"] = mask_phone(user.get("phone")) if user.get("phone") else ""
    return {"status": "success", "profile": profile}

@router.post("/api/admin/user/{uid}/bonus")
async def api_admin_user_bonus_adjust(uid: int, body: BonusAdjustModel, request: Request):
    admin = require_admin(request)
    if get_user_by_id(uid) is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    ok, msg, balances = adjust_bonus(
        uid,
        delta_normal=body.delta_normal,
        delta_deep=body.delta_deep,
        admin_id=admin["id"],
        reason=(body.reason or "").strip(),
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "msg": msg, "balances": balances}

@router.get("/api/admin/user/{uid}/bonus-logs")
async def api_admin_user_bonus_logs(uid: int, request: Request, page: int = 1, per_page: int = 20):
    require_admin(request)
    total, rows = list_bonus_logs(uid=uid, page=page, per_page=per_page)
    return {"total": total, "rows": rows, "page": page, "per_page": per_page}

@router.get("/api/admin/bonus-logs")
async def api_admin_bonus_logs(request: Request, page: int = 1, per_page: int = 20):
    require_admin(request)
    total, rows = list_bonus_logs(uid=None, page=page, per_page=per_page)
    return {"total": total, "rows": rows, "page": page, "per_page": per_page}

@router.get("/api/admin/records")
async def api_admin_records(request: Request, page: int = 1, per_page: int = 20, mode: str = None):
    require_admin(request)
    try:
        total, rows = list_analysis_records(page=page, per_page=per_page, mode=mode)
        return {"total": total, "rows": rows, "page": page, "per_page": per_page}
    except Exception as e:
        print(f"admin records error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/api/admin/feedback")
async def api_admin_feedback(request: Request, page: int = 1, per_page: int = 20, status: int = None):
    require_admin(request)
    try:
        total, rows = list_feedback(page=page, per_page=per_page, status=status)
        return {
            "total": total,
            "rows": [_feedback_to_public(r) for r in rows],
            "page": page, "per_page": per_page,
        }
    except Exception as e:
        print(f"admin feedback error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/api/admin/panel/groups")
async def api_admin_panel_groups(request: Request):
    require_admin(request)
    groups = []
    for gid, cfg in data_service.DATA_GROUPS.items():
        groups.append({
            "id": gid,
            "title": cfg.get("title"),
            "fields": list(cfg.get("fields") or []),
            "field_count": len(cfg.get("fields") or []),
            "source_api": (cfg.get("task") or "基础任务").replace("task_", ""),
        })
    return {"status": "success", "groups": groups,
            "defaults": data_service.PREFERENCE_DATA_GROUPS,
            "base_groups": data_service._BASE_GROUPS}

@router.post("/api/admin/panel/preview")
async def api_admin_panel_preview(body: PanelPreviewModel, request: Request):
    require_admin(request)
    ts_code = (body.ts_code or "").strip()
    if not ts_code:
        raise HTTPException(status_code=400, detail="请填写股票代码")
    try:
        picked = data_service.resolve_data_groups(body.preference_id or None, body.groups)
        text = await get_stock_data_summary(ts_code, preference_id=body.preference_id or None,
                                            groups=body.groups)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败：{e}")
    return {"status": "success", "ts_code": ts_code,
            "preference_id": body.preference_id or "",
            "groups": picked, "panel": text, "length": len(text or "")}

@router.get("/api/admin/models/health")
async def api_admin_models_health(request: Request):
    require_admin(request)
    return {"status": "success", "health": settings.get_model_health(),
            "models": settings.get_all_ai_models(include_disabled=True)}

_MODEL_LOGO_DIR = os.path.join(STATIC_DIR, "uploads", "models")
_MODEL_LOGO_ALLOWED = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

@router.post("/api/admin/models/upload-logo")
async def api_admin_models_upload_logo(request: Request, file: UploadFile = File(...)):
    require_admin(request)
    fname = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = os.path.splitext(fname)[1].lower()
    if ext not in _MODEL_LOGO_ALLOWED:
        raise HTTPException(status_code=400, detail=f"仅支持图片格式（{'/'.join(sorted(_MODEL_LOGO_ALLOWED))}）")
    try:
        os.makedirs(_MODEL_LOGO_DIR, exist_ok=True)
    except Exception as e:
        print(f"model logo mkdir error: {e}")
        raise HTTPException(status_code=500, detail="上传目录创建失败")
    data = await file.read()
    if len(data) <= 0:
        raise HTTPException(status_code=400, detail="上传内容为空")
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 2MB")
    import uuid as _uuid
    out_name = _uuid.uuid4().hex + ext
    out_path = os.path.join(_MODEL_LOGO_DIR, out_name)
    try:
        with open(out_path, "wb") as f:
            f.write(data)
    except Exception as e:
        print(f"model logo save error: {e}")
        raise HTTPException(status_code=500, detail="图片保存失败")
    print(f"[upload] 模型 Logo 已保存: {out_path}")
    return {"status": "success", "url": f"/static/uploads/models/{out_name}"}

@router.post("/api/admin/models/test")
async def api_admin_model_test(body: ModelTestModel, request: Request):
    require_admin(request)
    mid = (body.model_id or "").strip()
    if not mid:
        raise HTTPException(status_code=400, detail="缺少 model_id，无法定位要检测的模型")

    draft = bool((body.base_url or "").strip() and (body.model or "").strip())
    if draft:
        res = await ai_service.probe_endpoint(
            body.base_url.strip(), (body.api_key or "").strip(), body.model.strip(),
            alias=(body.alias or "").strip() or body.model.strip(),
            channel="（未保存的草稿）", timeout=90.0, extra={"draft": True})
    else:
        res = await ai_service.probe_model(mid, timeout=90.0, strict=True)
    settings.update_model_health(mid, res)
    return {"status": "success", "model_id": mid, "draft": draft, "result": res}

@router.post("/api/admin/models/test-all")
async def api_admin_model_test_all(request: Request):
    require_admin(request)
    models = settings.get_all_ai_models()
    keys = [m["id"] for m in models]
    sem = asyncio.Semaphore(_MAX_PROBE_CONCURRENCY)

    async def _one(mid):
        try:
            async with sem:
                return mid, await ai_service.probe_model(mid, timeout=90.0, strict=True)
        except Exception as e:
            return mid, {"ok": False, "ms": 0, "error": str(e)[:120]}

    results = await asyncio.gather(*[_one(k) for k in keys])
    report = {}
    for mid, res in results:
        report[mid] = dict(res, checked_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    settings.set_model_health(report)
    settings.prune_model_health()
    ok_n = sum(1 for v in report.values() if v.get("ok"))
    busy_n = sum(1 for v in report.values() if not v.get("ok") and v.get("timeout_only"))
    return {"status": "success", "total": len(report), "ok": ok_n,
            "busy": busy_n,
            "failed": len(report) - ok_n - busy_n, "health": report}

@router.post("/api/admin/feedback/{fid}/status")
async def api_admin_feedback_status(fid: int, body: FeedbackStatusModel, request: Request):
    require_admin(request)
    if body.status not in _FEEDBACK_STATUS_REV:
        raise HTTPException(status_code=400, detail="非法状态值")
    try:
        rc = update_feedback_status(fid, _FEEDBACK_STATUS_REV[body.status])
        if rc == 0:
            raise HTTPException(status_code=404, detail="反馈不存在")
        return {"status": "success", "id": fid, "status_value": body.status}
    except HTTPException:
        raise
    except Exception as e:
        print(f"admin feedback status error: {e}")
        raise HTTPException(status_code=500, detail="更新失败")

@router.get("/api/admin/settings")
async def api_admin_settings(request: Request):
    require_admin(request)
    return {"status": "success", "settings": all_settings()}

@router.get("/api/admin/sidebar")
async def api_admin_sidebar_get(request: Request):
    require_admin(request)
    return {"status": "success", **settings.get_sidebar_modules()}

@router.post("/api/admin/sidebar")
async def api_admin_sidebar_save(body: SidebarModulesModel, request: Request):
    require_admin(request)
    try:
        clean = settings.set_sidebar_modules(body.modules)
        return {"status": "success", "count": len(clean)}
    except Exception as e:
        print(f"admin sidebar save error: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")

@router.post("/api/admin/settings")
async def api_admin_settings_update(body: SettingsUpdateModel, request: Request):
    require_admin(request)
    if "AI_MODEL_CHANNELS" in body.settings:
        _wipe_msg = _model_meta_wipe_check(body.settings["AI_MODEL_CHANNELS"])
        if _wipe_msg:
            raise HTTPException(status_code=409, detail=_wipe_msg)
    updated = {}
    for key, value in body.settings.items():
        if key not in settings.SETTING_KEYS:
            raise HTTPException(status_code=400, detail=f"未知设置键: {key}")
        settings.set_setting(key, str(value))
        updated[key] = str(value)
    if "AI_MODEL_CHANNELS" in updated:
        try:
            settings.prune_model_health()
        except Exception as e:
            print(f"prune model health error: {e}")
    try:
        apply_runtime_settings()
        refresh_site_settings(request.app)
        refresh_pricing(request.app)
        refresh_analysis_preferences(request.app)
    except Exception as e:
        print(f"apply runtime settings error: {e}")
        return {"status": "partial", "updated": updated,
                "warning": "设置已保存，但热重载数据源失败，请检查配置后重启。"}
    return {"status": "success", "updated": updated, "msg": "设置已保存并即时生效"}

@router.get("/api/admin/settings/export")
async def api_admin_settings_export(request: Request):
    require_admin(request)
    from datetime import datetime as _dt
    data = {
        "exported_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app": "A股棱镜",
        "settings": settings.all_settings(),
    }
    return JSONResponse(content=data)

@router.post("/api/admin/settings/import")
async def api_admin_settings_import(body: SettingsImportModel, request: Request):
    require_admin(request)
    if not isinstance(body.settings, dict) or not body.settings:
        raise HTTPException(status_code=400, detail="导入内容为空或格式不正确（应为 {settings: {...}}）")
    unknown = [k for k in body.settings if k not in settings.SETTING_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知设置键: {', '.join(unknown[:10])}")
    updated = {}
    for key, value in body.settings.items():
        try:
            settings.set_setting(key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            updated[key] = value
        except Exception as e:
            print(f"settings import key {key} error: {e}")
    try:
        apply_runtime_settings()
        refresh_site_settings(request.app)
        refresh_pricing(request.app)
        refresh_analysis_preferences(request.app)
    except Exception as e:
        print(f"apply runtime settings error: {e}")
        return {"status": "partial", "updated": len(updated),
                "warning": "设置已导入，但热重载数据源失败，请检查配置后重启。"}
    return {"status": "success", "updated": len(updated), "msg": f"已导入 {len(updated)} 项设置并即时生效"}

@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_logs.html",
                                      {"request": request, "active_page": "admin", "admin_active": "logs"})

@router.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_orders.html",
                                      {"request": request, "active_page": "admin", "admin_active": "orders"})

@router.get("/admin/invites", response_class=HTMLResponse)
async def admin_invites_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_invites.html",
                                      {"request": request, "active_page": "admin", "admin_active": "invites"})

@router.get("/api/admin/login-logs")
async def api_admin_login_logs(request: Request, page: int = 1, per_page: int = 20, success: int = None):
    require_admin(request)
    try:
        s = None if success is None else (1 if success == 1 else 0)
        total, rows = list_login_logs(page=page, per_page=per_page, success=s)
        return {"total": total, "rows": rows, "page": page, "per_page": per_page}
    except Exception as e:
        print(f"admin login-logs error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/api/admin/orders")
async def api_admin_orders(request: Request, page: int = 1, per_page: int = 20):
    require_admin(request)
    try:
        total, rows = list_membership_orders(page=page, per_page=per_page)
        return {"total": total, "rows": rows, "page": page, "per_page": per_page}
    except Exception as e:
        print(f"admin orders error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/api/admin/invites")
async def api_admin_invites(request: Request, page: int = 1, per_page: int = 20):
    require_admin(request)
    try:
        total, rows = list_invite_records(page=page, per_page=per_page)
        return {"total": total, "rows": rows, "page": page, "per_page": per_page}
    except Exception as e:
        print(f"admin invites error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/admin/redeem", response_class=HTMLResponse)
async def admin_redeem_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_redeem.html",
                                      {"request": request, "active_page": "admin",
                                       "admin_active": "redeem",
                                       "plans": getattr(request.app.state, "pricing", []) or []})

@router.get("/api/admin/redeem/list")
async def api_admin_redeem_list(request: Request, page: int = 1, per_page: int = 20,
                                batch: str = None, status: int = None, kw: str = None):
    require_admin(request)
    try:
        total, rows = list_redeem_codes(page=page, per_page=per_page,
                                        batch_no=batch, status=status, kw=kw)
        now = datetime.datetime.now()
        for r in rows:
            r["code_display"] = format_redeem_code(r.get("code"))
            exp = r.get("expire_at")
            r["expired"] = bool(exp and exp < now)
            for k in ("expire_at", "used_at", "created_at"):
                if r.get(k):
                    r[k] = str(r[k])[:19]
            r["benefit_text"] = _describe_redeem_spec({
                "level": r.get("level"), "days": r.get("days"),
                "bonus_normal": r.get("bonus_normal"), "bonus_deep": r.get("bonus_deep"),
            })
        return {"total": total, "rows": rows, "page": page, "per_page": per_page,
                "stats": redeem_code_stats()}
    except Exception as e:
        print(f"admin redeem list error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/api/admin/redeem/preview")
async def api_admin_redeem_preview(request: Request, plan_key: str = "",
                                   sku_index: int = 0):
    require_admin(request)
    spec = _resolve_redeem_spec(str(plan_key or "").strip(), sku_index)
    if not spec:
        return {"status": "fail", "message": "该套餐/规格不支持发码（免费版或解析不出权益）"}
    return {"status": "success", "spec": spec, "text": _describe_redeem_spec(spec)}

@router.post("/api/admin/redeem/generate")
async def api_admin_redeem_generate(request: Request):
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")

    spec = _resolve_redeem_spec(str(body.get("plan_key") or "").strip(),
                                body.get("sku_index"))
    if not spec:
        raise HTTPException(status_code=400, detail="未知的套餐或规格（免费版不支持发码）")

    try:
        count = max(1, min(int(body.get("count") or 1), 500))
    except Exception:
        count = 1

    expire_at = None
    try:
        ed = int(body.get("expire_days") or 0)
        if ed > 0:
            expire_at = (datetime.datetime.now() +
                         datetime.timedelta(days=min(ed, 3650))).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        expire_at = None

    admin_uid = None
    try:
        u = get_current_user(request)
        admin_uid = (u or {}).get("id")
    except Exception:
        admin_uid = None

    try:
        batch_no, codes = create_redeem_codes(
            spec["plan_key"], spec["plan_name"], spec["sku_label"],
            spec["level"], spec["days"], spec["bonus_normal"], spec["bonus_deep"],
            count, expire_at, admin_uid, str(body.get("remark") or "")[:255],
        )
    except Exception as e:
        print(f"admin redeem generate error: {e}")
        raise HTTPException(status_code=500, detail="生成失败")

    if not codes:
        raise HTTPException(status_code=500, detail="生成失败，未产出任何兑换码")
    return {"status": "success", "batch_no": batch_no, "count": len(codes),
            "codes": [format_redeem_code(c) for c in codes], "spec": spec,
            "spec_text": _describe_redeem_spec(spec),
            "raw_codes": list(codes)}

@router.post("/api/admin/redeem/void")
async def api_admin_redeem_void(request: Request):
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    raw = body.get("codes") or []
    if isinstance(raw, str):
        raw = [raw]
    codes = [str(c).strip().upper().replace("-", "").replace(" ", "") for c in raw]
    codes = [c for c in codes if c]
    if not codes:
        raise HTTPException(status_code=400, detail="请先选择要作废的兑换码")
    try:
        n = void_redeem_codes(codes)
    except Exception as e:
        print(f"admin redeem void error: {e}")
        raise HTTPException(status_code=500, detail="作废失败")
    return {"status": "success", "voided": n,
            "message": f"已作废 {n} 张（已使用/不存在的码不会被作废）"}

@router.get("/api/admin/redeem/export")
async def api_admin_redeem_export(request: Request, batch: str = None, status: int = 0):
    require_admin(request)
    try:
        _total, rows = list_redeem_codes(page=1, per_page=5000,
                                         batch_no=batch, status=status, kw=None)
    except Exception as e:
        print(f"admin redeem export error: {e}")
        raise HTTPException(status_code=500, detail="导出失败")
    import io as _io
    buf = _io.StringIO()
    buf.write("兑换码,套餐,规格,等级,天数,普通次数,深度次数,批次,有效期,状态\n")
    for r in rows:
        st = {0: "未使用", 1: "已使用", 2: "已作废"}.get(int(r.get("status") or 0), "-")
        buf.write("%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" % (
            r.get("code"), r.get("plan_name"), r.get("sku_label"),
            r.get("level"), r.get("days"), r.get("bonus_normal"), r.get("bonus_deep"),
            r.get("batch_no"), r.get("expire_at") or "长期", st))
    fname = "redeem_%s.csv" % (batch or "all")
    return Response(content=buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})

@router.get("/admin/notices", response_class=HTMLResponse)
async def admin_notices_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_notices.html",
                                      {"request": request, "active_page": "admin",
                                       "admin_active": "notices"})

@router.get("/api/admin/notices")
async def api_admin_notices(request: Request, page: int = 1, per_page: int = 20):
    require_admin(request)
    try:
        total, rows = list_admin_notifications(page=page, per_page=per_page)
        return {"total": total, "rows": rows, "page": page, "per_page": per_page}
    except Exception as e:
        print(f"admin notices error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.post("/api/admin/notices/create")
async def api_admin_notice_create(request: Request):
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    content = str(body.get("content") or "").strip() or None
    link = str(body.get("link") or "").strip() or None
    level = str(body.get("level") or "info").strip()
    if level not in ("info", "success", "warning", "danger"):
        level = "info"
    uid = body.get("user_id")
    try:
        uid = int(uid) if (uid not in (None, "", 0)) else None
    except Exception:
        raise HTTPException(status_code=400, detail="用户 ID 不合法")
    ntype = str(body.get("type") or "system").strip()[:24] or "system"
    expire_at = None
    try:
        ed = int(body.get("expire_days") or 0)
        if ed > 0:
            expire_at = (datetime.datetime.now() +
                         datetime.timedelta(days=min(ed, 365))).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        expire_at = None
    nid = create_notification(uid, ntype, title, content, link=link, level=level,
                              expire_at=expire_at)
    if not nid:
        raise HTTPException(status_code=400, detail="创建失败（可能重复）")
    return {"status": "success", "id": nid}

@router.post("/api/admin/notices/delete")
async def api_admin_notice_delete(request: Request):
    require_admin(request)
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
    n = delete_notification(nid)
    if not n:
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"status": "success"}

@router.post("/api/admin/notices/scan-expiry")
async def api_admin_scan_expiry(request: Request):
    require_admin(request)
    try:
        created, scanned = scan_membership_expiry()
    except Exception as e:
        print(f"scan membership expiry error: {e}")
        raise HTTPException(status_code=500, detail="扫描失败")
    return {"status": "success", "created": created, "scanned": scanned}

@router.get("/admin/valuation", response_class=HTMLResponse)
async def admin_valuation_page(request: Request):
    require_admin(request)
    prefs = [{"id": p.get("id"), "name": p.get("name")}
             for p in (get_analysis_preferences() or [])
             if p.get("id") in BACKTEST_PREFERENCES]
    return templates.TemplateResponse(
        request, "admin_valuation.html",
        {"request": request, "active_page": "admin", "admin_active": "valuation",
         "prefs": prefs})

@router.get("/api/admin/valuation")
async def api_admin_valuation(request: Request, page: int = 1, per_page: int = 20,
                              preference: str = None, model: str = None, kw: str = None,
                              min_score: float = None, max_score: float = None):
    require_admin(request)
    try:
        total, rows = list_analysis_valuations(
            page=page, per_page=per_page, preference=preference or None,
            model=model or None, kw=(kw or "").strip() or None,
            min_score=min_score, max_score=max_score)
        return {"total": total, "rows": rows, "page": page, "per_page": per_page}
    except Exception as e:
        print(f"admin valuation error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/api/admin/valuation/summary")
async def api_admin_valuation_summary(request: Request):
    require_admin(request)
    try:
        return get_valuation_summary()
    except Exception as e:
        print(f"admin valuation summary error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/api/admin/valuation/{vid}")
async def api_admin_valuation_detail(request: Request, vid: int):
    require_admin(request)
    try:
        row = get_valuation_detail(vid)
        if not row:
            raise HTTPException(status_code=404, detail="记录不存在")
        return row
    except HTTPException:
        raise
    except Exception as e:
        print(f"admin valuation detail error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.post("/api/admin/valuation/{vid}/delete")
async def api_admin_valuation_delete(vid: int, request: Request):
    require_admin(request)
    try:
        ok = delete_analysis_valuation(vid)
        if not ok:
            raise HTTPException(status_code=404, detail="记录不存在")
        return {"status": "success", "id": vid}
    except HTTPException:
        raise
    except Exception as e:
        print(f"admin valuation delete error: {e}")
        raise HTTPException(status_code=500, detail="删除失败")

@router.get("/admin/news", response_class=HTMLResponse)
async def admin_news_page(request: Request):
    require_admin(request)
    return templates.TemplateResponse(request, "admin_news.html",
                                      {"request": request, "active_page": "admin", "admin_active": "news"})

@router.get("/api/admin/news")
async def api_admin_news(request: Request, page: int = 1, per_page: int = 20, pinned: int = None):
    require_admin(request)
    try:
        limit = min(200, max(1, int(per_page)))
        offset = max(0, int(page) - 1) * limit
        total, rows = list_news(limit=limit, offset=offset)
        items = [data_service._row_to_news_item(r) for r in rows]
        if pinned is not None:
            items = [it for it in items if bool(it.get("pinned")) == bool(pinned)]
        return {"status": "success", "total": total, "rows": items, "page": page, "per_page": per_page}
    except Exception as e:
        print(f"admin news error: {e}")
        raise HTTPException(status_code=500, detail="查询失败")

@router.get("/api/admin/news/{gid}")
async def api_admin_news_detail(gid: int, request: Request):
    require_admin(request)
    row = get_news_by_gid(gid)
    if not row:
        raise HTTPException(status_code=404, detail="快讯不存在")
    return {"status": "success", "news": data_service._row_to_news_item(row),
            "raw": {"category": row.get("category"), "create_timestamp": row.get("create_timestamp")}}

@router.post("/api/admin/news/{gid}/pin")
async def api_admin_news_pin(gid: int, body: NewsPinModel, request: Request):
    require_admin(request)
    val = set_news_pinned(gid, body.pinned)
    if val is None:
        raise HTTPException(status_code=404, detail="快讯不存在")
    data_service.invalidate_news_cache()
    return {"status": "success", "gid": gid, "pinned": bool(val)}

@router.post("/api/admin/news/{gid}/delete")
async def api_admin_news_delete(gid: int, request: Request):
    require_admin(request)
    n = delete_news(gid)
    if n == 0:
        raise HTTPException(status_code=404, detail="快讯不存在")
    data_service.invalidate_news_cache()
    return {"status": "success", "gid": gid}

@router.post("/api/admin/test-datasource")
async def api_admin_test_datasource(request: Request):
    require_admin(request)
    try:
        pro = get_pro()
        df = pro.trade_cal(exchange="", start_date="20260101", end_date="20260630", is_open="1")
        if df is None or getattr(df, "empty", True):
            return {"status": "success", "ok": False,
                    "msg": "连接成功，但 trade_cal 返回空数据（可能该 Token 无此接口权限）"}
        return {"status": "success", "ok": True,
                "msg": f"连接成功，trade_cal 返回 {len(df)} 条交易日记录"}
    except Exception as e:
        return {"status": "success", "ok": False,
                "msg": f"连接失败：{type(e).__name__}: {str(e)[:200]}"}

@router.get("/api/admin/datahub-catalog")
async def api_admin_datahub_catalog(request: Request):
    require_admin(request)
    cat = settings.get_datahub_catalog()
    groups = {}
    for item in cat:
        c = item.get("category", "其他")
        groups.setdefault(c, []).append(item)
    categories = {}
    for c, items in groups.items():
        subs = {}
        for it in items:
            subs.setdefault(it.get("sub", ""), []).append(it)
        categories[c] = [
            {"sub": s, "count": len(apis), "apis": apis}
            for s, apis in sorted(subs.items())
        ]
    return {
        "status": "success",
        "total": len(cat),
        "category_count": len(categories),
        "categories": categories,
        "doc_url": "https://tushare.pro/document/2",
        "base_url": settings.get_setting("DATAHUB_BASE_URL", ""),
    }

@router.post("/api/admin/test-datahub-api/{api_name}")
async def api_admin_test_datahub_api(api_name: str, request: Request):
    require_admin(request)
    from datahub_catalog import get_api_info
    info = get_api_info(api_name)
    if not info:
        return {"status": "success", "ok": False,
                "msg": f"接口 {api_name} 不在 DATAHUB 目录中", "rows": 0}
    params = {}
    pnames = set((info.get("params") or {}).keys())
    if "ts_code" in pnames:
        params["ts_code"] = "600519.SH"
    if "trade_date" in pnames and "start_date" in pnames:
        params["trade_date"] = ""
        del params["trade_date"]
    if "start_date" in pnames:
        params["start_date"] = "20260101"
        params["end_date"] = "20260630"
    if info.get("category") == "股票数据" and info.get("sub") == "基础数据" and api_name == "stock_basic":
        params = {"list_status": "L", "limit": 1}
    try:
        pro = get_pro()
        fn = getattr(pro, api_name, None)
        if fn is None:
            return {"status": "success", "ok": False,
                    "msg": f"当前数据源适配层不支持接口 {api_name}", "rows": 0}
        df = fn(**params) if params else fn()
        rows = 0 if df is None else (len(df) if hasattr(df, "__len__") else 0)
        if rows == 0:
            msg = "调用成功但返回 0 行（可能无权限/无数据/参数不匹配），字段清单见目录说明"
        else:
            cols = []
            try:
                cols = [str(c) for c in df.columns] if getattr(df, "columns", None) is not None else []
            except Exception:
                cols = []
            col_info = (f"，字段 {len(cols)} 个：{', '.join(cols[:12])}" + ("..." if len(cols) > 12 else "")) if cols else ""
            msg = f"调用成功，返回 {rows} 行" + col_info
        return {"status": "success", "ok": rows > 0, "msg": msg, "rows": rows,
                "name": info.get("name"), "params_used": params}
    except Exception as e:
        return {"status": "success", "ok": False,
                "msg": f"{type(e).__name__}: {str(e)[:300]}", "rows": 0,
                "name": info.get("name")}

@router.get("/api/admin/lixinger-catalog")
async def api_admin_lixinger_catalog(request: Request):
    require_admin(request)
    from lixinger_catalog import USAGE, BASE_URL
    cat = settings.get_lixinger_catalog()
    regions = {}
    for item in cat:
        r = item.get("region", "其他")
        regions.setdefault(r, {}).setdefault(item.get("category", "其他"), []).append(item)
    region_out = {}
    for r, cats in regions.items():
        cat_list = []
        for c, apis in cats.items():
            cat_list.append({"category": c, "count": len(apis), "apis": apis})
        region_out[r] = {
            "category_count": len(cat_list),
            "categories": sorted(cat_list, key=lambda x: x["category"]),
        }
    return {
        "status": "success",
        "total": len(cat),
        "region_count": len(region_out),
        "regions": region_out,
        "usage": USAGE,
        "doc_url": USAGE.get("doc_index", ""),
        "base_url": BASE_URL,
    }

@router.post("/api/admin/test-lixinger-api/{api:path}")
async def api_admin_test_lixinger_api(api: str, request: Request):
    require_admin(request)
    import requests as _requests
    from lixinger_catalog import get_api_info, BASE_URL
    norm = api if api.startswith("/") else "/" + api
    if not norm.startswith("/api/"):
        norm = "/api" + norm
    info = get_api_info(norm)
    if not info:
        return {"status": "success", "ok": False,
                "msg": f"接口 {norm} 不在 Lixinger 目录中", "rows": 0}
    token = getattr(config, "LIXINGER_TOKEN", "")
    if not token:
        return {"status": "success", "ok": False,
                "msg": "未配置 LIXINGER_TOKEN（请在 .env 或后台设置）", "rows": 0}
    body = dict(info.get("probe") or {})
    body["token"] = token
    url = BASE_URL + norm
    headers = {"Content-Type": "application/json", "Accept-Encoding": "gzip"}
    last_err = ""
    for attempt in range(3):
        try:
            resp = _requests.post(url, json=body, headers=headers, timeout=30)
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:200]}"
            if attempt < 2:
                time.sleep(1 * (attempt + 1))
                continue
            return {"status": "success", "ok": False,
                    "msg": f"网络请求失败（重试 {attempt + 1} 次）：{last_err}", "rows": 0,
                    "name": info.get("name")}
        if resp.status_code == 429:
            last_err = "HTTP 429 Too Many Request（触发限频）"
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return {"status": "success", "ok": False,
                    "msg": "触发限频（HTTP 429），请稍后重试（限频：1000 次/分、36 次/秒）", "rows": 0,
                    "name": info.get("name")}
        try:
            j = resp.json()
        except Exception:
            return {"status": "success", "ok": False,
                    "msg": f"响应非 JSON，HTTP {resp.status_code}：{resp.text[:160]}", "rows": 0,
                    "name": info.get("name")}
        code = j.get("code")
        if code != 1:
            return {"status": "success", "ok": False,
                    "msg": f"业务错误 code={code} msg={j.get('message', '')}", "rows": 0,
                    "name": info.get("name")}
        data = j.get("data")
        rows = 0
        if isinstance(data, list):
            rows = len(data)
        elif isinstance(data, dict):
            rows = 1
        if rows == 0:
            msg = "调用成功但返回 0 行（可能无权限/无数据/参数不匹配）"
        else:
            msg = f"调用成功，返回 {rows} 行"
        return {"status": "success", "ok": rows > 0, "msg": msg, "rows": rows,
                "name": info.get("name"), "params_used": body}
    return {"status": "success", "ok": False, "msg": last_err or "未知失败", "rows": 0,
            "name": info.get("name")}

@router.get("/api/admin/fuyao-catalog")
async def api_admin_fuyao_catalog(request: Request):
    require_admin(request)
    from fuyao_catalog import USAGE, BASE_URL
    cat = settings.get_fuyao_catalog()
    regions = {}
    for item in cat:
        r = item.get("region", "其他")
        regions.setdefault(r, {}).setdefault(item.get("category", "其他"), []).append(item)
    region_out = {}
    for r, cats in regions.items():
        cat_list = []
        for c, apis in cats.items():
            cat_list.append({"category": c, "count": len(apis), "apis": apis})
        region_out[r] = {
            "category_count": len(cat_list),
            "categories": sorted(cat_list, key=lambda x: x["category"]),
        }
    return {
        "status": "success",
        "total": len(cat),
        "region_count": len(region_out),
        "regions": region_out,
        "usage": USAGE,
        "doc_url": USAGE.get("doc_index", ""),
        "base_url": BASE_URL,
        "configured": fuyao_client.configured(),
        "enabled": settings.fuyao_enabled(),
    }

@router.post("/api/admin/test-fuyao-api/{api:path}")
async def api_admin_test_fuyao_api(api: str, request: Request):
    require_admin(request)
    from fuyao_catalog import get_api_info
    norm = "/" + str(api).lstrip("/")
    info = get_api_info(norm)
    if not info:
        return {"status": "success", "ok": False,
                "msg": f"接口 {norm} 不在伏尧目录中", "rows": 0}
    params = dict(info.get("probe") or {})
    t0 = time.time()
    data, err = fuyao_client._request(norm, params, timeout=30)
    ms = int((time.time() - t0) * 1000)
    if err:
        return {"status": "success", "ok": False, "msg": err, "rows": 0,
                "name": info.get("name"), "params_used": params, "ms": ms}
    rows = 0
    if isinstance(data, dict):
        has_list = False
        for k in ("item", "stock_items", "abilities"):
            v = data.get(k)
            if isinstance(v, list):
                rows = len(v)
                has_list = True
                break
        if not has_list and data:
            rows = 1
    elif isinstance(data, list):
        rows = len(data)
    if rows == 0:
        msg = f"调用成功但返回 0 行（{ms}ms）——盘后/非交易时段部分榜单本就为空，也可能无该能力权限"
    else:
        msg = f"调用成功，返回 {rows} 行（{ms}ms）"
    return {"status": "success", "ok": rows > 0, "msg": msg, "rows": rows,
            "name": info.get("name"), "params_used": params, "ms": ms}

@router.post("/api/admin/test-fuyao")
async def api_admin_test_fuyao(request: Request):
    require_admin(request)
    ok, msg = fuyao_client.probe()
    return {"status": "success", "ok": ok, "msg": msg,
            "configured": fuyao_client.configured(), "enabled": settings.fuyao_enabled()}

def _resolve_redeem_spec(plan_key: str, sku_index):
    import re as _re
    plans = settings.get_pricing_plans() or []
    plan = next((p for p in plans if str(p.get("key")) == str(plan_key)), None)
    if not plan:
        return None
    prices = plan.get("prices") or []
    if not prices:
        return None
    try:
        idx = max(0, min(int(sku_index or 0), len(prices) - 1))
    except Exception:
        idx = 0
    label = str((prices[idx] or {}).get("label") or "").strip() or "默认规格"
    spec = {"plan_key": str(plan_key), "plan_name": str(plan.get("name") or ""),
            "sku_label": label, "level": 0, "days": 0,
            "bonus_normal": 0, "bonus_deep": 0}
    ptype = plan.get("type")
    if ptype == "subscription":
        spec["level"] = 1 if str(plan_key) == "vip1" else 2
        if "年" in label:
            spec["days"] = 365
        elif ("半年" in label) or ("6" in label and "月" in label):
            spec["days"] = 180
        elif "季" in label:
            spec["days"] = 90
        elif "周" in label:
            spec["days"] = 7
        elif "月" in label:
            spec["days"] = 30
        else:
            spec["days"] = [30, 180, 365][idx] if idx < 3 else 30
    elif ptype == "payg":
        ben = (prices[idx] or {}).get("benefits") or {}
        if isinstance(ben, dict) and (ben.get("normal") or ben.get("deep")):
            spec["bonus_normal"] = int(ben.get("normal") or 0)
            spec["bonus_deep"] = int(ben.get("deep") or 0)
        else:
            m = _re.search(r"(\d+)", label)
            n = int(m.group(1)) if m else 0
            if "深度" in label or "deep" in label.lower():
                spec["bonus_deep"] = n
            else:
                spec["bonus_normal"] = n
    else:
        return None
    if spec["level"] == 0 and not spec["bonus_normal"] and not spec["bonus_deep"]:
        return None
    return spec

def _describe_redeem_spec(spec):
    if not spec:
        return "-"
    parts = []
    if int(spec.get("level") or 0) > 0 and int(spec.get("days") or 0) > 0:
        parts.append("VIP-%d 会员 %d 天" % (int(spec["level"]), int(spec["days"])))
    if int(spec.get("bonus_normal") or 0):
        parts.append("普通分析 %d 次" % int(spec["bonus_normal"]))
    if int(spec.get("bonus_deep") or 0):
        parts.append("深度分析 %d 次" % int(spec["bonus_deep"]))
    return " + ".join(parts) if parts else "-"

