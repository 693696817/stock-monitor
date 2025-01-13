import os
import json

# 基础配置
class Config:
    # 项目根目录
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 配置文件路径
    CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
    
    # 模板目录
    TEMPLATES_DIR = os.path.join(BASE_DIR, "app", "templates")
    
    # 静态文件目录
    STATIC_DIR = os.path.join(BASE_DIR, "app", "static")
    
    # API配置
    @classmethod
    def load_config(cls):
        if os.path.exists(cls.CONFIG_FILE):
            with open(cls.CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"watchlist": {}}
    
    @classmethod
    def get_tushare_token(cls):
        config = cls.load_config()
        return config.get('tushare_token')
    
    @classmethod
    def get_ai_api_key(cls):
        config = cls.load_config()
        return config.get('ai_api_key')
    
    @classmethod
    def get_ai_model_id(cls):
        config = cls.load_config()
        return config.get('ai_model_id')
    
    # 确保目录存在
    @classmethod
    def ensure_directories(cls):
        os.makedirs(cls.STATIC_DIR, exist_ok=True)
        os.makedirs(cls.TEMPLATES_DIR, exist_ok=True)
        
        # 确保配置文件存在
        if not os.path.exists(cls.CONFIG_FILE):
            with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.write('{"watchlist": {}}') 