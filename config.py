import os
from pathlib import Path

# ============================================================
#  ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (если есть .env рядом)
# ============================================================
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass 


SMARTSHELL_GRAPHQL_URL = "https://billing.smartshell.gg/api/graphql"

# Маппинг: Telegram-аккаунт → Название точки
POINT_ACCOUNTS = {
    "@cybermg_russkaya": "Русская",
    "@cybermg_lugovaya": "Трамвайная",
    "@cybermg_bam": "Ульяновская",
    "@cybermg_tihaya": "Сахалинская",
    "@cybermg_centr": "Светланская",
    "@cybermg_kalinina": "Калинина",
}

SMARTSHELL_WAREHOUSE_IDS = {
    "Русская": 1598,
    "Сахалинская": 3241,
    "Трамвайная": 2610,
    "Светланская": 7879,
    "Ульяновская": 4532,
    "Калинина": 10178,
}

# ============================================================
#  ТОЧКИ ПРОДАЖ (удобный алиас для UI)
# ============================================================
POINTS = SMARTSHELL_WAREHOUSE_IDS


# ============================================================
#  НАСТРОЙКИ ПРИЛОЖЕНИЯ
# ============================================================
MAX_CART_ITEMS = 50              # Макс. количество товаров в корзине
RATE_LIMIT_DELAY = 0.05          # Задержка между запросами (сек)
SEARCH_DEBOUNCE_MS = 300         # Задержка поиска (debounce)


# ============================================================
#  ФОНОВАЯ АНИМАЦИЯ
# ============================================================
BACKGROUND_GIF_PATH = "background.gif"
BACKGROUND_OVERLAY_ALPHA = 180   # 0-255: прозрачность затемнения поверх GIF


PROXY_SERVER_URL = os.getenv(
    "PROXY_SERVER_URL",
    "https://78.17.47.74:8443"
)
API_SECRET_KEY = "aB3xk9mp2nQ5rT781jdqIasid109AA"
PROXY_VERIFY_SSL = os.getenv("PROXY_VERIFY_SSL", "false").lower() == "true"
PROXY_CERT_PATH = os.getenv("PROXY_CERT_PATH", "")

# ============================================================
#  ОТЛАДКА
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"