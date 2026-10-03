# 接口清单

所有接口以 `/api` 开头。标注「需登录」的接口必须携带会话 Cookie。

---

## 一、公开接口（无需登录）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 首页 |
| GET | `/stock/{ts_code}` | 个股研究页 |
| GET | `/market` | 大盘概览 |
| GET | `/hot` | 热门个股 |
| GET | `/news` | 市场快讯 |
| GET | `/opportunities` | 机会捕捉 |
| GET | `/calendar` | 财报披露日历 |
| GET | `/risks` | 风险预警 |
| GET | `/pricing` | 价格方案 |
| GET | `/legal/{page}` | 法律条款 |
| GET | `/sitemap.xml` | 站点地图 |
| GET | `/robots.txt` | 爬虫策略 |
| GET | `/valuation` | **研报复盘** |
| GET | `/docs` | 接口文档（FastAPI 自动生成） |
| GET | `/api/stocks/search?q=&limit=` | 股票搜索（名称/代码，支持模糊匹配） |
| GET | `/api/stock/{ts_code}/...` | 个股公开数据（有限流保护） |
| GET | `/api/market-snapshot` | 大盘快照 |
| GET | `/api/analysis-options` | 可用投资偏好与数据组 |

---

## 二、认证相关

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/send-code` | 发送短信验证码（需图形验证码） |
| POST | `/api/auth/login` | 手机号 + 验证码登录 |
| POST | `/api/auth/register` | 注册（首次注册自动绑定邀请关系） |
| POST | `/api/auth/logout` | 退出登录 |
| GET | `/api/auth/me` | 当前用户信息 |

---

## 三、AI 分析（需登录 · 消耗配额）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/analysis` | 分析页 |
| POST | `/api/analyze` | **流式生成研报**（SSE / chunked） |
| GET | `/api/analysis/history` | 分析历史 |
| GET | `/api/analysis/archive/{rid}` | 研报详情 |
| GET | `/api/export-pdf` | 导出 PDF |
| GET | `/api/ai/quota` | 查询剩余配额 |
| GET | `/api/models` | 可用模型列表 |

### `POST /api/analyze` 请求体

```json
{
  "stock_code": "600519",
  "model_id": "m_xxx",
  "preference_id": "deep_value"
}
```

`preference_id` 可选值：`long_term_value`（长线价值）、`comprehensive`（综合）、`deep_value`（深度价值）。

### 响应

`text/event-stream`，分片推送。**首个分片前服务端会发送空行心跳**（防止反向代理掐断长连接），客户端应将心跳与正文区分处理。

---

## 四、研报复盘（需登录）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/valuation/summary` | 复盘汇总（模型对比 / 评分分桶 / 观察进度） |

---

## 五、自选与告警（需登录）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/watchlist` | 自选列表 |
| POST | `/api/watchlist/add` | 添加自选 |
| POST | `/api/watchlist/update` | 更新分组/备注/成本/数量 |
| POST | `/api/watchlist/delete` | 删除自选 |
| GET | `/api/alerts?ts_code=` | 告警规则列表 |
| POST | `/api/alerts/add` | 新增告警 |
| POST | `/api/alerts/toggle` | 启用/停用 |
| POST | `/api/alerts/delete` | 删除 |
| GET | `/api/alerts/unread` | 未读触发数 |

### 告警指标（`metric`）

| 值 | 含义 | 单位 |
|---|---|---|
| `val_low` | 跌破我的研报合理价 | **无需填阈值**，自动取研报合理市值下限 |
| `total_mv` | 总市值 | 亿元 |
| `price` | 收盘价 | 元 |
| `pct_chg` | 涨跌幅 | % |
| `pe_ttm` | 市盈率 TTM | 倍 |
| `pb` | 市净率 | 倍 |
| `pb_y5` | PB 近五年分位 | % |
| `disclosure` | 财报披露 | 提前天数 |

⚠️ `val_low` 的判定语义固定为「跌破」：当前总市值 ≤ 研报合理市值下限。若该股未做过研报，规则不会触发（宁可不提醒，也不编造阈值）。

---

## 六、个人中心（需登录）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/profile` | 个人中心 |
| GET | `/api/profile/portfolio` | 持仓盈亏 |
| GET | `/api/profile/orders` | 订单记录 |
| POST | `/api/redeem` | 兑换码核销 |
| POST | `/api/invite/bind` | 绑定邀请关系 |

---

## 七、后台管理（需管理员）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin` | 仪表盘 |
| `/admin/users` | 用户管理 |
| `/admin/settings` | 站点设置（含 AI 模型配置） |
| `/admin/valuation` | 全站研报回测台账 |
| `/admin/records` | 研报记录 |
| `/admin/logs` | 系统日志 |
| `/admin/redeem` | 兑换码管理 |
| `/admin/feedback` | 用户反馈 |

---

## 配额规则

深度分析采用三通道计数，剩余额度 = 每日额度 + 月度体验额度 + 赠送额度。

| 通道 | 说明 |
|---|---|
| `daily` | 每日固定额度，按自然日重置 |
| `monthly` | 月度体验额度，每周期重置 |
| `bonus` | 兑换码/活动赠送，一次性 |

⚠️ 报告生成失败（模型故障、生成中断）时**退还对应额度** —— 用户没拿到完整服务就不该扣次数。

---

## 速率限制

| 接口类别 | 限制 |
|---|---|
| 股票搜索 | 游客 30 次/分钟（按 IP） |
| 个股公开数据 | 游客 60 次/分钟（按 IP），登录用户不限 |
| 短信验证码 | 同号码 60 秒 1 次，单日 10 次 |
| AI 分析 | 由配额系统控制 + per-user 并发锁 |
