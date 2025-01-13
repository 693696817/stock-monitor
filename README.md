# 价值投资盯盘系统

一个专注于中国 A 股市场的智能股票分析与监控平台，基于 Python FastAPI 开发，集成实时行情监控、AI 智能分析和价值投资建议等功能，助力投资者进行理性的价值投资决策。

## 功能特点

### 1. A股实时监控
- 支持所有 A 股上市公司的实时监控
- 沪深两市实时价格和涨跌幅更新
- 自定义市值目标区间预警
- 个股交易状态实时提示

### 2. AI 智能分析
- 基于中国市场特点的智能投资建议
- A股市场合理价格区间估算
- 结合中国经济环境的目标市值评估
- 多维度分析报告：
  - A股市场估值分析
  - 中国特色财务健康状况评估
  - 行业对标成长潜力评估
  - 系统性风险评估

### 3. A股财务指标分析
- 估值指标：PE（市盈率）、PB（市净率）、PS（市销率）等
- 盈利能力：ROE（净资产收益率）、毛利率、净利率
- 成长能力：营收增长、利润增长、研发投入
- 运营效率：资产周转率、存货周转率等
- 偿债能力：资产负债率、流动比率等
- 现金流指标：经营现金流、自由现金流等

### 4. 中国市场行情
- 上证指数、深证成指、创业板指等主要指数实时行情
- 专业K线图技术分析
- A股市场涨跌分布分析
- 行业板块轮动分析

### 5. 上市公司详情
- 工商登记信息
- 十大股东持股变动
- A股特色财务报表分析
- 公司公告与重大事项
- 行业地位分析

## 技术架构

### 后端技术栈
- Web框架：FastAPI
- 数据处理：Pandas
- A股数据源：Tushare API（提供专业的 A 股数据）
- 服务器：Uvicorn
- 数据存储：JSON文件

### 前端技术栈
- 框架：Bootstrap 5
- 图表：ECharts
- 交互：JavaScript
- 样式：CSS3

### 主要模块
```
项目结构
├── app/
│   ├── __init__.py
│   ├── api/
│   │   └── stock_routes.py    # API路由
│   ├── models/
│   │   └── stock.py          # 数据模型
│   ├── services/
│   │   ├── stock_service.py  # 股票服务
│   │   └── ai_analysis_service.py  # AI分析服务
│   ├── templates/
│   │   ├── index.html       # 主页面
│   │   └── market.html      # 市场页面
│   └── config.py            # 配置文件
├── run.py                   # 启动文件
└── requirements.txt         # 依赖包
```

## 安装部署

### 环境要求
- Python 3.8+
- pip 包管理器
- 网络连接（访问 Tushare API）

### 安装步骤

1. 克隆项目
```bash
git clone https://github.com/693696817/stock-monitor.git
cd stock-monitor
```

2. 创建虚拟环境（推荐）
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. 安装依赖
```bash
pip install -r requirements.txt
```

4. 配置
- 复制 `config.json.example` 为 `config.json`
- 在 `config.json` 中配置你的 Tushare Token
```json
{
    "watchlist": {},
    "tushare_token": "your_tushare_token_here"
}
```

5. 运行
```bash
python run.py
```

6. 访问
- 打开浏览器访问 `http://localhost:8000`
- 默认端口为 8000，可在 `run.py` 中修改

## 使用指南

### 添加监控股票
1. 在主页面顶部输入 A 股股票代码（6位数字，如：000001）
2. 可选择设置目标市值区间
3. 点击"添加"按钮开始监控

### 查看股票详情
1. 点击股票名称进入详情页
2. 查看完整的 A 股特色财务指标
3. 获取针对中国市场的 AI 投资建议

### 指数行情
- 实时展示沪深主要指数行情
- 提供大盘趋势分析
- 行业板块表现对比

### 数据更新频率
- A股交易时段（9:30-11:30, 13:00-15:00）实时更新
- 盘后自动更新财务数据
- 可手动强制刷新最新数据

## 开发指南

### 代码规范
- 遵循 PEP 8 编码规范
- 使用类型注解
- 保持代码简洁清晰

### 目录结构说明
- `api/`: API路由和接口定义
- `models/`: 数据模型和结构定义
- `services/`: 业务逻辑和服务实现
- `templates/`: 前端页面模板

### 扩展开发
1. 添加新的数据源
   - 在 `services` 中添加新的服务类
   - 实现数据获取和处理方法

2. 扩展AI分析
   - 修改 `ai_analysis_service.py`
   - 添加新的分析维度和方法

3. 自定义UI
   - 修改 `templates` 中的HTML文件
   - 更新样式和交互逻辑

## 维护说明

### 数据更新
- A股交易时段实时行情更新
- 每日收盘后自动更新财务数据
- 定期同步公司公告信息
- 可配置更新频率

### 错误处理
- 完善的错误提示
- 异常捕获和处理
- 日志记录

## 贡献指南

欢迎提交 Issue 和 Pull Request：
1. Fork 本仓库
2. 创建特性分支
3. 提交变更
4. 发起 Pull Request

## 许可证

MIT License

## 联系方式

- 作者：ZYJ
- 邮箱：693696817@qq.com

## 更新日志

### v1.0.0 (2024-03)
- 支持全部 A 股上市公司监控
- 实现核心功能：实时行情、AI 分析、财务分析
- 完成基础框架搭建
- 优化 A 股特色分析逻辑 