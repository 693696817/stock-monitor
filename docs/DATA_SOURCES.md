# 数据源说明

本项目对外部数据源的依赖是「可选但冗余」设计：全部配置项留空时系统仍可运行（面板显示为空），配置后多源互为备份。

---

## 一、能力矩阵

| 数据源 | 环境变量 | 提供能力 |
|---|---|---|
| **Tushare 兼容聚合** | `DATAHUB_BASE_URL` `DATAHUB_API_KEY` | 日线行情、每日指标、估值分位、财报数据、披露计划、涨跌停统计 |
| **理杏仁** | `LIXINGER_TOKEN` | K 线（含复权）、估值指标（PE/PB/PS/股息率）、历史分位、财务明细、资金流、股东 |
| **伏尧 iFinD** | `FUYAO_TOKEN` | 龙虎榜、热门榜单、概念热度、题材榜、涨停梯队 |
| **AKShare** | 无需配置 | 兜底数据源（部分接口） |

---

## 二、数据组定义

数据面板由 22 个数据组构成，按投资偏好动态组合。

| 组 | 内容 | 主要来源 |
|---|---|---|
| `quote` | 现价、涨跌幅、总市值、流通市值、换手率、成交额、均线 | Tushare / 理杏仁 |
| `technical` | MACD、KDJ、RSI、BOLL、CCI、WR、BIAS、ATR、PSY、ROC、DMI、MTM、OBV | Tushare |
| `moneyflow` | 主力/超大单/大单/中单/小单净流入，近 5 日主力净额 | Tushare |
| `valuation` | PE、PB、PS、股息率、历史百分位、每股分红 | 理杏仁 / Tushare |
| `profitability` | ROE、ROIC、毛利率、净利率、资产负债率 | Tushare |
| `growth` | 营收/净利增速、扣非净利润、收入质量 | Tushare |
| `dividend` | 分红历史、分红率、股息连续年数 | 理杏仁 |
| `holder` | 股东户数、十大股东、机构持股 | Tushare |
| `industry` | 行业归属、同业对比 | 理杏仁 |
| `news` | 公司公告、新闻 | 伏尧 |
| `holder_trend` | 股东户数变化 | Tushare |
| `capital` | 资本开支、自由现金流 | Tushare |
| `forecast` | 业绩预告、快报 | Tushare |
| `tech_index` | 指数与行业指数 | 理杏仁 |
| `sentiment` | 市场情绪指标 | 内部计算 |
| `hot_rank` | 热门榜单 | 伏尧 |
| `event` | 事件驱动 | 伏尧 |
| `fundamental` | 基本面综合 | 理杏仁 |
| `comparison` | 同业横向对比 | 理杏仁 |
| `risk` | 风险指标（商誉、质押、诉讼） | Tushare |
| `theme` | 题材归属 | 伏尧 |
| `northbound` | 北向资金 | 第三方 |

---

## 三、故障降级策略

### 多源回退

同一指标优先走主源，失败或返回空时自动切备源。这保证单一服务商故障不会导致整个面板空白。

### 失效接口短路

部分第三方接口会在一段时间后下架（返回 `unknown api_name` 而非空数据）。这类接口**重试无用**，只会消耗配额与时间。

系统内置失效接口名单，入口处直接短路返回「不可用」状态：

```
ths_hot  dc_hot  kpl_concept  kpl_list
moneyflow_hsgt  hsgt_top10  ggt_top10
ths_index  ths_daily
```

> 名单在 `data_source.py` 的 `_DEPRECATED_DATAHUB_APIS`。若服务商日后恢复某接口，从名单中删除即可自动恢复。

### 分页限制

部分聚合服务的分页参数在升级后失效（传 `offset` 恒返回 0 行）。这类情况下按日期查询单次上限通常为 5000 条。

**替代方案**：先取第一页，再用本地股票池做差集，对缺失部分按代码批量补查。

### 当日数据未落地

交易日盘中或收盘后数据同步延迟时，当日数据会缺失。系统**自动回退到上一个交易日**并在界面标注实际数据日期，不会拿今天冒充。

---

## 四、代理注意事项

宿主机常会注入 `http_proxy` 环境变量，服务进程继承后所有外部请求绕道代理。若代理端口无人监听（宿主退出后），**全部外部请求失败**，且错误信息只显示「连接失败」。

系统启动时注入 `NO_PROXY` 白名单（国内数据源 + 国内 AI 渠道 + 本机地址），确保国内源直连。

⚠️ 境外源（部分 AI 服务）**保持走代理**是刻意设计：直连会长时间挂起，代理不可达至少能快速失败。

---

## 五、自建数据源

若需完全自持，可考虑自建 Tushare 镜像：

```bash
# MySQL 需开启 binlog（MySQL 5.7.7+）
my.cnf:
  log-bin=mysql-bin
  binlog-format=ROW
  server-id=1

# 启动 tushare 服务
git clone https://github.com/waditu/tushare
python tushare/pro/run.py
```

然后把 `DATAHUB_BASE_URL` 指向自建服务即可。AKShare 本身无需部署，直接可用。

---

## 六、申请与成本

| 服务 | 免费额度 | 说明 |
|---|---|---|
| Tushare Pro | 120 积分/注册 | 部分接口需 2000 积分 |
| 理杏仁 | 付费订阅 | 按接口计费 |
| 伏尧 iFinD | 付费订阅 | 按接口计费 |
| AKShare | 完全免费 | 数据来自公开接口，稳定性无保障 |

**生产建议**：至少配置两个数据源。免费额度在高频调用场景下极易触发限流，而限流会直接体现为面板数据缺失。
