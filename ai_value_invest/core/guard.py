import json

import settings

def _model_meta_wipe_check(new_raw):
    try:
        new_chans = json.loads(new_raw) if isinstance(new_raw, str) else (new_raw or [])
    except Exception:
        return None
    if not isinstance(new_chans, list):
        return None
    try:
        old_chans = settings.get_ai_model_channels()
    except Exception:
        return None

    def _key(m):
        return str(m.get("id") or "").strip() or str(m.get("alias") or "").strip()

    old_map = {}
    for c in old_chans or []:
        for m in (c.get("models") or []):
            k = _key(m)
            if k:
                old_map[k] = m

    wiped = {}
    for c in new_chans:
        for m in (c.get("models") or []):
            om = old_map.get(_key(m))
            if not om:
                continue
            for f, label in (("tagline", "一句话特色"), ("logo", "Logo")):
                if str(om.get(f) or "").strip() and not str(m.get(f) or "").strip():
                    wiped.setdefault(label, []).append(str(m.get("alias") or _key(m)))

    for label, names in wiped.items():
        total = sum(1 for m in old_map.values() if str(m.get(
            "tagline" if label == "一句话特色" else "logo") or "").strip())
        if len(names) >= 2 and len(names) == total:
            return ("已阻止本次保存：它会把全部 %d 个模型的「%s」清空（%s）。"
                    "通常是浏览器停留在旧页面导致的——请刷新后台页面（Ctrl+F5）后重新修改保存；"
                    "确实要清空的话，请逐条手动删除。" % (total, label, "、".join(names[:6])))
    return None
