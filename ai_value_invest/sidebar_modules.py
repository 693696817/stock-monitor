
PLACEMENTS = [
    {"key": "home", "name": "首页模块", "icon": "fa-house",
     "desc": "首页自上而下的各个内容区块"},
    {"key": "analysis", "name": "分析页右侧边栏", "icon": "fa-chart-column",
     "desc": "股票分析页右侧：市场总览 / 市场情绪 / 热门个股"},
    {"key": "news", "name": "快讯页右侧边栏", "icon": "fa-newspaper",
     "desc": "市场快讯页右侧：实时大盘 / 重大快讯 / AI 情绪 / 热点标签 / 今日统计"},
    {"key": "market", "name": "大盘页卡片", "icon": "fa-chart-line",
     "desc": "大盘分析页：指数卡 / 市场活跃度 / 情绪走势 / 资金流向"},
    {"key": "hot", "name": "热门个股页模块", "icon": "fa-fire",
     "desc": "热门个股页：人气热榜 / 本站分析榜"},
]

MODULES = [
    {
        "key": "home.ticker",
        "name": "大盘行情条",
        "placement": "home",
        "icon": "fa-chart-line",
        "desc": "首屏搜索框下方的滚动行情条（三大指数 + 成交额）",
        "source": "行情快照接口（指数日线 + 成交额）",
        "options": [
            {"key": "auto_refresh", "label": "自动刷新", "type": "bool", "default": True,
             "help": "关闭后页面加载时取一次，不再定时轮询"},
            {"key": "refresh_sec", "label": "刷新间隔(秒)", "type": "int", "default": 60,
             "min": 15, "max": 600, "help": "仅在开启自动刷新时生效"},
        ],
    },
    {
        "key": "home.hot_stocks",
        "name": "热股榜",
        "placement": "home",
        "icon": "fa-fire",
        "desc": "首页热股榜（默认同花顺人气榜，可切成本站分析榜）",
        "source": "同花顺人气榜 / 本站分析记录",
        "options": [
            {"key": "source", "label": "数据源", "type": "select", "default": "ths",
             "choices": [
                 {"value": "ths", "label": "同花顺人气榜（市场热度）"},
                 {"value": "local", "label": "本站分析榜（近 7 天分析次数）"},
             ]},
            {"key": "limit", "label": "显示条数", "type": "int", "default": 8, "min": 3, "max": 20},
        ],
    },
    {
        "key": "home.steps",
        "name": "三步使用引导",
        "placement": "home",
        "icon": "fa-list-ol",
        "desc": "「三步开启你的价值投资研究」说明区块",
        "source": "静态文案",
        "options": [],
    },
    {
        "key": "home.perspectives",
        "name": "投资视角卡片",
        "placement": "home",
        "icon": "fa-layer-group",
        "desc": "展示当前启用的投资偏好视角，点击进入对应分析",
        "source": "系统设置 · 投资偏好",
        "options": [
            {"key": "limit", "label": "显示数量", "type": "int", "default": 6, "min": 0, "max": 24,
             "help": "0 表示不限制"},
            {"key": "vip_only", "label": "只显示 VIP 视角", "type": "bool", "default": False},
        ],
    },

    {
        "key": "analysis.market_overview",
        "name": "市场总览",
        "placement": "analysis",
        "icon": "fa-chart-pie",
        "desc": "两市成交额 / 龙虎榜家数 / 北向资金 + 三大指数",
        "source": "行情快照接口（指数日线 + 沪深港通 + 龙虎榜）",
        "options": [
            {"key": "show_indices", "label": "显示三大指数", "type": "bool", "default": True},
            {"key": "show_breadth", "label": "显示涨跌家数", "type": "bool", "default": True,
             "help": "全市场真实统计，非估算"},
            {"key": "show_north", "label": "显示北向资金", "type": "bool", "default": True,
             "help": "沪深港通 T+1 发布，当日未落地时标注实际数据日期"},
            {"key": "show_limit_count", "label": "显示龙虎榜家数", "type": "bool", "default": True},
        ],
    },
    {
        "key": "analysis.sentiment",
        "name": "市场情绪",
        "placement": "analysis",
        "icon": "fa-bullseye",
        "desc": "情绪指针（0 极度恐慌 → 100 极度贪婪）",
        "source": "龙虎榜净买入方向 + 北向资金方向",
        "options": [
            {"key": "algorithm", "label": "计算口径", "type": "select", "default": "lhb_north",
             "choices": [
                 {"value": "lhb_north", "label": "龙虎榜涨跌比 + 北向方向（默认）"},
                 {"value": "lhb_only", "label": "仅龙虎榜涨跌比"},
                 {"value": "north_only", "label": "仅北向资金方向"},
             ],
             "help": "北向缺失时自动按所选口径重算，不再计入该项"},
        ],
    },
    {
        "key": "analysis.hot_stocks",
        "name": "热门个股",
        "placement": "analysis",
        "icon": "fa-fire-flame-curved",
        "desc": "边栏热门个股列表",
        "source": "同花顺人气榜 / 本站分析记录",
        "options": [
            {"key": "source", "label": "数据源", "type": "select", "default": "ths",
             "choices": [
                 {"value": "ths", "label": "同花顺人气榜（市场热度）"},
                 {"value": "local", "label": "本站分析榜（近 7 天分析次数）"},
             ]},
            {"key": "limit", "label": "显示条数", "type": "int", "default": 6, "min": 1, "max": 12},
        ],
    },

    {
        "key": "news.market",
        "name": "实时大盘",
        "placement": "news",
        "icon": "fa-chart-line",
        "desc": "边栏实时大盘（复用 /api/market-snapshot）",
        "source": "行情快照接口",
        "options": [
            {"key": "refresh_sec", "label": "刷新间隔(秒)", "type": "int", "default": 60,
             "min": 15, "max": 600},
        ],
    },
    {
        "key": "news.important",
        "name": "重大快讯",
        "placement": "news",
        "icon": "fa-fire",
        "desc": "命中重大关键词的快讯，可点击定位到正文",
        "source": "快讯库（本地落库，每小时同步）",
        "options": [
            {"key": "limit", "label": "显示条数", "type": "int", "default": 8, "min": 1, "max": 30},
        ],
    },
    {
        "key": "news.sentiment",
        "name": "AI 市场情绪",
        "placement": "news",
        "icon": "fa-gauge-high",
        "desc": "基于当日快讯利好/利空统计的情绪刻度 + 点评",
        "source": "快讯库情绪统计（本地关键词判定）",
        "options": [
            {"key": "show_comment", "label": "显示点评文字", "type": "bool", "default": True},
        ],
    },
    {
        "key": "news.hot_tags",
        "name": "热点标签",
        "placement": "news",
        "icon": "fa-hashtag",
        "desc": "当日高频标签，点击可筛选快讯",
        "source": "快讯库标签统计",
        "options": [
            {"key": "limit", "label": "标签数量", "type": "int", "default": 15, "min": 5, "max": 50},
        ],
    },
    {
        "key": "news.stats",
        "name": "今日统计",
        "placement": "news",
        "icon": "fa-chart-pie",
        "desc": "利好 / 利空 / 总快讯 / 重大快讯 四项计数",
        "source": "快讯库统计",
        "options": [],
    },

    {
        "key": "market.indices",
        "name": "三大指数卡",
        "placement": "market",
        "icon": "fa-chart-simple",
        "desc": "上证 / 深证 / 创业板 实时点位与涨跌幅",
        "source": "行情快照接口（指数日线）",
        "options": [],
    },
    {
        "key": "market.breadth",
        "name": "市场活跃度",
        "placement": "market",
        "icon": "fa-layer-group",
        "desc": "涨跌家数分布 + 成交额 + 龙虎榜 + 北向资金",
        "source": "全市场行情快照（收盘口径）/ 沪深港通 / 龙虎榜",
        "options": [
            {"key": "show_breadth", "label": "显示涨跌家数", "type": "bool", "default": True},
            {"key": "show_north", "label": "显示北向资金", "type": "bool", "default": True},
            {"key": "north_warn_if_stale", "label": "北向非当日时标注日期", "type": "bool", "default": True,
             "help": "沪深港通为 T+1 发布，标注可避免误读"},
        ],
    },
    {
        "key": "market.sentiment_chart",
        "name": "情绪走势图",
        "placement": "market",
        "icon": "fa-wave-square",
        "desc": "上证近 30 日走势 + 情绪刻度条",
        "source": "行情快照接口（指数日线历史）",
        "options": [
            {"key": "days", "label": "历史天数", "type": "int", "default": 30, "min": 10, "max": 60},
        ],
    },
    {
        "key": "market.limit_ladder",
        "name": "涨停天梯",
        "placement": "market",
        "icon": "fa-stairs",
        "desc": "最高连板高度 + 连板梯队分布 + 近 N 日高度走势（赚钱效应）",
        "source": "金融大数据（连板梯队矩阵，近 30 个交易日）",
        "options": [
            {"key": "show_trend", "label": "显示较前一日变化", "type": "bool", "default": True},
            {"key": "show_hist", "label": "显示连板高度走势图", "type": "bool", "default": True},
            {"key": "hist_days", "label": "走势图天数", "type": "int", "default": 30, "min": 10, "max": 30,
             "help": "数据源最多提供近 30 个交易日"},
        ],
    },
    {
        "key": "market.hot_rank",
        "name": "市场人气榜",
        "placement": "market",
        "icon": "fa-fire",
        "desc": "全市场人气 TOP + 热度飙升榜（含名次变化）",
        "source": "金融大数据（24 小时滚动人气统计）",
        "options": [
            {"key": "limit", "label": "显示条数", "type": "int", "default": 10, "min": 5, "max": 30},
        ],
    },
    {
        "key": "market.money_flow",
        "name": "主力资金流向",
        "placement": "market",
        "icon": "fa-money-bill-transfer",
        "desc": "沪股通 / 深股通 / 北向合计 资金流向图",
        "source": "沪深港通资金流",
        "options": [],
    },

    {
        "key": "hot.ths_rank",
        "name": "人气热榜 TOP20",
        "placement": "hot",
        "icon": "fa-ranking-star",
        "desc": "同花顺人气榜（含上榜解读）",
        "source": "同花顺人气榜",
        "options": [
            {"key": "show_reason", "label": "显示上榜解读", "type": "bool", "default": True,
             "help": "概念/行业板块接口不返回解读，缺解读时回退「关联概念」"},
        ],
    },
    {
        "key": "hot.local_rank",
        "name": "本站热门分析 TOP10",
        "placement": "hot",
        "icon": "fa-arrow-trend-up",
        "desc": "近 7 天本站分析次数最多的个股（只统计成功记录）",
        "source": "本站分析记录",
        "options": [
            {"key": "days", "label": "统计天数", "type": "int", "default": 7, "min": 1, "max": 30},
            {"key": "limit", "label": "显示条数", "type": "int", "default": 10, "min": 3, "max": 30},
        ],
    },
]

def _opt_default(opt):
    return opt.get("default")

def default_config():
    counters = {}
    cfg = {}
    for m in MODULES:
        p = m["placement"]
        counters[p] = counters.get(p, 0) + 10
        cfg[m["key"]] = {
            "enabled": True,
            "order": counters[p],
            "options": {o["key"]: _opt_default(o) for o in m.get("options", [])},
        }
    return cfg

def _coerce(opt, value):
    default = _opt_default(opt)
    t = opt.get("type")
    try:
        if t == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        if t == "int":
            n = int(value)
            lo = opt.get("min"); hi = opt.get("max")
            if lo is not None:
                n = max(lo, n)
            if hi is not None:
                n = min(hi, n)
            return n
        if t == "select":
            allowed = {c["value"] for c in opt.get("choices", [])}
            return value if value in allowed else default
        if t == "text":
            return str(value)
    except Exception:
        return default
    return default

def normalize(stored):
    base = default_config()
    if not isinstance(stored, dict):
        return base

    for key, cur in base.items():
        saved = stored.get(key)
        if not isinstance(saved, dict):
            continue
        if "enabled" in saved:
            cur["enabled"] = bool(saved["enabled"])
        if "order" in saved:
            try:
                cur["order"] = int(saved["order"])
            except Exception:
                pass
        saved_opts = saved.get("options")
        if isinstance(saved_opts, dict):
            for opt in next((m for m in MODULES if m["key"] == key), {}).get("options", []):
                if opt["key"] in saved_opts:
                    cur["options"][opt["key"]] = _coerce(opt, saved_opts[opt["key"]])
    return base

def by_placement():
    out = {}
    for m in MODULES:
        out.setdefault(m["placement"], []).append(m)
    return out
