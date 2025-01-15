import os

# 基础配置
class Config:
    # 项目根目录
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Tushare API配置
    TUSHARE_TOKEN = 'your_tushare_token_here'
    
    # 配置文件路径
    CONFIG_FILE = os.path.join(BASE_DIR, "config.json") 