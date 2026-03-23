import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

PORT = int(os.getenv('PORT', 3000))
APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://127.0.0.1:3000')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_ALLOWED_USER_IDS = [
    uid.strip() for uid in os.getenv('TELEGRAM_ALLOWED_USER_IDS', '').split(',') if uid.strip()
]
DATABASE_PATH = os.getenv('DATABASE_PATH', 'data/mailbox-py.db')
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '')

# 管理员固定 token，用于 /import 导入页面
ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', '')

# 邮件访问链接有效期（秒），默认 1 小时
ACCESS_TOKEN_TTL = int(os.getenv('ACCESS_TOKEN_TTL', 3600))
