import os
from pathlib import Path

# ============================================================
#  ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (если есть .env рядом)
# ============================================================
try:
    from dotenv import load_dotenv
    from core.paths import get_env_path
    
    env_path = get_env_path()
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[Config] ✓ .env загружен: {env_path}")
    else:
        print(f"[Config] ⚠ .env не найден: {env_path}")
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
from core.paths import get_background_gif_path
BACKGROUND_GIF_PATH = str(get_background_gif_path())

BACKGROUND_OVERLAY_ALPHA = 180   # 0-255: прозрачность затемнения поверх GIF


PROXY_SERVER_URL = os.getenv(
    "PROXY_SERVER_URL",
    "https://78.17.47.74:8443"
)
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")
PROXY_VERIFY_SSL = os.getenv("PROXY_VERIFY_SSL", "false").lower() == "true"
PROXY_CERT_PATH = os.getenv("PROXY_CERT_PATH", "")

# ============================================================
#  ОТЛАДКА
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"