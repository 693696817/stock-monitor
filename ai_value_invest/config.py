import os
import secrets
from dotenv import load_dotenv

load_dotenv()

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
if not TUSHARE_TOKEN:
    print("⚠️ 警告: 未配置 TUSHARE_TOKEN，数据接口将不可用，请在 .env 中设置。")

VOLC_API_KEY = os.getenv("VOLC_API_KEY", "")
VOLC_BASE_URL = os.getenv("VOLC_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
VOLC_MODEL_ID = os.getenv("VOLC_MODEL_ID", "")
if not VOLC_API_KEY or not VOLC_MODEL_ID:
    print("⚠️ 警告: 未配置 VOLC_API_KEY / VOLC_MODEL_ID，AI 分析接口将不可用，请在 .env 中设置。")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(_BASE_DIR, "pdfs")
os.makedirs(PDF_DIR, exist_ok=True)

SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
if not os.getenv("SESSION_SECRET"):
    print("⚠️ 警告: 未配置 SESSION_SECRET，已使用临时随机密钥（进程重启后会话失效），建议写入 .env。")

DB_ENGINE = os.getenv("DB_ENGINE", "mysql").lower()
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "aistock")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "aistock")
MYSQL_CHARSET = os.getenv("MYSQL_CHARSET", "utf8mb4")

DATA_SOURCE = os.getenv("DATA_SOURCE", "proxy").lower()
PROXY_PROVIDER = os.getenv("PROXY_PROVIDER", "promoax").lower()
PROMOAX_BASE_URL = os.getenv("PROMOAX_BASE_URL", "https://pcd.mobcvb.cn/tushare/pro")
PROMOAX_API_KEY = os.getenv("PROMOAX_API_KEY", "")
DATAHUB_BASE_URL = os.getenv("DATAHUB_BASE_URL", "http://datahubco.com/app-api/openapi/v1/tushare")
DATAHUB_API_KEY = os.getenv("DATAHUB_API_KEY", "")
DATAHUB_NEWS_ENABLED = os.getenv("DATAHUB_NEWS_ENABLED", "false").lower() in ("1", "true", "yes", "on")

LIXINGER_TOKEN = os.getenv("LIXINGER_TOKEN", "")

FUYAO_API_KEY = os.getenv("FUYAO_API_KEY", "")
FUYAO_BASE_URL = os.getenv("FUYAO_BASE_URL", "https://fuyao.aicubes.cn").rstrip("/")
FUYAO_TIMEOUT = int(os.getenv("FUYAO_TIMEOUT", "20"))

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

SMS_PROVIDER = os.getenv("SMS_PROVIDER", "spug")
SPUG_SMS_TEMPLATE_CODE = os.getenv("SPUG_SMS_TEMPLATE_CODE", "")
SMS_ENABLED = os.getenv("SMS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
if SMS_ENABLED and not SPUG_SMS_TEMPLATE_CODE:
    print("⚠️ 警告: 未配置 SPUG_SMS_TEMPLATE_CODE，短信验证码将不可用，请在 .env 中设置。")
