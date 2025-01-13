import os

# 基础配置
class Config:
    # 项目根目录
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Tushare API配置
    TUSHARE_TOKEN = '90f8a141125e1decb952cd49032b7b8409a2d7fa370745f6c9f45c96'
    
    # 配置文件路径
    CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
    
    # 模板目录
    TEMPLATES_DIR = os.path.join(BASE_DIR, "app", "templates")
    
    # 静态文件目录
    STATIC_DIR = os.path.join(BASE_DIR, "app", "static")
    
    # 确保目录存在
    @classmethod
    def ensure_directories(cls):
        os.makedirs(cls.STATIC_DIR, exist_ok=True)
        os.makedirs(cls.TEMPLATES_DIR, exist_ok=True)
        
        # 确保配置文件存在
        if not os.path.exists(cls.CONFIG_FILE):
            with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.write('{"watchlist": {}}') 