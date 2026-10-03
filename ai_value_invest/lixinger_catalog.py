
DOC_BASE = "https://www.lixinger.com/api/open-api/html-doc/"
BASE_URL = "https://open.lixinger.com"

USAGE = {
    "method": "POST",
    "content_type": "application/json",
    "accept_encoding": "gzip, deflate, br, *",
    "rate_limit": "每分钟最大 1000 次、每秒钟 36 次；超出返回 HTTP 429 (Too Many Request)",
    "retry": "调用方应具备重试机制（网络错误 / 429 退避重试），Lixinger 每分钟自检一次服务状态",
    "auth": "请求体 JSON 内携带用户专属 token（配置于 config.LIXINGER_TOKEN / .env）",
    "doc_index": "https://www.lixinger.com/api/open-api/url-doc",
}

PARAMS = {
    "cn/company": {
        "token": "用户专属 Token（必填）",
        "pageIndex": "页码，从 0 开始（必填）",
        "stockCodes": "股票代码数组，长度 1~100（可选）",
        "fsTableType": "财报类型 non_financial/bank/insurance/security/other_financial（可选）",
    },
    "cn/company/hot/t_a": {
        "token": "用户专属 Token（必填）",
        "sortName": "排序字段（不传 stockCodes 时必填，如 tatnpa_last）",
        "sortOrder": "排序顺序 asc / desc（不传 stockCodes 时必填）",
        "pageIndex": "页码，从 0 开始",
        "pageSize": "每页条数 1~100，默认 100",
        "stockCodes": "股票代码数组（可选，传入则按代码查询）",
    },
    "cn/index/candlestick": {
        "token": "用户专属 Token（必填）",
        "stockCode": "指数代码（必填，如 000016）",
        "type": "收盘点位类型 normal / total_return（必填）",
        "startDate": "开始日期 YYYY-MM-DD（必填，间隔≤10年）",
        "endDate": "结束日期 YYYY-MM-DD（可选，默认今天）",
    },
}

PROBE = {
    "cn/company": {"pageIndex": 0},
    "cn/company/hot/t_a": {"sortName": "tatnpa_last", "sortOrder": "desc", "pageIndex": 0, "pageSize": 5},
    "cn/index/candlestick": {"stockCode": "000016", "type": "normal",
                             "startDate": "2025-08-27", "endDate": "2026-08-27"},
}

RAW = {
    "大陆 CN": {
        "公司接口": [
            "cn/company|基础信息",
            "cn/company/profile|公司概况",
            "cn/company/equity-change|股本变动",
            "cn/company/candlestick|K线数据",
            "cn/company/volatility|波动率",
            "cn/company/shareholders-num|股东人数",
            "cn/company/senior-executive-shares-change|高管增减持",
            "cn/company/major-shareholders-shares-change|大股东增减持",
            "cn/company/trading-abnormal|龙虎榜",
            "cn/company/block-deal|大宗交易",
            "cn/company/pledge|股权质押",
            "cn/company/operation-revenue-constitution|营收构成",
            "cn/company/operating-data|经营数据",
            "cn/company/indices|股票所属指数",
            "cn/company/industries|股票所属行业",
            "cn/company/announcement|公告",
            "cn/company/measures|监管措施",
            "cn/company/inquiry|问询函",
            "cn/company/majority-shareholders|前十大股东",
            "cn/company/nolimit-shareholders|前十大流通股东",
            "cn/company/fund-shareholders|公募基金持股",
            "cn/company/fund-collection-shareholders|基金公司持股",
            "cn/company/dividend|分红",
            "cn/company/allotment|配股",
            "cn/company/customers|客户",
            "cn/company/suppliers|供应商",
            "cn/company/fundamental/non_financial|基本面数据-非金融",
            "cn/company/fundamental/bank|基本面数据-银行",
            "cn/company/fundamental/security|基本面数据-证券",
            "cn/company/fundamental/insurance|基本面数据-保险",
            "cn/company/fundamental/other_financial|基本面数据-其他金融",
            "cn/company/fs/non_financial|财务报表-非金融",
            "cn/company/fs/bank|财务报表-银行",
            "cn/company/fs/security|财务报表-证券",
            "cn/company/fs/insurance|财务报表-保险",
            "cn/company/fs/other_financial|财务报表-其他金融",
            "cn/company/hot/tr_dri|热度-分红再投入收益率",
            "cn/company/hot/mm_ha|热度-互联互通",
            "cn/company/hot/mtasl|热度-融资融券",
            "cn/company/hot/esc|热度-高管增减持",
            "cn/company/hot/mssc|热度-大股东增减持",
            "cn/company/hot/t_a|热度-龙虎榜",
            "cn/company/hot/elr|热度-限售解禁",
            "cn/company/hot/ple|热度-股权质押",
            "cn/company/hot/capita|热度-人均指标",
            "cn/company/hot/shnc|热度-股东人数变化",
            "cn/company/hot/df|热度-分红融资",
            "cn/company/hot/npd|热度-派息",
            "cn/company/hot/tr|热度-换手率",
            "cn/company/mutual-market|资金流向-互联互通",
            "cn/company/margin-trading-and-securities-lending|资金流向-融资融券",
            "cn/company/market-data/margin-trading-and-securities-lending|市场数据-融资融券",
            "cn/company/market-data/mutual-market|市场数据-互联互通",
        ],
        "指数接口": [
            "cn/index|基础信息",
            "cn/index/constituents|样本信息",
            "cn/index/constituent-weightings|样本权重",
            "cn/index/candlestick|K线数据",
            "cn/index/drawdown|回撤",
            "cn/index/volatility|波动率",
            "cn/index/tracking-fund|跟踪基金",
            "cn/index/fundamental|基本面数据",
            "cn/index/fs/hybrid|财务报表-混合",
            "cn/index/fs/non_financial|财务报表-非金融",
            "cn/index/fs/bank|财务报表-银行",
            "cn/index/fs/security|财务报表-证券",
            "cn/index/hot/mm_ha|热度-互联互通",
            "cn/index/hot/mtasl|热度-融资融券",
            "cn/index/hot/cp|热度-收益率",
            "cn/index/hot/tr_cp|热度-全收益率",
            "cn/index/hot/ic|热度-样本",
            "cn/index/hot/ifet_sni|热度-场内基金认购净流入",
            "cn/index/hot/tr|热度-换手率",
            "cn/index/mutual-market|资金流向-互联互通",
            "cn/index/margin-trading-and-securities-lending|资金流向-融资融券",
        ],
        "行业接口-申万2021": [
            "cn/industry|基础信息",
            "cn/industry/constituents/sw_2021|样本信息",
            "cn/industry/fundamental/sw_2021|基本面数据",
            "cn/industry/fs/sw_2021/hybrid|财务报表-混合",
            "cn/industry/fs/sw_2021/non_financial|财务报表-非金融",
            "cn/industry/fs/sw_2021/bank|财务报表-银行",
            "cn/industry/fs/sw_2021/security|财务报表-证券",
            "cn/industry/fs/sw_2021/insurance|财务报表-保险",
            "cn/industry/hot/mm_ha/sw_2021|热度-互联互通",
            "cn/industry/hot/mtasl/sw_2021|热度-融资融券",
            "cn/industry/mutual-market/sw_2021|资金流向-互联互通",
            "cn/industry/margin-trading-and-securities-lending/sw_2021|资金流向-融资融券",
        ],
        "行业接口-申万": [
            "cn/industry/constituents/sw|样本信息",
            "cn/industry/fundamental/sw|基本面数据",
            "cn/industry/fs/sw/hybrid|财务报表-混合",
            "cn/industry/fs/sw/non_financial|财务报表-非金融",
            "cn/industry/fs/sw/bank|财务报表-银行",
            "cn/industry/fs/sw/security|财务报表-证券",
            "cn/industry/fs/sw/insurance|财务报表-保险",
            "cn/industry/hot/mm_ha/sw|热度-互联互通",
            "cn/industry/hot/mtasl/sw|热度-融资融券",
            "cn/industry/mutual-market/sw|资金流向-互联互通",
            "cn/industry/margin-trading-and-securities-lending/sw|资金流向-融资融券",
        ],
        "行业接口-国证": [
            "cn/industry/constituents/cni|样本信息",
            "cn/industry/fundamental/cni|基本面数据",
            "cn/industry/fs/cni/hybrid|财务报表-混合",
            "cn/industry/fs/cni/non_financial|财务报表-非金融",
            "cn/industry/fs/cni/bank|财务报表-银行",
            "cn/industry/fs/cni/security|财务报表-证券",
            "cn/industry/fs/cni/insurance|财务报表-保险",
            "cn/industry/hot/mm_ha/cni|热度-互联互通",
            "cn/industry/hot/mtasl/cni|热度-融资融券",
            "cn/industry/mutual-market/cni|资金流向-互联互通",
            "cn/industry/margin-trading-and-securities-lending/cni|资金流向-融资融券",
        ],
        "公募基金": [
            "cn/fund|基础信息",
            "cn/fund/profile|基金概况",
            "cn/fund/manager|基金经理",
            "cn/fund/candlestick|K线数据",
            "cn/fund/net-value|净值",
            "cn/fund/total-net-value|基金累积净值",
            "cn/fund/net-value-of-dividend-reinvestment|分红再投入净值",
            "cn/fund/fees|费用",
            "cn/fund/drawdown|回撤",
            "cn/fund/volatility|波动率",
            "cn/fund/turnover-rate|持仓换手率",
            "cn/fund/dividend|分红",
            "cn/fund/split|拆分",
            "cn/fund/shares|基金份额及规模",
            "cn/fund/shareholders-structure|持有人结构",
            "cn/fund/shareholdings|基金持股",
            "cn/fund/asset-combination|资产组合",
            "cn/fund/asset-industry-combination|按行业分类的股票投资组合",
            "cn/fund/announcement|公告",
            "cn/fund/hot/fp|热度-分红再投入收益率",
            "cn/fund/hot/fpr|热度-分红再投入收益率排名",
            "cn/fund/hot/f_as|热度-最新资产规模信息",
            "cn/fund/hot/ff|热度-最新费用信息",
            "cn/fund/hot/fss|热度-最新持有人结构信息",
            "cn/fund/hot/fet_s|热度-最新场内份额信息",
            "cn/fund/hot/f_nlacan|热度-最新收盘价溢价率信息",
        ],
        "基金经理": [
            "cn/fund-manager|基础信息",
            "cn/fund-manager/management-funds|管理的基金",
            "cn/fund-manager/profit-ratio|利润率",
            "cn/fund-manager/shareholdings|基金经理持仓",
            "cn/fund-manager/hot/fmi|热度-基金经理信息",
            "cn/fund-manager/hot/fmp|热度-基金经理收益率",
        ],
        "基金公司": [
            "cn/fund-company|基础信息",
            "cn/fund-company/fund-list|基金列表",
            "cn/fund-company/fund-manager-list|基金经理列表",
            "cn/fund-company/asset-scale|总资产规模",
            "cn/fund-company/shareholdings|基金公司持股",
            "cn/fund-company/hot/fc_as|热度-基金公司资产规模",
            "cn/fund-company/hot/fc_asr|热度-基金公司资产规模排名",
        ],
    },
    "香港 HK": {
        "公司接口": [
            "hk/company|基础信息",
            "hk/company/profile|公司概况",
            "hk/company/candlestick|K线数据",
            "hk/company/volatility|波动率",
            "hk/company/equity-change|股本变动",
            "hk/company/employee|员工",
            "hk/company/repurchase|回购",
            "hk/company/short-selling|做空",
            "hk/company/operation-revenue-constitution|营收构成",
            "hk/company/indices|股票所属指数",
            "hk/company/industries|股票所属行业",
            "hk/company/announcement|公告",
            "hk/company/latest-shareholders|股东-最新股东",
            "hk/company/shareholders-equity-change|股东权益变动",
            "hk/company/fund-shareholders|内资基金持股",
            "hk/company/fund-collection-shareholders|内资基金公司持股",
            "hk/company/dividend|分红",
            "hk/company/split|拆分",
            "hk/company/allotment|配股",
            "hk/company/fundamental/non_financial|基本面-非金融",
            "hk/company/fundamental/bank|基本面-银行",
            "hk/company/fundamental/security|基本面-证券",
            "hk/company/fundamental/insurance|基本面-保险",
            "hk/company/fundamental/reit|基本面-房地产投资信托",
            "hk/company/fundamental/other_financial|基本面-其他金融",
            "hk/company/fs/non_financial|财务报表-非金融",
            "hk/company/fs/bank|财务报表-银行",
            "hk/company/fs/security|财务报表-证券",
            "hk/company/fs/insurance|财务报表-保险",
            "hk/company/fs/reit|财务报表-房地产投资信托",
            "hk/company/fs/other_financial|财务报表-其他金融",
            "hk/company/hot/tr_dri|热度-分红再投入收益率",
            "hk/company/hot/mm_ah|热度-互联互通",
            "hk/company/hot/rep|热度-回购",
            "hk/company/hot/ss|热度-做空",
            "hk/company/hot/director_equity_change|热度-董事权益变动",
            "hk/company/hot/npd|热度-派息",
            "hk/company/hot/capita|热度-人均指标",
            "hk/company/hot/tr|热度-换手率",
            "hk/company/hot/ss_ha|热度-跨市场比价HA",
            "hk/company/mutual-market|资金流向-互联互通",
            "hk/company/market-data/mutual-market|市场数据-互联互通",
        ],
        "指数接口": [
            "hk/index|基础信息",
            "hk/index/candlestick|K线数据",
            "hk/index/constituents|样本信息",
            "hk/index/drawdown|回撤",
            "hk/index/volatility|波动率",
            "hk/index/tracking-fund|跟踪基金",
            "hk/index/fundamental|基本面数据",
            "hk/index/fs/hybrid|财务报表-混合",
            "hk/index/fs/non_financial|财务报表-非金融",
            "hk/index/hot/mm_ah|热度-互联互通",
            "hk/index/hot/cp|热度-收益率",
            "hk/index/hot/ic|热度-样本",
            "hk/index/hot/ifet_sni|热度-场内基金认购净流入",
            "hk/index/mutual-market|资金流向-互联互通",
        ],
        "行业接口-恒生": [
            "hk/industry|基础信息",
            "hk/industry/constituents/hsi|恒生-样本信息",
            "hk/industry/fundamental/hsi|恒生-基本面数据",
            "hk/industry/fs/hsi/hybrid|恒生-财务报表-混合",
            "hk/industry/fs/hsi/non_financial|恒生-财务报表-非金融",
            "hk/industry/hot/mm_ah/hsi|恒生-热度-互联互通",
            "hk/industry/mutual-market/hsi|恒生-资金流向-互联互通",
        ],
    },
    "美国 US": {
        "指数接口": [
            "us/index|基础信息",
            "us/index/candlestick|K线数据",
            "us/index/constituents|样本信息",
            "us/index/drawdown|回撤",
            "us/index/volatility|波动率",
            "us/index/tracking-fund|跟踪基金",
            "us/index/fundamental|基本面数据",
            "us/index/fs/non_financial|财务报表-非金融",
            "us/index/hot/cp|热度-收益率",
            "us/index/hot/ifet_sni|热度-场内基金认购净流入",
        ],
    },
    "宏观 Macro": {
        "宏观数据": [
            "macro/investor|证券市场-投资者",
            "macro/credit-securities-account|证券市场-信用证券账户",
            "macro/stamp-duty|证券市场-印花税",
            "macro/price-index|价格指数",
            "macro/required-reserves|存款备用金",
            "macro/money-supply|货币供应",
            "macro/national-debt|国债",
            "macro/interest-rates|利率",
            "macro/social-financing|社会融资",
            "macro/rmb-deposits|人民币存款",
            "macro/rmb-loans|人民币贷款",
            "macro/central-bank-balance-sheet|央行资产负债表",
            "macro/official-reserve-assets|官方储备资产",
            "macro/foreign-assets|国外资产",
            "macro/domestic-debt-securities|国内各类债券",
            "macro/national-finance|国家财政",
            "macro/leverage-ratio|杠杆率",
            "macro/population|人口",
            "macro/gdp|GDP",
            "macro/unemployment-rate|失业率",
            "macro/domestic-trade|社会消费品零售",
            "macro/foreign-trade|对外贸易",
            "macro/bop|国际收支平衡",
            "macro/traffic-transportation|交通运输",
            "macro/investment-in-fixed-assets|全社会固定资产投资",
            "macro/real-estate|房地产",
            "macro/energy|能源",
            "macro/crude-oil|大宗商品-原油",
            "macro/natural-gas|大宗商品-天然气",
            "macro/gold-price|大宗商品-黄金",
            "macro/silver-price|大宗商品-白银",
            "macro/platinum-price|大宗商品-铂金",
            "macro/non-ferrous-metals|大宗商品-有色金属",
            "macro/industrialization|工业",
            "macro/vix-fear-index|VIX恐慌指数",
            "macro/usdx|美元指数",
            "macro/rmbidx|人民币指数",
            "macro/market-index|债券类市场指数",
            "macro/currency-exchange-rate|汇率",
        ],
    },
}

def _build():
    items = []
    for region, cats in RAW.items():
        for category, entries in cats.items():
            for entry in entries:
                suffix, name = entry.split("|", 1)
                api = "/api/" + suffix
                doc = DOC_BASE + suffix
                params = dict(PARAMS.get(suffix, {"token": "用户专属 Token（必填）"}))
                item = {
                    "region": region,
                    "category": category,
                    "api": api,
                    "name": name,
                    "method": "POST",
                    "doc": doc,
                    "params": params,
                }
                if suffix in PROBE:
                    item["probe"] = PROBE[suffix]
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
    rc = Counter(i["region"] for i in CATALOG)
    cc = Counter(i["category"] for i in CATALOG)
    print(f"共 {len(CATALOG)} 个接口条目")
    print("按区域：")
    for r, n in rc.items():
        print(f"  {r}: {n}")
    print("按分类：")
    for c, n in cc.items():
        print(f"  {c}: {n}")
