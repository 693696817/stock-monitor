
import json
import time
import threading
import datetime

from config import (
    DATA_SOURCE, PROXY_PROVIDER, PROMOAX_BASE_URL, PROMOAX_API_KEY,
    DATAHUB_BASE_URL, DATAHUB_API_KEY, TUSHARE_TOKEN,
    VOLC_API_KEY, VOLC_BASE_URL, VOLC_MODEL_ID,
    FUYAO_API_KEY,
)
from db import get_setting as _db_get, set_setting as _db_set
from datahub_catalog import build_catalog as _build_datahub_catalog
from lixinger_catalog import build_catalog as _build_lixinger_catalog
from fuyao_catalog import build_catalog as _build_fuyao_catalog

SETTINGS = {}
_LOCK = threading.Lock()


def _default_data_channels():
    return [
        {"id": "promoax", "name": "PROMOAX 聚合", "base_url": PROMOAX_BASE_URL, "api_key": PROMOAX_API_KEY, "enabled": True},
        {"id": "datahub", "name": "DATAHUB 聚合", "base_url": DATAHUB_BASE_URL, "api_key": DATAHUB_API_KEY, "enabled": False},
    ]

def _default_ai_channels():
    return [
        {
            "id": "volcano", "name": "火山引擎", "base_url": VOLC_BASE_URL,
            "api_key": VOLC_API_KEY, "enabled": True,
            "models": [
                {"id": "volcano__doubao", "alias": "豆包大模型", "model_id": VOLC_MODEL_ID,
                 "enabled": True, "vip_only": False},
            ],
        },
    ]

def _default_analysis_preferences():
    return [
        {
            "id": "short_term",
            "name": "短线激进投资",
            "tagline": "关注短期波动、热点与技术信号",
            "is_deep": False,
            "vip_only": False,
            "system_prompt": """你是一位短线交易分析师，专注于捕捉 1-5 个交易日的价格波动机会。\n你的任务是为【{stock_name} ({stock_code})】撰写一份《短线激进投资分析报告》。\n\n【分析纪律】：\n- 严格基于用户提供的全维数据面板进行分析，面板包含行情、估值、盈利、成长、现金流、技术面等约 30 项指标。\n- 对 N/A 项明确标注“数据缺失”，严禁臆造数值或历史分位。\n- 重点关注：近期热点催化、量价关系、技术形态、资金流向、短期支撑/压力位。\n\n【格式要求】：\n1. 必须输出 Markdown 格式。\n2. 至少包含 5 个章节。\n3. 使用 HTML 标签增强视觉效果（如 <span class=\"text-danger\">, <b>）。\n4. 关键结论用引用块 > 包裹，使用 Emoji 图标（📊, ⚡, ⚠️, 🎯）。\n5. 核心数据对比必须使用 Markdown 表格展示。\n\n【报告大纲】：\n# {stock_name} ({stock_code}) 短线激进投资分析报告\n> 报告日期：{current_date} | 分析师：A股棱镜\n\n## ⚡ 一、短线情绪与热点催化\n（梳理近期行业/个股事件、热点概念、资金关注度；给出情绪评分）\n\n## 📊 二、技术形态与关键价位\n（基于 MA5/MA20、换手率、成交量、K线形态；给出支撑位、压力位、突破/跌破信号）\n\n## 🎯 三、量价关系与资金博弈\n（分析近 5 日量能变化、主力资金动向、换手是否健康）\n\n## ⚠️ 四、风险提示\n（列出 3-4 点短线核心风险，如利好兑现、板块退潮、大盘变脸）\n\n## 📝 五、短线操作建议\n（给出明确的买入区间、目标价、止损位、持仓周期 1-5 日、仓位建议）\n""",
        },
        {
            "id": "swing",
            "name": "波段机会投资",
            "tagline": "寻找中短期高抛低吸的波段机会",
            "is_deep": False,
            "vip_only": False,
            "system_prompt": """你是一位波段交易分析师，专注于 2-8 周的中短期高抛低吸机会。\n你的任务是为【{stock_name} ({stock_code})】撰写一份《波段机会投资分析报告》。\n\n【分析纪律】：\n- 严格基于用户提供的全维数据面板进行分析。\n- 对 N/A 项明确标注“数据缺失”，严禁臆造。\n- 重点关注：趋势结构、估值安全边际、业绩催化窗口、板块轮动节奏。\n\n【格式要求】：\n1. 必须输出 Markdown 格式。\n2. 至少包含 5 个章节。\n3. 使用 HTML 标签、引用块、Emoji（📈, 🛡️, ⚠️, 🎯）。\n4. 核心数据使用 Markdown 表格。\n\n【报告大纲】：\n# {stock_name} ({stock_code}) 波段机会投资分析报告\n> 报告日期：{current_date} | 分析师：A股棱镜\n\n## 📈 一、趋势结构与波段定位\n（判断当前处于上升/下降/盘整哪个阶段，给出波段位置评分）\n\n## 💰 二、估值与基本面安全垫\n（基于 PE/PB/PS、股息率、ROE，评估当前价位是否有基本面支撑）\n\n## 🗓️ 三、业绩与事件催化窗口\n（结合财报披露、行业政策、解禁/回购等事件，判断波段催化）\n\n## ⚠️ 四、风险与止损设计\n（列出波段核心风险，给出止损位与仓位管理建议）\n\n## 📝 五、波段操作策略\n（低吸区间、高抛区间、目标收益、持仓周期 2-8 周）\n""",
        },
        {
            "id": "long_term_value",
            "name": "长线价值投资",
            "tagline": "更看重基本面与长期价值",
            "is_deep": False,
            "vip_only": False,
            "system_prompt": """你是一位拥有20年经验的买方价值投资分析师，深谙本杰明·格雷厄姆的安全边际理论、巴菲特的护城河与自由现金流折现思想，以及林园“高确定性长期持有”与李大霄“价值底线”的实战流派。\n你的任务是为【{stock_name} ({stock_code})】撰写一份严谨、可落地的《长线价值投资分析报告》。\n\n【数据纪律（最重要）】：\n- 严格基于用户提供的“全维数据面板”进行分析。面板包含约30项指标：行情与估值（价格、市值、换手、量比、PE/PB/PS、股息率、估值历史分位）、盈利质量（ROE/ROIC/毛利率/净利率/负债率）、成长（营收/利润增速）、现金流（经营现金流、自由现金流）、技术面（MA5/MA20）等。\n- 面板中若某项显示“N/A”，表示数据源未提供。**严禁臆造 N/A 项的数值或历史分位**；应明确标注“数据缺失”并提示为信息风险。\n- 估值历史分位、股息率等关键结论必须基于面板已有数据。\n- 重点关注：现金流、ROE质量、估值安全边际。\n\n【格式要求】：\n1. 必须输出 Markdown 格式。\n2. 篇幅详尽，至少包含6个章节。\n3. 使用 HTML 标签增强视觉效果（如 <span class=\"text-danger\">, <b>）。\n4. 关键结论用引用块 > 包裹。\n5. 使用 Emoji 图标增加可读性 (📊, 🛡️, ⚠️, ✅)。\n6. 核心数据对比必须使用 Markdown 表格展示。\n\n【报告大纲结构】：\n# {stock_name} ({stock_code}) 长线价值投资分析报告\n> 报告日期：{current_date} | 分析师：A股棱镜\n\n## 📊 一、核心摘要 (Executive Summary)\n（创建一个表格，列出：当前股价、PE-TTM、股息率、ROE、内在价值估算区间、投资评级[买入/增持/持有/卖出]）\n（用一句话犀利点评）\n\n## 🏰 二、商业模式与护城河 (Business & Moat)\n### 1. 核心竞争力打分\n（从品牌、成本、网络效应、转换成本维度分析，并给出 ⭐ 评级）\n### 2. 行业地位\n（分析其在产业链中的话语权，上下游议价能力）\n\n## 📈 三、财务健康度体检 (Financial Health)\n### 1. 杜邦分析拆解\n（基于 ROE = 净利率 × 周转率 × 权益乘数，分析驱动力）\n### 2. 成长质量\n（对比 营收增速 vs 利润增速 vs 现金流增速。**警惕：有利润无现金的“纸面富贵”**）\n### 3. 资产负债表排雷\n（分析 存货周转、应收账款、商誉占比。是否有“存贷双高”嫌疑？）\n\n## 💰 四、估值与安全边际 (Valuation)\n### 1. 相对估值\n（PE/PB 处于历史什么分位？对比同行业水平如何？）\n### 2. 绝对估值 (DCF简易推演)\n（基于当前自由现金流(FCF)和假设增长率，倒推合理估值区间。**必须给出具体数字并注明假设**）\n### 3. 分红回报\n（股息率(TTM)与历史分红稳定性；分析分红连续性对长期持有的意义）\n\n## 🎯 五、技术面与资金博弈 (Technical & Flow)\n（基于 MA5/MA20 均线、换手率、成交量数据，分析短期趋势是多头还是空头？）\n\n## ⚠️ 六、风险提示 (Risk Factors)\n（列出3-4点核心风险）\n\n## 📝 七、最终结论与操作框架\n（给出：具体的建议买入价格区间、仓位建议、止损位、目标价与持有周期）\n""",
        },
        {
            "id": "comprehensive",
            "name": "综合分析投资",
            "tagline": "技术 + 基本面 + 事件的均衡视角",
            "is_deep": False,
            "vip_only": False,
            "system_prompt": """你是一位均衡型投资分析师，同时关注技术面、基本面和事件催化，致力于为【{stock_name} ({stock_code})】提供一份多维度的《综合分析投资报告》。\n\n【分析纪律】：\n- 严格基于用户提供的全维数据面板。\n- N/A 项明确标注“数据缺失”，不臆造。\n- 避免单一维度下结论，必须在技术面、基本面、事件面之间做交叉验证。\n\n【格式要求】：\n1. 必须输出 Markdown 格式。\n2. 至少包含 5 个章节。\n3. 使用 HTML 标签、引用块、Emoji（📊, 🔍, ⚠️, 🎯）。\n4. 核心数据使用 Markdown 表格。\n\n【报告大纲】：\n# {stock_name} ({stock_code}) 综合分析投资报告\n> 报告日期：{current_date} | 分析师：A股棱镜\n\n## 🔍 一、多维度核心摘要\n（用表格汇总：估值、盈利、成长、技术、事件五个维度的评分与关键数据）\n\n## 📈 二、技术面研判\n（趋势、支撑压力、量能、资金流向）\n\n## 🏢 三、基本面扫描\n（盈利质量、成长持续性、现金流健康度、资产负债风险）\n\n## 📰 四、事件与情绪催化\n（近期公告、行业政策、宏观环境、市场情绪）\n\n## ⚠️ 五、风险与综合建议\n（列出多维风险，给出投资评级、适合周期、买入/观望/卖出建议）\n""",
        },
        {
            "id": "deep_tech",
            "name": "深度技术",
            "tagline": "多指标共振与节奏判断，更偏短期",
            "is_deep": True,
            "vip_only": True,
            "system_prompt": """你是一位量化技术分析师，擅长多指标共振与交易节奏判断，专注于为【{stock_name} ({stock_code})】生成一份深度技术分析报告。\n\n【分析纪律】：\n- 严格基于用户提供的全维数据面板。\n- N/A 项明确标注“数据缺失”，不臆造。\n- 深度技术不等于追高，必须给出明确的买点、卖点、止损与仓位。\n\n【格式要求】：\n1. 必须输出 Markdown 格式。\n2. 至少包含 6 个章节。\n3. 使用 HTML 标签、引用块、Emoji（📊, ⚡, ⚠️, 🎯）。\n4. 核心数据使用 Markdown 表格。\n\n【报告大纲】：\n# {stock_name} ({stock_code}) 深度技术分析报告\n> 报告日期：{current_date} | 分析师：A股棱镜 | 深度技术版\n\n## ⚡ 一、趋势结构判定\n（周线/日线/60分钟级别趋势；判断主升、震荡、下跌）\n\n## 📊 二、多指标共振分析\n（MA5/MA20/MA60、MACD、量能、换手率、RSI、布林通道等；给出共振方向）\n\n## 🎯 三、关键价位与买卖点\n（精确给出支撑位、压力位、突破买点、回踩买点、止损位）\n\n## 💸 四、资金博弈与主力行为\n（龙虎榜、北向、融资余额、大宗交易等资金流向线索）\n\n## ⚠️ 五、风险与失效条件\n（列出技术形态失效的触发条件）\n\n## 📝 六、交易计划\n（买入区间、目标价、止损价、持仓周期、仓位建议、加减仓条件）\n""",
        },
        {
            "id": "deep_value",
            "name": "深度价值",
            "tagline": "估值锚 + 质地筛选，更偏中长期",
            "is_deep": True,
            "vip_only": True,
            "system_prompt": """你是一位深度价值投资者，信奉“以合理价格买入优秀公司”，擅长估值锚定与质地筛选，专注于为【{stock_name} ({stock_code})】生成一份深度价值投资报告。\n\n【分析纪律】：\n- 严格基于用户提供的全维数据面板。\n- N/A 项明确标注“数据缺失”，不臆造。\n- 所有估值结论必须给出假设、参数与区间。\n\n【格式要求】：\n1. 必须输出 Markdown 格式。\n2. 至少包含 6 个章节。\n3. 使用 HTML 标签、引用块、Emoji（📊, 🛡️, ⚠️, ✅）。\n4. 核心数据使用 Markdown 表格。\n\n【报告大纲】：\n# {stock_name} ({stock_code}) 深度价值投资报告\n> 报告日期：{current_date} | 分析师：A股棱镜 | 深度价值版\n\n## 🛡️ 一、生意质地评估\n（商业模式、护城河、行业格局、管理层与资本配置）\n\n## 📈 二、财务质量深度体检\n（ROE/ROIC 十年视角、毛利率稳定性、现金流成色、资本开支、负债结构）\n\n## 💰 三、估值锚定\n### 1. 历史分位与同业对比\n### 2. DCF 估值（给出乐观/中性/悲观三种情景）\n### 3. 股息与回购回报测算\n\n## 🔍 四、成长驱动力\n（量价拆分、行业空间、市占率、第二曲线）\n\n## ⚠️ 五、核心风险与黑天鹅\n（政策、技术替代、竞争恶化、财务造假信号、ESG 风险）\n\n## 📝 六、价值投资决策框架\n（内在价值区间、安全边际买入价、目标价、持有周期、仓位建议、再平衡条件）\n""",
        },
    ]

def _default_pricing_plans():
    return [
        {
            "key": "free", "name": "免费版", "tagline": "注册即享，体验AI投研魅力",
            "type": "free", "popular": False, "price_from": "¥0", "period": "/永久",
            "prices": [],
            "button": {"text": "当前版本", "action": ""},
            "features": [
                {"text": "普通分析：2次/天", "on": True},
                {"text": "注册赠送：5次普通分析", "on": True},
                {"text": "注册赠送：1次深度分析", "on": True},
                {"text": "深度研报体验：每月 1 次", "on": True},
                {"text": "个股多角度普通分析", "on": True},
                {"text": "大盘多角度普通分析", "on": True},
                {"text": "基础数据查询", "on": True},
                {"text": "投资机会查询", "on": True},
                {"text": "深度价值研报", "on": False},
                {"text": "PDF 研报导出", "on": False},
            ],
        },
        {
            "key": "vip1", "name": "VIP-1 会员", "tagline": "适合日常投资分析，性价比之选",
            "type": "subscription", "popular": True, "price_from": "¥19.9", "period": "/月",
            "prices": [
                {"label": "月卡", "price": "¥19.9", "unit": "/月", "note": ""},
                {"label": "年卡", "price": "¥99", "unit": "/年", "note": "立省 ¥140 · 新站特惠"},
            ],
            "button": {"text": "立即开通", "action": "vip1"},
            "features": [
                {"text": "普通分析：5次/天", "on": True},
                {"text": "深度分析：2次/天", "on": True},
                {"text": "解锁「深度技术 / 深度价值」分析视角", "on": True},
                {"text": "VIP 专属后端模型", "on": True},
                {"text": "无限次 PDF 研报导出", "on": True},
                {"text": "会员到期站内提醒", "on": True},
            ],
        },
        {
            "key": "vip2", "name": "VIP-2 尊享版", "tagline": "额度翻倍，适合高频 / 专业投资者",
            "type": "subscription", "popular": False, "price_from": "¥39.9", "period": "/月",
            "prices": [
                {"label": "月卡", "price": "¥39.9", "unit": "/月", "note": ""},
                {"label": "年卡", "price": "¥199", "unit": "/年", "note": "立省 ¥280 · 额度翻倍"},
            ],
            "button": {"text": "立即开通", "action": "vip2"},
            "features": [
                {"text": "普通分析：10次/天", "on": True},
                {"text": "深度分析：5次/天", "on": True},
                {"text": "解锁「深度技术 / 深度价值」分析视角", "on": True},
                {"text": "VIP 专属后端模型", "on": True},
                {"text": "无限次 PDF 研报导出", "on": True},
                {"text": "会员到期站内提醒", "on": True},
                {"text": "新功能灰度优先体验", "on": True},
            ],
        },
        {
            "key": "payg", "name": "按量付费包", "tagline": "按需购买，用完即止，无时间限制",
            "type": "payg", "popular": False, "price_from": "¥9.9", "period": "起",
            "prices": [
                {"label": "新人体验包（10次普通 + 2次深度）", "price": "¥9.9", "unit": "", "note": "新人推荐",
                 "benefits": {"normal": 10, "deep": 2}},
            ],
            "button": {"text": "前往店铺购买", "action": "contact"},
            "features": [
                {"text": "新人体验包 ¥9.9（10次普通 + 2次深度）", "on": True},
                {"text": "无时间限制，用完即止", "on": True},
                {"text": "与会员每日额度并存，不互相抵扣", "on": True},
                {"text": "适合低频 / 临时需求用户", "on": True},
            ],
        },
    ]

SETTING_KEYS = {
    "DATA_SOURCE_ACTIVE": "promoax",
    "DATA_SOURCE_CHANNELS": json.dumps(_default_data_channels(), ensure_ascii=False),
    "TUSHARE_TOKEN": TUSHARE_TOKEN,
    "FUYAO_API_KEY": FUYAO_API_KEY,
    "FUYAO_ENABLED": "1",
    "FUYAO_API_CATALOG": json.dumps(_build_fuyao_catalog(), ensure_ascii=False),
    "AI_MODEL_ACTIVE": "volcano",
    "AI_MODEL_CHANNELS": json.dumps(_default_ai_channels(), ensure_ascii=False),
    "AI_MODEL_HEALTH": "{}",
    "SITE_NAME": "A股棱镜",
    "SITE_DOMAIN": "",
    "SITE_LOGO_URL": "",
    "SEO_TITLE": "",
    "SEO_KEYWORDS": "",
    "SEO_DESCRIPTION": "",
    "SEO_OG_IMAGE": "",
    "PRICING_PLANS": json.dumps(_default_pricing_plans(), ensure_ascii=False),
    "ANALYSIS_PREFERENCES": json.dumps(_default_analysis_preferences(), ensure_ascii=False),
    "REGISTER_BONUS_NORMAL": "5",
    "REGISTER_BONUS_DEEP": "1",
    "DATAHUB_API_CATALOG": json.dumps(_build_datahub_catalog(), ensure_ascii=False),
    "LIXINGER_API_CATALOG": json.dumps(_build_lixinger_catalog(), ensure_ascii=False),
    "SIDEBAR_MODULES": "{}",
    "QUOTA_RULES": json.dumps({
        "free_daily_normal": 2,
        "free_daily_deep": 0,
        "free_monthly_deep": 1,
        "vip1_daily_normal": 5,
        "vip1_daily_deep": 2,
        "vip1_monthly_deep": 0,
        "vip2_daily_normal": 10,
        "vip2_daily_deep": 5,
        "vip2_monthly_deep": 0,
        "admin_uid_whitelist": "",
    }, ensure_ascii=False),
    "REGISTER_POLICY": json.dumps({
        "sms_required": True,
        "invite_required": False,
        "password_min_len": 6,
    }, ensure_ascii=False),
    "RATE_LIMITS": json.dumps({
        "register_ip_per_hour": 10,
        "login_ip_per_min": 10,
        "login_acct_per_min": 5,
        "sms_ip_per_hour": 20,
        "smsverify_ip_per_min": 20,
        "smsverify_acct_per_600s": 20,
        "sms_code_max_fail": 5,
        "pwdreset_ip_per_hour": 10,
        "pwdreset_confirm_per_min": 5,
        "analyze_ip_per_day": 0,
        "ip_blacklist": "",
    }, ensure_ascii=False),
    "OPERATOR_INFO": json.dumps({
        "entity": "",
        "email": "",
        "wechat": "",
        "address": "",
        "dpo": "",
        "sla": "",
    }, ensure_ascii=False),
    "ICP_NUMBER": "",
    "SITE_ANNOUNCEMENT": json.dumps({
        "enabled": False,
        "text": "",
        "level": "info",
        "start_at": "",
        "end_at": "",
    }, ensure_ascii=False),
}

def init_settings():
    with _LOCK:
        SETTINGS.clear()
        for k, v in SETTING_KEYS.items():
            SETTINGS[k] = v
    try:
        for k in SETTING_KEYS:
            val = _db_get(k)
            if val is not None:
                with _LOCK:
                    SETTINGS[k] = val
        if _db_get("DATA_SOURCE_CHANNELS") is None:
            _migrate_data_channels()
        if _db_get("AI_MODEL_CHANNELS") is None:
            _migrate_ai_channels()
        if _db_get("TUSHARE_TOKEN") is None:
            _db_set("TUSHARE_TOKEN", TUSHARE_TOKEN)
        for k, v in SETTING_KEYS.items():
            if _db_get(k) is None:
                _db_set(k, v)
    except Exception as e:
        print(f"[settings] init warning: {e}")

def _migrate_data_channels():
    dc = _default_data_channels()
    for c in dc:
        if c["id"] == "promoax":
            c["base_url"] = _db_get("PROMOAX_BASE_URL") or c["base_url"]
            c["api_key"] = _db_get("PROMOAX_API_KEY") or c["api_key"]
        elif c["id"] == "datahub":
            c["base_url"] = _db_get("DATAHUB_BASE_URL") or c["base_url"]
            c["api_key"] = _db_get("DATAHUB_API_KEY") or c["api_key"]
    active = "promoax"
    ds = _db_get("DATA_SOURCE")
    pp = _db_get("PROXY_PROVIDER")
    if ds == "tushare":
        active = "tushare"
    elif pp in ("promoax", "datahub"):
        active = pp
    _db_set("DATA_SOURCE_CHANNELS", json.dumps(dc, ensure_ascii=False))
    _db_set("DATA_SOURCE_ACTIVE", active)
    with _LOCK:
        SETTINGS["DATA_SOURCE_CHANNELS"] = json.dumps(dc, ensure_ascii=False)
        SETTINGS["DATA_SOURCE_ACTIVE"] = active

def _migrate_ai_channels():
    model_id = _db_get("VOLC_MODEL_ID") or VOLC_MODEL_ID
    ac = [{
        "id": "volcano", "name": "火山引擎",
        "base_url": _db_get("VOLC_BASE_URL") or VOLC_BASE_URL,
        "api_key": _db_get("VOLC_API_KEY") or VOLC_API_KEY,
        "enabled": True,
        "models": [{"id": "volcano__doubao", "alias": "豆包大模型", "model_id": model_id,
                    "enabled": True, "vip_only": False}],
    }]
    _db_set("AI_MODEL_CHANNELS", json.dumps(ac, ensure_ascii=False))
    _db_set("AI_MODEL_ACTIVE", "volcano__doubao")
    with _LOCK:
        SETTINGS["AI_MODEL_CHANNELS"] = json.dumps(ac, ensure_ascii=False)
        SETTINGS["AI_MODEL_ACTIVE"] = "volcano__doubao"

def _parse_json(val, default):
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


def get_data_source_channels():
    return _parse_json(get_setting("DATA_SOURCE_CHANNELS"), [])

def get_active_data_source():
    return get_setting("DATA_SOURCE_ACTIVE", "tushare")


def _norm_model_entry(m, chan, idx):
    if not isinstance(m, dict):
        m = {"model_id": str(m or "")}
    chan_id = (chan.get("id") or "ch").strip() or "ch"
    mid = (m.get("id") or "").strip() or f"{chan_id}__m{idx}"
    model_id = (m.get("model_id") or m.get("model") or "").strip()
    alias = (m.get("alias") or "").strip() or model_id or mid
    vip_raw = m.get("vip_only")
    if vip_raw is None:
        vip_raw = (chan_id != "volcano")
    profile = _norm_model_profile(m.get("profile"))
    return {
        "id": mid,
        "alias": alias,
        "model_id": model_id,
        "enabled": bool(m.get("enabled", True)),
        "vip_only": bool(vip_raw),
        "featured": bool(m.get("featured")),
        "tagline": str(m.get("tagline") or "").strip(),
        "logo": str(m.get("logo") or "").strip(),
        "profile": profile,
    }

def _norm_model_profile(raw):
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except Exception:
            return {}
    if not isinstance(raw, dict):
        return {}
    p = {}
    kind = str(raw.get("kind") or "").strip().lower()
    if kind in ("reasoning", "direct"):
        p["kind"] = kind
    try:
        temp = float(raw.get("temperature"))
    except (TypeError, ValueError):
        temp = 0.0
    if 0 < temp <= 2:
        p["temperature"] = round(temp, 2)
    try:
        mo = int(raw.get("max_out") or 0)
    except (TypeError, ValueError):
        mo = 0
    if mo > 0:
        p["max_out"] = mo
    tok = raw.get("tokens")
    if isinstance(tok, dict):
        clean_tok = {}
        for k in ("normal", "deep"):
            try:
                v = int(tok.get(k) or 0)
            except (TypeError, ValueError):
                v = 0
            if v > 0:
                clean_tok[k] = v
        if clean_tok:
            p["tokens"] = clean_tok
    instr = str(raw.get("instruction") or "").strip()
    if instr:
        p["instruction"] = instr[:200]
    spec = str(raw.get("spec") or "").strip()
    if spec:
        p["spec"] = spec[:120]
    return p

def _channel_models(chan):
    models = chan.get("models")
    if not isinstance(models, list) or not models:
        chan_id = (chan.get("id") or "ch").strip() or "ch"
        vip_raw = chan.get("vip_only")
        if vip_raw is None:
            vip_raw = (chan_id != "volcano")
        models = [{
            "id": f"{chan_id}__default",
            "alias": (chan.get("name") or "").strip() or (chan.get("model") or "") or "默认模型",
            "model_id": (chan.get("model") or "").strip(),
            "enabled": True,
            "vip_only": bool(vip_raw),
        }]
    return [_norm_model_entry(m, chan, i) for i, m in enumerate(models)]

def get_ai_model_channels():
    channels = _parse_json(get_setting("AI_MODEL_CHANNELS"), [])
    for c in channels:
        c["models"] = _channel_models(c)
        c["vip_only"] = all(m["vip_only"] for m in c["models"]) if c["models"] else False
    return channels

def get_all_ai_models(include_disabled=False):
    out = []
    for chan in get_ai_model_channels():
        if not chan.get("enabled") and not include_disabled:
            continue
        for m in chan["models"]:
            if not m["enabled"] and not include_disabled:
                continue
            out.append({
                "id": m["id"],
                "alias": m["alias"],
                "model_id": m["model_id"],
                "vip_only": m["vip_only"],
                "enabled": m["enabled"],
                "channel_id": chan.get("id"),
                "channel_name": chan.get("name"),
                "featured": m.get("featured", False),
                "tagline": m.get("tagline", ""),
                "logo": m.get("logo", ""),
            })
    return out

def get_default_ai_model_id():
    active = (get_setting("AI_MODEL_ACTIVE", "") or "").strip()
    models = get_all_ai_models()
    if active:
        if any(m["id"] == active for m in models):
            return active
        for m in models:
            if m["channel_id"] == active:
                return m["id"]
    free = next((m["id"] for m in models if not m["vip_only"]), None)
    return free or (models[0]["id"] if models else "")

def resolve_ai_model(model_key: str = None):
    channels = get_ai_model_channels()
    key = (model_key or "").strip() or get_default_ai_model_id()

    def _pick(chan, mid=None):
        for m in chan["models"]:
            if not m["enabled"]:
                continue
            if mid is None or m["id"] == mid:
                return chan, m
        return None

    for chan in channels:
        if not chan.get("enabled"):
            continue
        hit = _pick(chan, key)
        if hit:
            return hit
    for chan in channels:
        if chan.get("id") == key and chan.get("enabled"):
            hit = _pick(chan)
            if hit:
                return hit
    default_id = get_default_ai_model_id()
    if default_id and default_id != key:
        for chan in channels:
            if not chan.get("enabled"):
                continue
            hit = _pick(chan, default_id)
            if hit:
                return hit
    return None, None

def locate_ai_model(model_key: str):
    key = (model_key or "").strip()
    if not key:
        return None, None, "empty"
    channels = get_ai_model_channels()
    for chan in channels:
        for m in chan["models"]:
            if m["id"] != key:
                continue
            if not chan.get("enabled"):
                return chan, m, "channel_disabled"
            if not m["enabled"]:
                return chan, m, "model_disabled"
            return chan, m, None
    for chan in channels:
        if chan.get("id") == key:
            if not chan.get("enabled"):
                return chan, None, "channel_disabled"
            for m in chan["models"]:
                if m["enabled"]:
                    return chan, m, None
            return chan, None, "model_disabled"
    return None, None, "not_found"

MODEL_UNAVAILABLE_REASON = {
    "empty": "未指定模型",
    "not_found": "后台尚未保存该模型（新增或改名后请先点「保存设置」再检测）",
    "channel_disabled": "所属渠道已停用，请勾上渠道的「启用」并保存",
    "model_disabled": "该模型已停用，请勾上行内的「启用」并保存",
}

def describe_model_unavailable(reason: str) -> str:
    return MODEL_UNAVAILABLE_REASON.get(reason, f"模型不可用（{reason}）")

def get_active_ai_model():
    return get_default_ai_model_id()


def get_model_health():
    return _parse_json(get_setting("AI_MODEL_HEALTH", "{}"), {}) or {}

def set_model_health(report: dict):
    if not isinstance(report, dict):
        return
    set_setting("AI_MODEL_HEALTH", json.dumps(report, ensure_ascii=False))

def update_model_health(model_id: str, result: dict):
    if not model_id:
        return
    health = get_model_health()
    item = dict(result or {})
    item["checked_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    health[str(model_id)] = item
    set_model_health(health)
    return item

def prune_model_health():
    alive = {m["id"] for m in get_all_ai_models(include_disabled=True)}
    health = get_model_health()
    kept = {k: v for k, v in health.items() if k in alive}
    if len(kept) != len(health):
        set_model_health(kept)
    return len(health) - len(kept)

def get_setting(key, default=None):
    with _LOCK:
        val = SETTINGS.get(key)
        if val is not None:
            return val
    try:
        db_val = _db_get(key)
        if db_val is not None:
            with _LOCK:
                SETTINGS[key] = db_val
            return db_val
    except Exception:
        pass
    return default

def _to_int(val, default):
    try:
        n = int(str(val).strip())
        return n if n >= 0 else default
    except Exception:
        return default

def get_register_bonus():
    return (_to_int(get_setting("REGISTER_BONUS_NORMAL"), 5),
            _to_int(get_setting("REGISTER_BONUS_DEEP"), 1))

def _get_json_setting(key, default):
    return _parse_json(get_setting(key, None), default) or default

_QUOTA_RULES_DEFAULTS = {
    "free_daily_normal": 2, "free_daily_deep": 0, "free_monthly_deep": 1,
    "vip1_daily_normal": 5, "vip1_daily_deep": 2, "vip1_monthly_deep": 0,
    "vip2_daily_normal": 10, "vip2_daily_deep": 5, "vip2_monthly_deep": 0,
    "admin_uid_whitelist": "",
}

def get_quota_rules():
    raw = _get_json_setting("QUOTA_RULES", dict(_QUOTA_RULES_DEFAULTS))
    out = dict(_QUOTA_RULES_DEFAULTS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v is not None:
                out[k] = v
    return out

def get_register_policy():
    return _get_json_setting("REGISTER_POLICY", {
        "sms_required": True, "invite_required": False, "password_min_len": 6,
    })

def get_rate_limits():
    return _get_json_setting("RATE_LIMITS", {
        "register_ip_per_hour": 10, "login_ip_per_min": 10, "login_acct_per_min": 5,
        "sms_ip_per_hour": 20, "smsverify_ip_per_min": 20, "smsverify_acct_per_600s": 20,
        "sms_code_max_fail": 5, "pwdreset_ip_per_hour": 10, "pwdreset_confirm_per_min": 5,
        "analyze_ip_per_day": 0, "ip_blacklist": "",
        "stock_api_ip_per_min": 20,
    })

def get_operator_info():
    return _get_json_setting("OPERATOR_INFO", {
        "entity": "", "email": "", "wechat": "", "address": "", "dpo": "", "sla": "",
    })

def get_announcement():
    ann = _get_json_setting("SITE_ANNOUNCEMENT", {
        "enabled": False, "text": "", "level": "info", "start_at": "", "end_at": "",
    })
    active = bool(ann.get("enabled"))
    if active:
        now = datetime.datetime.now()
        for bound, cmp in (("start_at", "ge"), ("end_at", "lt")):
            raw = str(ann.get(bound) or "").strip()
            if not raw:
                continue
            try:
                t = datetime.datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if cmp == "ge" and now < t:
                active = False
            if cmp == "lt" and now >= t:
                active = False
    out = dict(ann)
    out["active"] = active
    return out

def get_admin_uid_whitelist():
    raw = str(get_quota_rules().get("admin_uid_whitelist") or "")
    out = set()
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return out

def get_pricing_plans():
    return _parse_json(get_setting("PRICING_PLANS"), [])

_SIDEBAR_CACHE = {"data": None, "ts": 0}
_SIDEBAR_TTL = 10

def get_sidebar_modules():
    import sidebar_modules as smod
    now = time.time()
    if _SIDEBAR_CACHE["data"] and (now - _SIDEBAR_CACHE["ts"] < _SIDEBAR_TTL):
        return _SIDEBAR_CACHE["data"]

    stored = _parse_json(get_setting("SIDEBAR_MODULES"), {})
    cfg = smod.normalize(stored)

    meta = {m["key"]: m for m in smod.MODULES}
    modules = {}
    for key, cur in cfg.items():
        m = meta.get(key, {})
        modules[key] = {
            "key": key,
            "name": m.get("name", key),
            "desc": m.get("desc", ""),
            "icon": m.get("icon", "fa-puzzle-piece"),
            "source": m.get("source", ""),
            "placement": m.get("placement", ""),
            "enabled": cur["enabled"],
            "order": cur["order"],
            "options": cur["options"],
        }

    placements = {}
    for key, m in modules.items():
        placements.setdefault(m["placement"], []).append(key)
    for p in placements:
        placements[p].sort(key=lambda k: (modules[k]["order"], k))

    result = {"modules": modules, "placements": placements}
    _SIDEBAR_CACHE.update({"data": result, "ts": now})
    return result

def set_sidebar_modules(raw):
    import sidebar_modules as smod
    data = raw if isinstance(raw, dict) else _parse_json(raw, {})
    clean = smod.normalize(data)
    set_setting("SIDEBAR_MODULES", json.dumps(clean, ensure_ascii=False))
    _SIDEBAR_CACHE["data"] = None
    return clean

def get_analysis_preferences():
    prefs = _parse_json(get_setting("ANALYSIS_PREFERENCES"), [])
    defaults = {}
    try:
        import data_service
        defaults = getattr(data_service, "PREFERENCE_DATA_GROUPS", {}) or {}
    except Exception:
        defaults = {}
    for p in prefs:
        if not p.get("data_groups"):
            p["data_groups"] = list(defaults.get(p.get("id")) or [])
    return prefs

def get_datahub_catalog():
    cat = _parse_json(get_setting("DATAHUB_API_CATALOG"), [])
    if not cat:
        return _build_datahub_catalog()
    return cat

def get_lixinger_catalog():
    cat = _parse_json(get_setting("LIXINGER_API_CATALOG"), [])
    if not cat:
        return _build_lixinger_catalog()
    return cat

def get_fuyao_catalog():
    cat = _parse_json(get_setting("FUYAO_API_CATALOG"), [])
    if not cat:
        return _build_fuyao_catalog()
    return cat

def fuyao_enabled():
    v = str(get_setting("FUYAO_ENABLED", "1") or "").strip().lower()
    if v in ("0", "false", "no", "off", ""):
        return False
    return bool((get_setting("FUYAO_API_KEY", "") or "").strip())

def set_setting(key, value):
    if key not in SETTING_KEYS:
        raise KeyError(f"未知设置键: {key}")
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    _db_set(key, str(value))
    with _LOCK:
        SETTINGS[key] = value

def all_settings():
    with _LOCK:
        return dict(SETTINGS)

def apply_runtime_settings():
    import importlib
    import data_source
    import data_service
    importlib.reload(data_source)
    data_service.pro = data_source.get_pro()
    data_service.pro_bar = data_source.get_pro_bar()
