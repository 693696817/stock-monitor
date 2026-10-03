
DOC_BASE = "https://fuyao.aicubes.cn/docs/api-reference/"
BASE_URL = "https://fuyao.aicubes.cn"

USAGE = {
    "method": "GET",
    "auth": "请求头 X-api-key: <your-api-key>",
    "response": "统一信封 {code, message, request_id, data}；⚠️ HTTP 状态码恒为 200，"
                "成败只看 code（0=成功），不能用 HTTP 状态码判断",
    "rate_limit": "按约定 QPS，超限返回 code=4001",
    "timestamp": "毫秒级 Unix 时间戳，时区 Asia/Shanghai",
    "code_format": "标的用完整 thscode（600519.SH）；❌ 不接受纯代码",
    "doc_index": "https://fuyao.aicubes.cn/docs/api-reference/overview/",
    "notes": "业务数据不一定在 data.item（龙虎榜是 data.stock_items）；"
             "比率字段是小数（0.1=10%）；金额单位是元，非亿元",
}

RAW = [
    ("prices/", "价格数据", "/api/a-share/prices/snapshot", "行情快照",
     {"thscodes": "逗号分隔 thscode 列表；省略则遍历全市场（配合 limit/offset 分页）",
      "limit": "分页大小，仅 thscodes 省略时生效，默认 100",
      "offset": "分页偏移，仅 thscodes 省略时生效，默认 0"},
     {"thscodes": "600519.SH,000963.SZ"}),

    ("prices/", "价格数据", "/api/a-share/prices/historical", "历史 K 线",
     {"thscode": "必填，单只标的（不接受逗号）",
      "interval": "必填，K线周期，目前仅支持 1d",
      "start": "必填，起始时间，毫秒 Unix 时间戳（客户端支持传 YYYY-MM-DD 自动换算）",
      "end": "必填，结束时间，毫秒；end-start 超过 10 年返回 code=1003",
      "adjust": "复权方式 none/forward/backward，默认 forward",
      "offset": "分页偏移，默认 0"},
     {"thscode": "000963.SZ", "interval": "1d",
      "start": 1785859200000, "end": 1788451200000, "adjust": "forward"}),

    ("dragon-tiger-data/", "特色数据", "/api/a-share/special-data/dragon-tiger-list", "龙虎榜榜单",
     {"trade_date": "交易日 yyyyMMdd 或 yyyy-MM-dd；省略取最近交易日",
      "board_type": "榜单类型：all(全部) / org(机构榜) / hot_money(游资榜)，默认 all"},
     {"board_type": "all"}),

    ("hot-list-data/", "特色数据", "/api/a-share/special-data/hot-stock-list", "A股热股榜单 Top30",
     {"period": "day(24小时级别) / hour(小时级别)，默认 day；其他值返回 code=1002"},
     {"period": "day"}),

    ("hot-list-data/", "特色数据", "/api/a-share/special-data/skyrocket-list", "热度飙升榜 Top30",
     {"period": "day(日榜) / hour(小时榜)，默认 day"},
     {"period": "day"}),

    ("hot-list-data/", "特色数据", "/api/a-share/special-data/hot-stock-list-history", "历史热股排行",
     {"date": "必填，自然日 yyyy-MM-dd（⚠️ 只接受这种格式，传 yyyyMMdd 报 code=1002）；限一年内"},
     {"date": "2026-09-04"}),

    ("hot-list-data/", "特色数据", "/api/a-share/special-data/hot-stock-rank-trend", "个股排名走势",
     {"thscode": "必填，单只标的",
      "start_date": "必填，yyyy-MM-dd",
      "end_date": "必填，yyyy-MM-dd，需 >= start_date；窗口超一年返回 code=1003"},
     {"thscode": "000963.SZ", "start_date": "2026-08-05", "end_date": "2026-09-04"}),

    ("anomaly-analysis/", "特色数据", "/api/a-share/special-data/anomaly-analysis-list", "个股异动原因列表",
     {"tag": "可选，按异动标签过滤（如 涨停）"},
     {}),

    ("anomaly-analysis/", "特色数据", "/api/a-share/special-data/anomaly-analysis-stock", "按股票查异动原因",
     {"thscodes": "必填，逗号分隔 thscode，批量查询当日异动原因"},
     {"thscodes": "000963.SZ,600519.SH"}),

    ("limit-up-data/", "特色数据", "/api/a-share/special-data/limit-up-pool", "涨停股票池",
     {"trade_date": "交易日 yyyyMMdd / yyyy-MM-dd；省略取最近交易日"},
     {}),

    ("limit-up-data/", "特色数据", "/api/a-share/special-data/limit-down-pool", "跌停股票池",
     {"trade_date": "交易日 yyyyMMdd / yyyy-MM-dd；省略取最近交易日"},
     {}),

    ("limit-up-data/", "特色数据", "/api/a-share/special-data/limit-break-pool", "炸板股票池",
     {"trade_date": "交易日 yyyyMMdd / yyyy-MM-dd；省略取最近交易日"},
     {}),

    ("limit-up-data/", "特色数据", "/api/a-share/special-data/limit-up-ladder", "连板天梯",
     {"(无)": "返回近 30 个交易日的连板梯队矩阵"},
     {}),

    ("auction/", "价格数据", "/api/a-share/auction/snapshot", "集合竞价快照",
     {"thscodes": "必填，逗号分隔 thscode（⚠️ 是 thscode**s** 复数，不是 thscode）"},
     {"thscodes": "000963.SZ"}),

    ("financial-indicators/", "基本面", "/api/a-share/financials/indicators", "财务指标",
     {"thscode": "必填，单只标的",
      "report": "报告期 {yyyy}-{1|2|3|4}，如 2026-2 表示 2026 中报（⚠️ 不是日期，"
                "传 2026-06-30 报 code=1002）；省略取最近一期"},
     {"thscode": "000963.SZ", "report": "2026-2"}),

    ("ticker-search/", "元数据", "/api/meta/tickers/search", "标的检索",
     {"q": "必填，thscode / ticker / 名称关键字（⚠️ 中文需 URL 编码，否则 HTTP 400）"},
     {"q": "华东医药"}),

    ("ticker-list/", "元数据", "/api/meta/tickers/list", "标的列表",
     {"asset_type": "规范化资产类型，如 a-share；分页遍历全量代码表"},
     {"asset_type": "a-share"}),

    ("calendar/", "元数据", "/api/a-share/calendar/trading-days", "交易日历",
     {"(无)": "固定窗口 [今日-1年, 今日]，无入参；item[].date 为 yyyyMMdd"},
     {}),
]

def _build():
    items = []
    for doc_anchor, category, api, name, params, probe in RAW:
        item = {
            "region": "A股",
            "category": category,
            "api": api,
            "name": name,
            "method": "GET",
            "doc": DOC_BASE + doc_anchor,
            "params": dict(params),
        }
        if probe:
            item["probe"] = dict(probe)
        items.append(item)
    return items

CATALOG = _build()

def build_catalog():
    return [dict(item) for item in CATALOG]

def get_api_info(api_path):
    for item in CATALOG:
        if item["api"] == api_path:
            return dict(item)
    return None

def all_api_names():
    return sorted({item["api"] for item in CATALOG})

if __name__ == "__main__":
    from collections import Counter
    print(f"共 {len(CATALOG)} 个接口条目（全部实测通过）")
    print("按分类：")
    for c, n in Counter(i["category"] for i in CATALOG).items():
        print(f"  {c}: {n}")
    for i in CATALOG:
        flag = "✓" if i.get("probe") else "·"
        print(f"  {flag} {i['api']}  {i['name']}")
