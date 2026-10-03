import settings
from settings import get_analysis_preferences

def refresh_analysis_preferences(app):
    app.state.analysis_preferences = get_analysis_preferences()
    app.state.analysis_models = settings.get_all_ai_models()

def refresh_site_settings(app):
    keys = ["SITE_NAME", "SITE_DOMAIN", "SITE_LOGO_URL",
            "SEO_TITLE", "SEO_KEYWORDS", "SEO_DESCRIPTION", "SEO_OG_IMAGE",
            "ICP_NUMBER"]
    site = {}
    for k in keys:
        site[k] = (settings.get_setting(k, "") or "")
    try:
        site["ANNOUNCEMENT"] = settings.get_announcement()
    except Exception:
        site["ANNOUNCEMENT"] = None
    app.state.site = site

def refresh_pricing(app):
    app.state.pricing = settings.get_pricing_plans()
