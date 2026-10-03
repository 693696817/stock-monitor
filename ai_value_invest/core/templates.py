import os

from fastapi.templating import Jinja2Templates

import settings
import legal_pages as legal

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(_BASE_DIR, "templates")
STATIC_DIR = os.path.join(_BASE_DIR, "static")

templates = Jinja2Templates(directory=TEMPLATE_DIR)
templates.env.auto_reload = True

templates.env.globals["legal_indexable"] = legal.is_indexable

def _static_version():
    latest = 0
    base = STATIC_DIR
    for sub in ("css", "js"):
        d = os.path.join(base, sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            try:
                latest = max(latest, int(os.path.getmtime(os.path.join(d, name))))
            except OSError:
                continue
    return latest or 1

templates.env.globals["STATIC_V"] = _static_version()

def _sb(key):
    try:
        mods = settings.get_sidebar_modules()["modules"]
        return mods.get(key) or {
            "key": key, "name": key, "desc": "", "icon": "fa-puzzle-piece",
            "source": "", "placement": "", "enabled": True, "order": 999, "options": {},
        }
    except Exception as _e:
        print(f"⚠️ [Sidebar] 读取小模块配置失败({key}): {_e}")
        return {"key": key, "name": key, "desc": "", "icon": "fa-puzzle-piece",
                "source": "", "placement": "", "enabled": True, "order": 999, "options": {}}

templates.env.globals["sb"] = _sb
