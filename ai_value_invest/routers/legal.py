from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

import legal_pages as legal
from core.templates import templates

router = APIRouter(tags=["法务与信息页"])

def _render_legal_page(request: Request, slug: str):
    page = legal.get_page(slug)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    ctx["updated"] = legal.UPDATED_AT
    return templates.TemplateResponse(
        request,
        "legal.html",
        {
            "request": request,
            "active_page": slug,
            "page": ctx,
            "all_pages": legal.PAGES,
            "order": legal.ORDER,
            "todo_fields": sorted(set(legal.pending_placeholders().values())),
        }
    )

@router.get("/privacy", response_class=HTMLResponse)
async def page_privacy(request: Request):
    return _render_legal_page(request, "privacy")

@router.get("/terms", response_class=HTMLResponse)
async def page_terms(request: Request):
    return _render_legal_page(request, "terms")

@router.get("/disclaimer", response_class=HTMLResponse)
async def page_disclaimer(request: Request):
    return _render_legal_page(request, "disclaimer")

@router.get("/cookies", response_class=HTMLResponse)
async def page_cookies(request: Request):
    return _render_legal_page(request, "cookies")

@router.get("/refund", response_class=HTMLResponse)
async def page_refund(request: Request):
    return _render_legal_page(request, "refund")

@router.get("/about", response_class=HTMLResponse)
async def page_about(request: Request):
    return _render_legal_page(request, "about")

@router.get("/contact", response_class=HTMLResponse)
async def page_contact(request: Request):
    return _render_legal_page(request, "contact")

@router.get("/help", response_class=HTMLResponse)
async def page_help(request: Request):
    return _render_legal_page(request, "help")
