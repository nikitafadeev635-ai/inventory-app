"""
QFact API Server — прокси для CyberMG Inventory App.
Защищает мастер-кредами SmartShell, предоставляет API для клиентов.
Все операции логируются в audit_log с детальной информацией о товарах.

Оптимизация: название товара передаётся клиентом (из кеша),
сервер не делает лишних запросов к SmartShell для получения title.

v1.3.0 — Пакетная обработка:
- Один HTTP-запрос к SmartShell с множественными GraphQL мутациями
- Автоматическое разбиение на батчи по 25 товаров
- Экономия rate limit (1 запрос вместо N)

v1.6.0 — Безопасность:
- IP-whitelist + Telegram-алерты при попытках взлома
- Rate limiting на /api/auth/* (5 попыток за 15 минут)
- bcrypt хеширование паролей сотрудников

Временно отключены (для безопасности):
- Поиск клиентов по телефону
- Корректировка депозита
"""
import os
import io
import json
import time
import logging
import asyncio
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
import bcrypt
import jwt
import httpx
import pymysql
import uvicorn
import ipaddress
from collections import defaultdict

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Загружаем конфиг
load_dotenv()

# ============================================================
#  🆕 ГЛОБАЛЬНЫЙ СЧЁТЧИК запросов к SmartShell
# ============================================================
_smartshell_request_counter = 0

# ============================================================
#  ЛОГИРОВАНИЕ
# ============================================================
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "server.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("qfact")

# ============================================================
#  КОНФИГ
# ============================================================
SS_MASTER_LOGIN = os.getenv("SS_MASTER_LOGIN")
SS_MASTER_PASSWORD = os.getenv("SS_MASTER_PASSWORD")
SS_GRAPHQL_URL = os.getenv("SMARTSHELL_GRAPHQL_URL", "https://billing.smartshell.gg/api/graphql")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "12"))

WAREHOUSE_IDS = {
    "Русская": int(os.getenv("WAREHOUSE_RUSSKAYA", "1598")),
    "Сахалинская": int(os.getenv("WAREHOUSE_SAHALINSKAYA", "3241")),
    "Трамвайная": int(os.getenv("WAREHOUSE_TRAMVAYNAYA", "2610")),
    "Светланская": int(os.getenv("WAREHOUSE_SVETLAYA", "7879")),
    "Ульяновская": int(os.getenv("WAREHOUSE_ULYANOVSKAYA", "4532")),
    "Калинина": int(os.getenv("WAREHOUSE_KALININA", "10178")),
}

# ============================================================
#  TELEGRAM УВЕДОМЛЕНИЯ
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 🆕 v1.4.0: Mapping точка → topic_id для рассылки отчётов по филиалам
TELEGRAM_TOPIC_MAP = {
    "Русская": int(os.getenv("TELEGRAM_TOPIC_RUSSKAYA", "4")),
    "Сахалинская": int(os.getenv("TELEGRAM_TOPIC_SAHALINSKAYA", "9")),
    "Трамвайная": int(os.getenv("TELEGRAM_TOPIC_TRAMVAYNAYA", "7")),
    "Светланская": int(os.getenv("TELEGRAM_TOPIC_SVETLAYA", "11213")),
    "Ульяновская": int(os.getenv("TELEGRAM_TOPIC_ULYANOVSKAYA", "10")),
    "Калинина": int(os.getenv("TELEGRAM_TOPIC_KALININA", "118019")),
}


async def send_telegram_alert(message: str):
    """Отправляет критические уведомления (crash-логи) в общий чат супергруппы."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[Telegram] ⚠ Не настроен бот или chat_id — пропуск")
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                logger.info("[Telegram] ✓ Уведомление отправлено")
            else:
                logger.error(f"[Telegram] ✗ HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"[Telegram] ✗ Ошибка отправки: {e}")


async def send_telegram_to_topic(point_name: str, message: str, parse_mode: str = "HTML") -> dict:
    """Отправляет сообщение в конкретный топик супергруппы."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[Telegram] ⚠ Не настроен бот или chat_id — пропуск")
        return {"success": False, "error": "bot/chat_id not configured"}
    
    topic_id = TELEGRAM_TOPIC_MAP.get(point_name)
    if not topic_id or topic_id <= 0:
        logger.warning(
            f"[Telegram] ⚠ Нет валидного topic_id для точки '{point_name}'"
        )
        return {"success": False, "error": f"no valid topic_id for '{point_name}'"}
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_thread_id": topic_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=payload)
            
            if r.status_code == 200:
                data = r.json()
                message_id = data.get("result", {}).get("message_id")
                logger.info(
                    f"[Telegram] ✓ Отчёт отправлен в топик '{point_name}' "
                    f"(topic_id={topic_id}, message_id={message_id})"
                )
                return {"success": True, "message_id": message_id, "error": None}
            
            error_text = r.text[:300]
            logger.error(
                f"[Telegram] ✗ HTTP {r.status_code} для точки '{point_name}': {error_text}"
            )
            
            if r.status_code == 400 and "message_thread_id" in error_text.lower():
                return {"success": False, "error": f"Invalid topic_id {topic_id}"}
            if r.status_code == 401:
                return {"success": False, "error": "Invalid bot token"}
            
            return {"success": False, "error": f"HTTP {r.status_code}"}
    
    except httpx.TimeoutException:
        logger.error(f"[Telegram] ✗ Таймаут отправки в топик {point_name}")
        return {"success": False, "error": "timeout"}
    except Exception as e:
        logger.error(f"[Telegram] ✗ Ошибка отправки в топик '{point_name}': {e}")
        return {"success": False, "error": str(e)}


# ============================================================
#  FASTAPI APP
# ============================================================
is_dev = os.getenv("DEBUG", "false").lower() == "true"

app = FastAPI(
    title="QFact API",
    version="1.6.0",
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
    openapi_url="/openapi.json" if is_dev else None,
)


# ============================================================
# 🔒 IP-WHITELIST: загрузка разрешённых IP
# ============================================================
ALLOWED_IPS_RAW = os.getenv("ALLOWED_IPS", "")
ADMIN_IPS_RAW = os.getenv("ADMIN_IPS", "")
ALERT_ON_BLOCKED_IP = os.getenv("ALERT_ON_BLOCKED_IP", "true").lower() == "true"

def _parse_ip_list(raw: str) -> list:
    """Парсит строку с IP/CIDR в список ip_network объектов."""
    networks = []
    for ip_range in raw.split(","):
        ip_range = ip_range.strip()
        if not ip_range:
            continue
        try:
            if "/" in ip_range:
                networks.append(ipaddress.ip_network(ip_range, strict=False))
            else:
                networks.append(ipaddress.ip_network(f"{ip_range}/32", strict=False))
        except Exception as e:
            logger.warning(f"[Security] ⚠ Неверный IP/CIDR: {ip_range}: {e}")
    return networks

ALLOWED_NETWORKS = _parse_ip_list(ALLOWED_IPS_RAW)
ADMIN_NETWORKS = _parse_ip_list(ADMIN_IPS_RAW)

if ALLOWED_NETWORKS:
    logger.info(f"[Security] ✅ IP-whitelist активен: {len(ALLOWED_NETWORKS)} адресов")
    for net in ALLOWED_NETWORKS:
        logger.info(f"[Security]   → {net}")
else:
    logger.warning("[Security] ⚠ IP-whitelist отключён (ALLOWED_IPS пустой)")

# Счётчик заблокированных IP для rate limiting алертов
_blocked_ip_tracker = defaultdict(list)


# ============================================================
# 🔒 RATE LIMITING: защита от брутфорса паролей
# ============================================================
RATE_LIMIT_MAX_ATTEMPTS = int(os.getenv("RATE_LIMIT_MAX_ATTEMPTS", "5"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "900"))       # 15 минут
RATE_LIMIT_LOCKOUT = int(os.getenv("RATE_LIMIT_LOCKOUT", "900"))      # 15 минут

# Счётчики: {(ip, faname): [timestamp1, timestamp2, ...]}
_login_attempts = defaultdict(list)
_blocked_users = {}  # {(ip, faname): timestamp_разблокировки}


def _check_rate_limit(client_ip: str, faname: str) -> tuple:
    """
    Проверяет не превышен ли лимит попыток.
    Returns: (is_allowed: bool, seconds_until_unlock: int)
    """
    now = time.time()
    key = (client_ip, faname)
    
    # 1. Проверка жёсткой блокировки
    if key in _blocked_users:
        unlock_at = _blocked_users[key]
        if now < unlock_at:
            return False, int(unlock_at - now)
        else:
            # Срок блокировки истёк — очищаем
            del _blocked_users[key]
            if key in _login_attempts:
                del _login_attempts[key]
    
    # 2. Очистка старых попыток (старше RATE_LIMIT_WINDOW)
    if key in _login_attempts:
        _login_attempts[key] = [
            t for t in _login_attempts[key]
            if now - t < RATE_LIMIT_WINDOW
        ]
    
    # 3. Проверка количества попыток
    attempts_count = len(_login_attempts.get(key, []))
    if attempts_count >= RATE_LIMIT_MAX_ATTEMPTS:
        _blocked_users[key] = now + RATE_LIMIT_LOCKOUT
        return False, RATE_LIMIT_LOCKOUT
    
    return True, 0


def _register_failed_attempt(client_ip: str, faname: str):
    """Регистрирует неудачную попытку входа."""
    key = (client_ip, faname)
    _login_attempts[key].append(time.time())
    attempts_count = len(_login_attempts[key])
    
    logger.warning(
        f"[Security] ✗ Неудачная попытка #{attempts_count}/{RATE_LIMIT_MAX_ATTEMPTS}: "
        f"{faname} @ {client_ip}"
    )
    
    if attempts_count >= RATE_LIMIT_MAX_ATTEMPTS:
        _blocked_users[key] = time.time() + RATE_LIMIT_LOCKOUT
        logger.error(
            f"[Security] 🚨 БЛОКИРОВКА: {faname} @ {client_ip} "
            f"на {RATE_LIMIT_LOCKOUT // 60} минут"
        )


def _reset_attempts(client_ip: str, faname: str):
    """Сбрасывает счётчик после успешного входа."""
    key = (client_ip, faname)
    _login_attempts.pop(key, None)
    _blocked_users.pop(key, None)


async def _send_rate_limit_alert(ip: str, faname: str, wait_seconds: int):
    """Отправляет Telegram-алерт о превышении попыток входа."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    message = (
        f"⚠️ <b>ПОДОЗРИТЕЛЬНАЯ АКТИВНОСТЬ</b>\n\n"
        f"👤 <b>Пользователь:</b> {faname}\n"
        f"🌐 <b>IP:</b> <code>{ip}</code>\n"
        f"🔒 <b>Заблокирован на:</b> {wait_seconds // 60} мин\n"
        f"🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        f"<i>Превышен лимит попыток входа "
        f"({RATE_LIMIT_MAX_ATTEMPTS} за {RATE_LIMIT_WINDOW // 60} мин)</i>"
    )
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                }
            )
            logger.info(f"[Security] 📨 Rate limit алерт отправлен для {faname} @ {ip}")
    except Exception as e:
        logger.error(f"[Security] ✗ Ошибка отправки rate limit алерта: {e}")


# ============================================================
#  API SECRET KEY — защита от несанкционированного доступа
# ============================================================
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")


# ============================================================
# 🔒 MIDDLEWARE: IP-whitelist + API-Key защита
# ============================================================
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """
    Трёхуровневая защита:
    1. IP-whitelist (разрешены только IP филиалов)
    2. API-Key (проверка секрета клиента)
    3. JWT (проверка авторизации пользователя — в отдельных эндпоинтах)
    """
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path
    
    # === Уровень 0: Healthcheck открыт всем (для мониторинга) ===
    if path == "/":
        return await call_next(request)

    if path.startswith("/api/debug/"):
        logger.info(f"[Debug] Диагностика: {client_ip} → {path}")
        return await call_next(request)
    
    # === Уровень 1: Проверка IP ===
    if ALLOWED_NETWORKS or ADMIN_NETWORKS:
        try:
            client_addr = ipaddress.ip_address(client_ip)
            is_allowed = any(client_addr in net for net in ALLOWED_NETWORKS)
            is_admin = any(client_addr in net for net in ADMIN_NETWORKS)
        except ValueError:
            is_allowed = False
            is_admin = False
            logger.warning(f"[Security] ⚠ Неверный IP формат: {client_ip}")
        
        if not (is_allowed or is_admin):
            logger.warning(
                f"🚫 [Security] BLOCKED: {client_ip} → {request.method} {path} "
                f"(IP not in whitelist)"
            )
            
            if ALERT_ON_BLOCKED_IP:
                await _send_blocked_ip_alert(client_ip, path, request.method)
            
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Access denied: your IP is not allowed",
                    "ip": client_ip,
                }
            )
        
        if is_admin:
            logger.debug(f"[Security] 👑 Admin access: {client_ip} → {path}")
    
    # === Уровень 2: Проверка API-Key ===
    if API_SECRET_KEY:
        api_key = request.headers.get("X-API-Key")
        if api_key != API_SECRET_KEY:
            logger.warning(
                f"🚫 [Security] Invalid API key from {client_ip} → {path}"
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"}
            )
    
    # Всё ок — пропускаем запрос дальше
    return await call_next(request)


async def _send_blocked_ip_alert(ip: str, path: str, method: str):
    """Отправляет алерт в Telegram о попытке доступа с неразрешённого IP."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    now = time.time()
    _blocked_ip_tracker[ip] = [
        t for t in _blocked_ip_tracker[ip] if now - t < 300
    ]
    
    if _blocked_ip_tracker[ip]:
        return
    
    _blocked_ip_tracker[ip].append(now)
    
    message = (
        f"🚨 <b>ПОПЫТКА ВЗЛОМА!</b>\n\n"
        f"🌐 <b>IP:</b> <code>{ip}</code>\n"
        f"📍 <b>Запрос:</b> {method} {path}\n"
        f"🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        f"<i>IP не в белом списке. Если это вы — добавьте IP в .env "
        f"(переменная ALLOWED_IPS или ADMIN_IPS)</i>"
    )
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                }
            )
            logger.info(f"[Security] 📨 Telegram-алерт отправлен для IP {ip}")
    except Exception as e:
        logger.error(f"[Security] ✗ Ошибка отправки алерта: {e}")


security = HTTPBearer()
_ss_token_cache = {}
_SS_TOKEN_TTL = 3600  # 1 час


# ============================================================
#  МОДЕЛИ ЗАПРОСОВ
# ============================================================
class LoginRequest(BaseModel):
    faname: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=255)
    point_name: str


class NormalizeSingleRequest(BaseModel):
    product_id: int
    product_title: str = Field(default="Неизвестный товар", max_length=500)
    delta: int
    reason: str
    type: str
    session_info: dict
    giver: str
    receiver: str
    point_name: str


class NormalizeOperation(BaseModel):
    product_id: int
    product_title: str = Field(default="Неизвестный товар", max_length=500)
    delta: int
    reason: str
    type: str


class NormalizeRequest(BaseModel):
    operations: list[NormalizeOperation]
    session_info: dict
    giver: str
    receiver: str
    point_name: str


class EmployeeSearchRequest(BaseModel):
    query: str = Field(default="", max_length=100)


# ============================================================
#  РАЗРЕШЁННЫЕ ПРИЧИНЫ
# ============================================================
ALLOWED_REASONS_LESS = {
    "Товар украден",
    "Пропал на смене (ищите:))",
    "Съел",
    "Не прошла оплата, нужно списать",
}
ALLOWED_REASONS_MORE = {
    "Не знаю откуда плюс - недовнёс бот",
    "Не знаю откуда плюс - недовнёс шелл",
    "Не знаю откуда плюс - может я даун",
}


# ============================================================
#  БАЗА ДАННЫХ
# ============================================================
def get_db_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", "3306")),
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
        connect_timeout=5,
    )


def verify_employee(faname: str, password: str) -> bool:
    """Проверяет пароль сотрудника через bcrypt."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT password FROM employees WHERE faname = %s", (faname,))
            row = cur.fetchone()
            if not row:
                return False
            
            stored_password = row["password"]
            
            if (stored_password.startswith('$2b$') or 
                stored_password.startswith('$2a$') or 
                stored_password.startswith('$2y$')):
                try:
                    return bcrypt.checkpw(
                        password.encode('utf-8'),
                        stored_password.encode('utf-8')
                    )
                except Exception as e:
                    logger.error(f"bcrypt error for {faname}: {e}")
                    return False
            else:
                logger.warning(f"⚠️ {faname} использует plaintext пароль!")
                return stored_password == password
    except Exception as e:
        logger.error(f"DB error: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def log_audit(data: dict):
    """Записывает аудит-лог в БД."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            details_json = None
            if data.get("details"):
                details_json = json.dumps(
                    data["details"],
                    ensure_ascii=False,
                    default=str
                )
            
            cur.execute(
                """INSERT INTO audit_log 
                   (timestamp, faname, point_name, warehouse_id, operation_type, 
                    product_count, ip_address, user_agent, session_info, details)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    datetime.now(),
                    data.get("faname"),
                    data.get("point_name"),
                    data.get("warehouse_id"),
                    data.get("operation_type"),
                    data.get("product_count"),
                    data.get("ip"),
                    data.get("user_agent"),
                    str(data.get("session_info", ""))[:1000],
                    details_json,
                ),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Audit log error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ============================================================
#  JWT
# ============================================================
def create_jwt_token(faname: str, point_name: str, warehouse_id: int) -> str:
    payload = {
        "faname": faname,
        "point_name": point_name,
        "warehouse_id": warehouse_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Токен истёк")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Недействительный токен")


# ============================================================
#  SMARTSHELL PROXY
# ============================================================
async def get_smartshell_token(warehouse_id: int) -> str:
    """Получает/кэширует токен SmartShell для склада."""
    now = time.time()
    cached = _ss_token_cache.get(warehouse_id)
    if cached and cached[1] > now:
        return cached[0]

    query = f"""
    mutation login {{
        login(input: {{
            login: "{SS_MASTER_LOGIN}"
            password: "{SS_MASTER_PASSWORD}"
            company_id: {warehouse_id}
        }}) {{ access_token }}
    }}
    """

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            SS_GRAPHQL_URL,
            json={"operationName": "login", "query": query, "variables": {}},
        )
        if r.status_code != 200:
            raise HTTPException(500, f"SmartShell login failed: {r.status_code}")

        data = r.json()
        if "errors" in data:
            raise HTTPException(500, f"SmartShell error: {data['errors']}")

        token = data["data"]["login"]["access_token"]
        _ss_token_cache[warehouse_id] = (token, now + _SS_TOKEN_TTL)
        logger.info(f"SmartShell token refreshed for warehouse {warehouse_id}")
        return token


async def fetch_goods_from_ss(warehouse_id: int, search: str = "") -> list:
    """Получает товары из SmartShell."""
    token = await get_smartshell_token(warehouse_id)

    query = """query goods($input: GoodsInput) {
        goods(input: $input) {
            id title cost wholesale_cost amount eans vat
            category { id company_id title }
            show_in_shell image in_combo highlighted
        }
    }"""

    variables = {"input": {}}
    if search:
        variables["input"]["title_search"] = search

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            SS_GRAPHQL_URL,
            json={"operationName": "goods", "query": query, "variables": variables},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get("data", {}).get("goods", [])


# ============================================================
#  🚀 ПАКЕТНОЕ ИЗМЕНЕНИЕ КОЛИЧЕСТВА В SMARTSHELL
# ============================================================
async def change_quantity_ss(
    warehouse_id: int, 
    items: list, 
    operation: str, 
    chunk_size: int = 25
) -> dict:
    """Изменяет количество товаров в SmartShell ОДНИМ HTTP-запросом."""
    global _smartshell_request_counter
    
    if not items:
        return {
            "success": True, "total_items": 0, "successful_items": 0,
            "failed_items": 0, "total_batches": 0, "successful_batches": 0,
            "failed_batches": 0, "errors": [],
            "ss_request_number": 0, "ss_request_count": 0,
        }
    
    token = await get_smartshell_token(warehouse_id)
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    total_batches = len(chunks)
    
    mutation_parts = []
    variables = {}
    variable_declarations = []
    
    for idx, chunk in enumerate(chunks, start=1):
        batch_name = f"batch{idx}"
        var_name = f"input{idx}"
        mutation_parts.append(f"{batch_name}: changeGoodsQuantity(input: ${var_name})")
        variable_declarations.append(f"${var_name}: ChangeGoodsQuantityInput!")
        variables[var_name] = {"items": chunk, "operation": operation}
    
    mutation_body = "\n    ".join(mutation_parts)
    vars_declaration = ", ".join(variable_declarations)
    query = f"""mutation ({vars_declaration}) {{
    {mutation_body}
}}"""
    
    _smartshell_request_counter += 1
    current_request_number = _smartshell_request_counter
    
    logger.info(
        f"📡 [SS-REQUEST #{current_request_number}] "
        f"🚀 {operation}: {len(items)} товаров → "
        f"1 HTTP-запрос с {total_batches} мутациями внутри"
    )
    
    request_payload = {"query": query, "variables": variables}
    request_size = len(json.dumps(request_payload, ensure_ascii=False))
    logger.info(
        f"📦 [SS-REQUEST #{current_request_number}] "
        f"Размер: {request_size} байт ({request_size / 1024:.2f} KB)"
    )
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                SS_GRAPHQL_URL,
                json=request_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            
            logger.info(
                f"📨 [SS-REQUEST #{current_request_number}] "
                f"HTTP {r.status_code}, размер: {len(r.text)} байт"
            )
            
            if r.status_code != 200:
                logger.error(
                    f"✗ [SS-REQUEST #{current_request_number}] "
                    f"HTTP error: {r.status_code} — {r.text[:500]}"
                )
                return {
                    "success": False, "total_items": len(items),
                    "successful_items": 0, "failed_items": len(items),
                    "total_batches": total_batches, "successful_batches": 0,
                    "failed_batches": total_batches,
                    "errors": [{"type": "http_error", "http_status": r.status_code,
                               "message": r.text[:500]}],
                    "ss_request_number": current_request_number, "ss_request_count": 1,
                }
            
            data = r.json()
            
            if "errors" in data and "data" not in data:
                logger.error(f"✗ [SS-REQUEST #{current_request_number}] GraphQL error: {data['errors']}")
                return {
                    "success": False, "total_items": len(items),
                    "successful_items": 0, "failed_items": len(items),
                    "total_batches": total_batches, "successful_batches": 0,
                    "failed_batches": total_batches,
                    "errors": [{"type": "graphql_error", "errors": data["errors"]}],
                    "ss_request_number": current_request_number, "ss_request_count": 1,
                }
            
            successful_items = 0
            failed_items = 0
            successful_batches = 0
            failed_batches = 0
            errors = []
            
            response_data = data.get("data", {})
            global_errors = data.get("errors", [])
            
            for idx, chunk in enumerate(chunks, start=1):
                batch_name = f"batch{idx}"
                chunk_size_actual = len(chunk)
                
                batch_errors = [
                    err for err in global_errors
                    if err.get("path") and batch_name in str(err.get("path", []))
                ]
                
                batch_result = response_data.get(batch_name)
                
                if batch_errors:
                    failed_items += chunk_size_actual
                    failed_batches += 1
                    errors.append({
                        "batch": idx, "type": "batch_error",
                        "errors": batch_errors, "items_count": chunk_size_actual,
                        "item_ids": [item["id"] for item in chunk]
                    })
                    logger.error(
                        f"✗ [SS-REQUEST #{current_request_number}] "
                        f"{operation} batch {idx}/{total_batches} FAILED: {batch_errors}"
                    )
                elif batch_result is not None:
                    successful_items += chunk_size_actual
                    successful_batches += 1
                    logger.info(
                        f"✓ [SS-REQUEST #{current_request_number}] "
                        f"{operation} batch {idx}/{total_batches}: {chunk_size_actual} items"
                    )
                else:
                    failed_items += chunk_size_actual
                    failed_batches += 1
                    errors.append({
                        "batch": idx, "type": "unknown_result",
                        "items_count": chunk_size_actual,
                        "item_ids": [item["id"] for item in chunk]
                    })
                    logger.warning(
                        f"⚠ [SS-REQUEST #{current_request_number}] "
                        f"{operation} batch {idx}/{total_batches}: ambiguous result"
                    )
            
            logger.info(
                f"✅ [SS-REQUEST #{current_request_number}] ЗАВЕРШЁН: "
                f"{successful_items}/{len(items)} товаров успешно"
            )
            
            return {
                "success": len(errors) == 0,
                "total_items": len(items),
                "successful_items": successful_items,
                "failed_items": failed_items,
                "total_batches": total_batches,
                "successful_batches": successful_batches,
                "failed_batches": failed_batches,
                "errors": errors,
                "ss_request_number": current_request_number,
                "ss_request_count": 1,
            }
    
    except Exception as e:
        logger.error(f"✗ [SS-REQUEST #{current_request_number}] Exception: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False, "total_items": len(items),
            "successful_items": 0, "failed_items": len(items),
            "total_batches": total_batches, "successful_batches": 0,
            "failed_batches": total_batches,
            "errors": [{"type": "exception", "exception": str(e)}],
            "ss_request_number": current_request_number, "ss_request_count": 1,
        }


# ============================================================
#  РОУТЫ
# ============================================================
# ============================================================
# 🔬 ДИАГНОСТИКА: определение IP клиента
# ============================================================
@app.get("/api/debug/ip")
async def debug_ip(request: Request):
    """
    Возвращает все IP-заголовки и информацию о подключении.
    Используется для диагностики IP-whitelist.
    """
    # Все возможные источники IP
    headers_info = {}
    ip_headers = [
        "x-forwarded-for",
        "x-real-ip",
        "x-client-ip",
        "cf-connecting-ip",
        "x-cluster-client-ip",
        "forwarded",
        "true-client-ip",
        "x-appengine-user-ip",
    ]
    
    for header in ip_headers:
        value = request.headers.get(header)
        if value:
            headers_info[header] = value
    
    # Информация о подключении
    client_info = {
        "direct_ip": request.client.host if request.client else None,
        "port": request.client.port if request.client else None,
        "ip_headers": headers_info,
        "first_forwarded_ip": None,
        "server_time": datetime.now().isoformat(),
    }
    
    # Парсим X-Forwarded-For (первый IP = реальный клиент)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        client_info["first_forwarded_ip"] = first_ip
    
    # Проверяем в whitelist
    real_ip = client_info["first_forwarded_ip"] or client_info["direct_ip"]
    is_allowed = False
    is_admin = False
    matched_network = None
    
    if real_ip:
        try:
            client_addr = ipaddress.ip_address(real_ip)
            for net in ALLOWED_NETWORKS:
                if client_addr in net:
                    is_allowed = True
                    matched_network = str(net)
                    break
            for net in ADMIN_NETWORKS:
                if client_addr in net:
                    is_admin = True
                    matched_network = str(net)
                    break
        except Exception:
            pass
    
    client_info["whitelist_check"] = {
        "ip_being_checked": real_ip,
        "is_allowed": is_allowed,
        "is_admin": is_admin,
        "matched_network": matched_network,
        "allowed_networks": [str(n) for n in ALLOWED_NETWORKS],
        "admin_networks": [str(n) for n in ADMIN_NETWORKS],
    }
    
    logger.info(
        f"[Debug] IP request: direct={client_info['direct_ip']}, "
        f"forwarded={client_info['first_forwarded_ip']}, "
        f"allowed={is_allowed}, admin={is_admin}"
    )
    
    return client_info


@app.get("/api/debug/headers")
async def debug_headers(request: Request):
    """Возвращает все заголовки запроса (для полной диагностики)."""
    return {
        "headers": dict(request.headers),
        "client_host": request.client.host if request.client else None,
        "client_port": request.client.port if request.client else None,
        "url": str(request.url),
        "method": request.method,
    }

@app.get("/")
async def root():
    return {"status": "ok", "service": "QFact API", "version": "1.6.0"}


# ------------------------------------------------------------
#  Авторизация
# ------------------------------------------------------------
@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    # Определяем реальный IP
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    if req.point_name not in WAREHOUSE_IDS:
        raise HTTPException(400, f"Неизвестная точка: {req.point_name}")

    # 🆕 RATE LIMIT CHECK
    is_allowed, wait_seconds = _check_rate_limit(client_ip, req.faname)
    if not is_allowed:
        logger.warning(f"[Security] 🚫 Rate limit: {req.faname} @ {client_ip}")
        await _send_rate_limit_alert(client_ip, req.faname, wait_seconds)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много попыток. Подождите {wait_seconds // 60} мин",
            headers={"Retry-After": str(wait_seconds)}
        )

    if not verify_employee(req.faname, req.password):
        _register_failed_attempt(client_ip, req.faname)
        log_audit({
            "faname": req.faname,
            "point_name": req.point_name,
            "operation_type": "LOGIN_FAILED",
            "ip": client_ip,
            "user_agent": request.headers.get("user-agent", ""),
        })
        raise HTTPException(401, "Неверный логин или пароль")

    _reset_attempts(client_ip, req.faname)
    
    warehouse_id = WAREHOUSE_IDS[req.point_name]
    token = create_jwt_token(req.faname, req.point_name, warehouse_id)

    log_audit({
        "faname": req.faname,
        "point_name": req.point_name,
        "warehouse_id": warehouse_id,
        "operation_type": "LOGIN_SUCCESS",
        "ip": client_ip,
        "user_agent": request.headers.get("user-agent", ""),
    })

    logger.info(f"✓ Login: {req.faname} @ {req.point_name} from {client_ip}")
    return {"access_token": token, "warehouse_id": warehouse_id}


@app.post("/api/auth/verify_password")
async def verify_password(request: Request):
    """Проверяет пароль БЕЗ выдачи JWT (с rate limiting)."""
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    try:
        data = await request.json()
        faname = data.get("faname", "").strip()
        password = data.get("password", "")
        
        if not faname or not password:
            return {"verified": False, "error": "Не указан ФИО или пароль"}
        
        # 🆕 RATE LIMIT CHECK
        is_allowed, wait_seconds = _check_rate_limit(client_ip, faname)
        if not is_allowed:
            logger.warning(f"[Security] 🚫 Rate limit: {faname} @ {client_ip}")
            await _send_rate_limit_alert(client_ip, faname, wait_seconds)
            return JSONResponse(
                status_code=429,
                content={
                    "verified": False,
                    "error": f"Слишком много попыток. Подождите {wait_seconds // 60} мин",
                    "retry_after": wait_seconds,
                },
                headers={"Retry-After": str(wait_seconds)}
            )
        
        def db_query():
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT faname, password FROM employees WHERE faname = %s",
                        (faname,)
                    )
                    return cur.fetchone()
            finally:
                try:
                    conn.close()
                except:
                    pass
        
        loop = asyncio.get_event_loop()
        row = await loop.run_in_executor(None, db_query)
        
        if not row:
            _register_failed_attempt(client_ip, faname)
            return {"verified": False, "error": "Неверный пароль"}
        
        db_password = row["password"]
        is_valid = False
        
        if (db_password.startswith('$2b$') or 
            db_password.startswith('$2a$') or 
            db_password.startswith('$2y$')):
            try:
                is_valid = bcrypt.checkpw(
                    password.encode('utf-8'),
                    db_password.encode('utf-8')
                )
            except Exception as e:
                logger.error(f"[Auth] bcrypt error: {e}")
                is_valid = False
        else:
            is_valid = db_password == password
        
        if is_valid:
            _reset_attempts(client_ip, faname)
            logger.info(f"[Auth] ✓ Пароль верен: {faname} @ {client_ip}")
            return {"verified": True, "faname": row["faname"]}
        else:
            _register_failed_attempt(client_ip, faname)
            logger.warning(f"[Auth] ✗ Неверный пароль: {faname} @ {client_ip}")
            return {"verified": False, "error": "Неверный пароль"}
    
    except Exception as e:
        logger.error(f"[Auth] ✗ Ошибка: {e}")
        return {"verified": False, "error": str(e)}


# ------------------------------------------------------------
#  Список товаров
# ------------------------------------------------------------
@app.get("/api/goods/list")
async def get_goods(
    search: str = "",
    user: dict = Depends(get_current_user),
):
    goods = await fetch_goods_from_ss(user["warehouse_id"], search)
    return {"goods": goods, "count": len(goods)}


# ------------------------------------------------------------
#  🚀 ПАКЕТНАЯ НОРМАЛИЗАЦИЯ
# ------------------------------------------------------------
@app.post("/api/normalize")
async def normalize(
    req: NormalizeRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not req.operations:
        raise HTTPException(400, "Нет операций")

    for op in req.operations:
        if op.type == "DISPOSAL":
            if op.reason and op.reason not in ALLOWED_REASONS_LESS:
                raise HTTPException(400, f"Недопустимая причина: {op.reason}")
        elif op.type == "ADD":
            if op.reason and op.reason not in ALLOWED_REASONS_MORE:
                raise HTTPException(400, f"Недопустимая причина: {op.reason}")

    disposals = [op for op in req.operations if op.type == "DISPOSAL"]
    additions = [op for op in req.operations if op.type == "ADD"]

    logger.info(
        f"🎯 Нормализация: {len(disposals)} DISPOSAL + {len(additions)} ADD = "
        f"{len(req.operations)} всего"
    )

    details_list = []
    for op in req.operations:
        details_list.append({
            "product_id": op.product_id,
            "product_title": op.product_title,
            "operation": op.type,
            "quantity": abs(op.delta),
            "delta": op.delta,
            "reason": op.reason if op.reason else "—",
        })

    log_audit({
        "faname": user["faname"],
        "point_name": req.point_name,
        "warehouse_id": user["warehouse_id"],
        "operation_type": f"NORMALIZE_BATCH ({len(disposals)}D/{len(additions)}A)",
        "product_count": len(req.operations),
        "ip": request.client.host,
        "user_agent": request.headers.get("user-agent", ""),
        "session_info": req.session_info,
        "details": details_list,
    })

    result = {
        "success": 0, "failed": 0, "errors": [], "operations": [],
        "chunks_info": {"disposal": None, "add": None}
    }

    if disposals:
        items = [{"id": op.product_id, "quantity": abs(op.delta)} for op in disposals]
        
        logger.info(
            f"🚀 DISPOSAL: {len(disposals)} товаров → "
            f"{(len(disposals) + 24) // 25} батчей"
        )
        
        disposal_result = await change_quantity_ss(
            user["warehouse_id"], items, "DISPOSAL"
        )
        
        result["chunks_info"]["disposal"] = disposal_result
        result["success"] += disposal_result["successful_items"]
        result["failed"] += disposal_result["failed_items"]
        
        failed_ids = set()
        for err in disposal_result.get("errors", []):
            failed_ids.update(err.get("item_ids", []))
        
        for op in disposals:
            success = op.product_id not in failed_ids
            result["operations"].append({
                "product_id": op.product_id,
                "product_title": op.product_title,
                "type": "DISPOSAL",
                "quantity": abs(op.delta),
                "success": success,
            })
            if success:
                logger.info(
                    f"✓ DISPOSAL {op.product_title} (id={op.product_id}) "
                    f"by {user['faname']} @ {req.point_name}"
                )

    if additions:
        items = [{"id": op.product_id, "quantity": abs(op.delta)} for op in additions]
        
        logger.info(
            f"🚀 ADD: {len(additions)} товаров → "
            f"{(len(additions) + 24) // 25} батчей"
        )
        
        add_result = await change_quantity_ss(
            user["warehouse_id"], items, "ADD"
        )
        
        result["chunks_info"]["add"] = add_result
        result["success"] += add_result["successful_items"]
        result["failed"] += add_result["failed_items"]
        
        failed_ids = set()
        for err in add_result.get("errors", []):
            failed_ids.update(err.get("item_ids", []))
        
        for op in additions:
            success = op.product_id not in failed_ids
            result["operations"].append({
                "product_id": op.product_id,
                "product_title": op.product_title,
                "type": "ADD",
                "quantity": abs(op.delta),
                "success": success,
            })
            if success:
                logger.info(
                    f"✓ ADD {op.product_title} (id={op.product_id}) "
                    f"by {user['faname']} @ {req.point_name}"
                )

    logger.info(
        f"📊 Нормализация завершена: "
        f"✓ {result['success']} успешно, "
        f"✗ {result['failed']} ошибок"
    )

    return result


# ------------------------------------------------------------
#  Нормализация ОДНОГО товара (legacy)
# ------------------------------------------------------------
@app.post("/api/normalize/single")
async def normalize_single(
    req: NormalizeSingleRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    if req.type == "DISPOSAL":
        if req.reason not in ALLOWED_REASONS_LESS:
            raise HTTPException(400, f"Недопустимая причина: {req.reason}")
        if req.delta >= 0:
            raise HTTPException(400, f"Для DISPOSAL delta < 0: {req.delta}")
    elif req.type == "ADD":
        if req.reason not in ALLOWED_REASONS_MORE:
            raise HTTPException(400, f"Недопустимая причина: {req.reason}")
        if req.delta <= 0:
            raise HTTPException(400, f"Для ADD delta > 0: {req.delta}")
    else:
        raise HTTPException(400, f"Неизвестный тип: {req.type}")

    quantity = abs(req.delta)
    product_title = req.product_title
    
    log_audit({
        "faname": user["faname"],
        "point_name": req.point_name,
        "warehouse_id": user["warehouse_id"],
        "operation_type": f"NORMALIZE_{req.type}",
        "product_count": 1,
        "ip": request.client.host,
        "user_agent": request.headers.get("user-agent", ""),
        "session_info": req.session_info,
        "details": {
            "product_id": req.product_id,
            "product_title": product_title,
            "operation": req.type,
            "quantity": quantity,
            "delta": req.delta,
            "reason": req.reason,
            "giver": req.giver,
            "receiver": req.receiver,
        }
    })

    items = [{"id": req.product_id, "quantity": quantity}]
    ss_result = await change_quantity_ss(user["warehouse_id"], items, req.type)
    
    if ss_result["success"]:
        logger.info(
            f"✓ {req.type} {product_title} (id={req.product_id}) "
            f"by {user['faname']} @ {req.point_name}"
        )
        return {
            "success": True,
            "error": None,
            "details": {
                "product_id": req.product_id,
                "product_title": product_title,
                "operation": req.type,
                "quantity": quantity,
            }
        }
    else:
        error_details = ss_result["errors"][0] if ss_result["errors"] else {}
        logger.error(
            f"✗ Failed {req.type} {product_title} (id={req.product_id}): {error_details}"
        )
        return {
            "success": False,
            "error": f"SmartShell failed: {error_details.get('type', 'unknown')}"
        }


# ------------------------------------------------------------
#  Поиск сотрудников
# ------------------------------------------------------------
@app.post("/api/employees/search")
async def search_employees(req: EmployeeSearchRequest):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            query = req.query.strip()
            if not query or len(query) < 1:
                cur.execute("SELECT faname FROM employees ORDER BY faname LIMIT 100")
            else:
                cur.execute(
                    "SELECT faname FROM employees WHERE faname LIKE %s ORDER BY faname LIMIT 50",
                    (f"%{query}%",)
                )
            employees = [row["faname"] for row in cur.fetchall()]
            return {"employees": employees}
    except Exception as e:
        logger.error(f"Employee search error: {e}")
        return {"employees": []}
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ============================================================
#  🆕 МОДЕЛИ ДЛЯ СОХРАНЕНИЯ ИТОГОВ ПЕРЕСЧЁТА
# ============================================================
class InventoryOperationItem(BaseModel):
    product_id: int
    product_title: str = Field(..., max_length=500)
    quantity: int = Field(..., ge=0)
    cost: float = 0.0
    operation_type: str
    reason: str = ""


class SaveInventoryOperationsRequest(BaseModel):
    operations: list[InventoryOperationItem]
    point_name: str
    administrator: str = Field(..., max_length=255)
    session_label: str = Field(..., max_length=255)
    operation_date: str


class SaveSessionDispolRequest(BaseModel):
    point_name: str
    administrator: str = Field(..., max_length=255)
    cost: float = Field(..., ge=0)
    allItem: list = []
    allitemDis: list = []
    reason: str = Field(default="Пересчёт смены", max_length=500)
    session_label: str = Field(..., max_length=255)


# ============================================================
#  🆕 ИНВЕНТАРИЗАЦИЯ: Сохранение операций
# ============================================================
@app.post("/api/inventory/save-operations")
async def save_inventory_operations(
    req: SaveInventoryOperationsRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not req.operations:
        return {"success": True, "inserted": 0, "message": "Нет операций"}
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            try:
                operation_date = datetime.fromisoformat(
                    req.operation_date.replace("Z", "+00:00")
                )
                if operation_date.tzinfo is not None:
                    operation_date = operation_date.replace(tzinfo=None)
            except Exception:
                operation_date = datetime.now()
            
            inserted = 0
            for op in req.operations:
                cur.execute(
                    """INSERT INTO inventory_operation 
                       (operation_date, point_name, administrator, product_id, 
                        product_title, quantity, cost, operation_type, reason, session_label)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        operation_date, req.point_name, req.administrator,
                        op.product_id, op.product_title, op.quantity, op.cost,
                        op.operation_type, op.reason, req.session_label,
                    ),
                )
                inserted += 1
            
            conn.commit()
        
        log_audit({
            "faname": user["faname"],
            "point_name": req.point_name,
            "warehouse_id": user["warehouse_id"],
            "operation_type": "INVENTORY_OPERATIONS_SAVE",
            "product_count": inserted,
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
            "details": {
                "administrator": req.administrator,
                "session_label": req.session_label,
                "operations_count": inserted,
            },
        })
        
        logger.info(
            f"✓ Saved {inserted} inventory operations for "
            f"{req.administrator} @ {req.point_name}"
        )
        
        return {
            "success": True,
            "inserted": inserted,
            "message": f"Сохранено {inserted} операций",
        }
    
    except Exception as e:
        logger.error(f"✗ Save inventory operations error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ============================================================
#  🆕 ИНВЕНТАРИЗАЦИЯ: Сохранение итога смены
# ============================================================
@app.post("/api/inventory/save-session-dispol")
async def save_session_dispol(
    req: SaveSessionDispolRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            all_item_json = json.dumps(req.allItem, ensure_ascii=False, default=str)
            all_item_dis_json = json.dumps(req.allitemDis, ensure_ascii=False, default=str)
            
            cur.execute(
                """INSERT INTO session_dispol 
                   (point_name, administrator, cost, allItem, allitemDis, reason, session_label)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    req.point_name, req.administrator, req.cost,
                    all_item_json, all_item_dis_json, req.reason, req.session_label,
                ),
            )
            conn.commit()
            new_id = cur.lastrowid
        
        log_audit({
            "faname": user["faname"],
            "point_name": req.point_name,
            "warehouse_id": user["warehouse_id"],
            "operation_type": "SESSION_DISPOL_SAVE",
            "product_count": len(req.allitemDis),
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
            "details": {
                "administrator": req.administrator,
                "session_label": req.session_label,
                "cost": req.cost,
            },
        })
        
        logger.info(
            f"✓ Saved session_dispol (id={new_id}) for {req.administrator}: "
            f"cost={req.cost:.2f} ({req.session_label})"
        )
        
        return {
            "success": True,
            "id": new_id,
            "message": f"Итог смены сохранён: {req.cost:.2f} ₽",
        }
    
    except Exception as e:
        logger.error(f"✗ Save session_dispol error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ============================================================
#  🆕 МОДЕЛИ ДЛЯ TROUBLE
# ============================================================
class TroubleOperationItem(BaseModel):
    product_id: int
    product_title: str = Field(..., max_length=500)
    quantity: int = Field(..., ge=0)
    cost: float = 0.0
    operation_type: str
    reason: str = Field(..., max_length=500)
    reference: str = Field(default="", max_length=2000)
    is_excusable: bool = False


class SaveTroubleOperationsRequest(BaseModel):
    operations: list[TroubleOperationItem]
    point_name: str
    administrator: str = Field(..., max_length=255)
    session_label: str = Field(..., max_length=255)
    operation_date: str


class SaveCorrectTroubleRequest(BaseModel):
    point_name: str
    administrator: str = Field(..., max_length=255)
    cost: float = Field(..., ge=0)
    allitemTrouble: list = []
    allitemDis: list = []
    costTrouble: float = Field(default=0.0, ge=0)
    costDisTrouble: float = Field(default=0.0, ge=0)
    allRef: list = []
    session_label: str = Field(..., max_length=255)


# ============================================================
#  🆕 TROUBLE: Сохранение операций
# ============================================================
@app.post("/api/inventory/save-trouble-operations")
async def save_trouble_operations(
    req: SaveTroubleOperationsRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not req.operations:
        return {"success": True, "inserted": 0, "message": "Нет операций"}
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            try:
                operation_date = datetime.fromisoformat(
                    req.operation_date.replace("Z", "+00:00")
                )
                if operation_date.tzinfo is not None:
                    operation_date = operation_date.replace(tzinfo=None)
            except Exception:
                operation_date = datetime.now()
            
            inserted = 0
            for op in req.operations:
                cur.execute(
                    """INSERT INTO inventory_operation_trouble 
                       (operation_date, point_name, administrator, product_id, 
                        product_title, quantity, cost, operation_type, reason, 
                        reference, is_excusable, session_label)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        operation_date, req.point_name, req.administrator,
                        op.product_id, op.product_title, op.quantity, op.cost,
                        op.operation_type, op.reason, op.reference or None,
                        1 if op.is_excusable else 0, req.session_label,
                    ),
                )
                inserted += 1
            
            conn.commit()
        
        log_audit({
            "faname": user["faname"],
            "point_name": req.point_name,
            "warehouse_id": user["warehouse_id"],
            "operation_type": "TROUBLE_OPERATIONS_SAVE",
            "product_count": inserted,
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
            "details": {
                "administrator": req.administrator,
                "session_label": req.session_label,
                "operations_count": inserted,
            },
        })
        
        logger.info(
            f"✓ Saved {inserted} trouble operations for "
            f"{req.administrator} @ {req.point_name}"
        )
        
        return {"success": True, "inserted": inserted}
    
    except Exception as e:
        logger.error(f"✗ Save trouble operations error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ============================================================
#  🆕 TROUBLE: Сохранение итога с помилованиями
# ============================================================
@app.post("/api/inventory/save-correct-trouble")
async def save_correct_trouble(
    req: SaveCorrectTroubleRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO correctTrouble 
                   (point_name, administrator, cost, allitemTrouble, allitemDis, 
                    costTrouble, costDisTrouble, allRef, session_label)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    req.point_name, req.administrator, req.cost,
                    json.dumps(req.allitemTrouble, ensure_ascii=False, default=str),
                    json.dumps(req.allitemDis, ensure_ascii=False, default=str),
                    req.costTrouble, req.costDisTrouble,
                    json.dumps(req.allRef, ensure_ascii=False, default=str),
                    req.session_label,
                ),
            )
            conn.commit()
            new_id = cur.lastrowid
        
        log_audit({
            "faname": user["faname"],
            "point_name": req.point_name,
            "warehouse_id": user["warehouse_id"],
            "operation_type": "CORRECT_TROUBLE_SAVE",
            "product_count": len(req.allitemDis),
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
            "details": {
                "administrator": req.administrator,
                "session_label": req.session_label,
                "cost": req.cost,
                "costTrouble": req.costTrouble,
                "costDisTrouble": req.costDisTrouble,
            },
        })
        
        logger.info(
            f"✓ Saved correctTrouble (id={new_id}) for {req.administrator}: "
            f"costTrouble={req.costTrouble:.2f}, costDisTrouble={req.costDisTrouble:.2f}"
        )
        
        return {
            "success": True,
            "id": new_id,
            "message": f"Итог с помилованиями сохранён: {req.costDisTrouble:.2f} ₽ к возмещению",
        }
    
    except Exception as e:
        logger.error(f"✗ Save correctTrouble error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ============================================================
# 🆕 v1.4.0: МОДЕЛИ ДЛЯ refState
# ============================================================
class RefStateGeneralRequest(BaseModel):
    point_name: str
    administrator: str = Field(..., max_length=255)
    session_label: str = Field(default="", max_length=255)
    total_types: int = 0
    total_items: int = 0
    total_value: float = Field(default=0.0, ge=0)
    items_on_check: int = 0
    links_count: int = 0
    pdf_path: str = Field(default=None, max_length=500)


class RefStateDetailedItem(BaseModel):
    administrator: str = Field(..., max_length=255)
    product_title: str = Field(..., max_length=500)
    product_id: int = None
    reference: str = Field(..., max_length=500)
    quantity: int = Field(default=0, ge=0)
    value: float = Field(default=0.0, ge=0)
    reason: str = Field(default="", max_length=255)


class RefStateDetailedRequest(BaseModel):
    general_id: int
    items: list[RefStateDetailedItem]


class TelegramRefStateRequest(BaseModel):
    point_name: str
    message: str
    parse_mode: str = "HTML"


# ============================================================
# 🆕 v1.5.0: refState — сохранение отчётов
# ============================================================
@app.post("/api/ref-state/general")
async def save_ref_state_general(
    req: RefStateGeneralRequest,
    request: Request,
):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO refStateGeneral 
                   (point_name, administrator, session_label, total_types,
                    total_items, total_value, items_on_check, links_count, pdf_path)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    req.point_name, req.administrator, req.session_label,
                    req.total_types, req.total_items, req.total_value,
                    req.items_on_check, req.links_count, req.pdf_path,
                ),
            )
            conn.commit()
            new_id = cur.lastrowid
        
        log_audit({
            "faname": req.administrator,
            "point_name": req.point_name,
            "warehouse_id": 0,
            "operation_type": "REF_STATE_GENERAL_SAVE",
            "product_count": req.items_on_check,
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
            "details": {
                "administrator": req.administrator,
                "session_label": req.session_label,
                "total_types": req.total_types,
                "total_items": req.total_items,
                "total_value": req.total_value,
                "links_count": req.links_count,
            },
        })
        
        logger.info(
            f"✓ Saved refStateGeneral (id={new_id}) for {req.administrator} @ {req.point_name}: "
            f"{req.items_on_check} товаров, {req.links_count} ссылок"
        )
        return {"success": True, "id": new_id}
    except Exception as e:
        logger.error(f"✗ Save refStateGeneral error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@app.post("/api/ref-state/detailed")
async def save_ref_state_detailed(
    req: RefStateDetailedRequest,
    request: Request,
):
    if not req.items:
        return {"success": True, "inserted": 0, "message": "Нет записей"}
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            inserted = 0
            for item in req.items:
                cur.execute(
                    """INSERT INTO refStateDetailed 
                       (general_id, administrator, product_title, product_id,
                        reference, quantity, value, reason)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        req.general_id, item.administrator, item.product_title,
                        item.product_id, item.reference, item.quantity,
                        item.value, item.reason,
                    ),
                )
                inserted += 1
            conn.commit()
        
        admin_name = req.items[0].administrator if req.items else "system"
        
        log_audit({
            "faname": admin_name,
            "point_name": "system",
            "warehouse_id": 0,
            "operation_type": "REF_STATE_DETAILED_SAVE",
            "product_count": inserted,
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
            "details": {
                "general_id": req.general_id,
                "items_count": inserted,
            },
        })
        
        logger.info(
            f"✓ Saved {inserted} refStateDetailed records (general_id={req.general_id})"
        )
        return {"success": True, "inserted": inserted}
    except Exception as e:
        logger.error(f"✗ Save refStateDetailed error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ============================================================
# 🆕 v1.5.0: Telegram — отправка PDF-отчёта в топик
# ============================================================
@app.post("/api/telegram/send-ref-state-with-pdf")
async def send_ref_state_with_pdf(
    request: Request,
    point_name: str = Form(...),
    message: str = Form(...),
    parse_mode: str = Form("HTML"),
    pdf_file: UploadFile = File(...),
):
    """Отправляет PDF-отчёт в Telegram топик (без JWT, только X-API-Key)."""
    topic_id = TELEGRAM_TOPIC_MAP.get(point_name)
    if not topic_id or topic_id <= 0:
        return {"success": False, "error": f"no valid topic_id for '{point_name}'"}
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"success": False, "error": "bot/chat_id not configured"}
    
    content = await pdf_file.read()
    file_size = len(content)
    if file_size > 50 * 1024 * 1024:
        return {"success": False, "error": "file too large (>50MB)"}
    
    caption = message
    caption_truncated = False
    if len(caption) > 1024:
        caption = caption[:1020] + "..."
        caption_truncated = True
        logger.warning(f"[Telegram] ⚠ Caption обрезан с {len(message)} до 1024 символов")
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        
        files = {
            "document": (
                pdf_file.filename or "report.pdf",
                io.BytesIO(content),
                "application/pdf"
            )
        }
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_thread_id": topic_id,
            "caption": caption,
            "parse_mode": parse_mode,
        }
        
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, data=data, files=files)
            
            if r.status_code == 200:
                result_data = r.json()
                message_id = result_data.get("result", {}).get("message_id")
                logger.info(
                    f"[Telegram] ✓ PDF отправлен в топик '{point_name}' "
                    f"(topic_id={topic_id}, message_id={message_id}, size={file_size} bytes)"
                )
                return {
                    "success": True,
                    "message_id": message_id,
                    "file_size": file_size,
                    "caption_truncated": caption_truncated,
                }
            else:
                logger.error(f"[Telegram] ✗ HTTP {r.status_code}: {r.text[:500]}")
                return {"success": False, "error": f"HTTP {r.status_code}"}
    
    except httpx.TimeoutException:
        logger.error(f"[Telegram] ✗ Timeout при отправке PDF в {point_name}")
        return {"success": False, "error": "timeout"}
    except Exception as e:
        logger.error(f"[Telegram] ✗ Ошибка отправки PDF: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == "__main__":
    cert_file = Path(__file__).parent / "certs" / "server.crt"
    key_file = Path(__file__).parent / "certs" / "server.key"

    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", "8443")),
        ssl_keyfile=str(key_file),
        ssl_certfile=str(cert_file),
        log_level="info",
    )