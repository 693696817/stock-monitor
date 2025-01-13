from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import tushare as ts
from app.config import Config

# 确保必要的目录和文件存在
Config.ensure_directories()

# 创建FastAPI实例
app = FastAPI()

# 设置tushare token
ts.set_token(Config.TUSHARE_TOKEN)
pro = ts.pro_api()

# Mount static files
app.mount("/static", StaticFiles(directory=Config.STATIC_DIR), name="static")

# Set up templates
templates = Jinja2Templates(directory=Config.TEMPLATES_DIR)

# 导入路由
from app.api import stock_routes
app.include_router(stock_routes.router) 