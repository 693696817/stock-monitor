import uvicorn
from app import app

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,      # 修改为8000端口
        reload=True,    # 启用热重载
        log_level="debug",  # 设置日志级别为debug
        workers=1       # 开发模式使用单个worker
    ) 