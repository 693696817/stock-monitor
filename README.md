# 价值投资盯盘系统

一个基于 Python FastAPI 开发的智能股票分析与监控平台。

## 功能特点

- 实时股票数据监控
- AI 智能分析
- 财务指标分析
- 价值投资建议
- 股东信息查询
- 指数行情展示

## 技术栈

- 后端：FastAPI + Python
- 前端：Bootstrap 5 + ECharts
- 数据源：Tushare API
- 部署：Uvicorn

## 安装使用

1. 克隆项目
```bash
git clone https://github.com/你的用户名/stock-monitor.git
cd stock-monitor
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置
- 复制 `config.json.example` 为 `config.json`
- 在 `config.json` 中配置你的 Tushare Token

4. 运行
```bash
python run.py
```

5. 访问
打开浏览器访问 `http://localhost:8000`

## 配置说明

主要配置项在 `app/config.py` 中：
- TUSHARE_TOKEN：Tushare API Token
- 其他配置项...

## 开发说明

- 遵循 PEP 8 编码规范
- 使用 Python 3.8 或以上版本
- 保持代码简洁清晰

## 贡献指南

欢迎提交 Issue 和 Pull Request

## 许可证

MIT License 