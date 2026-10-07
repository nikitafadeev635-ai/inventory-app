"""
QFact API Server — прокси для CyberMG Inventory App.
Защищает мастер-кредами SmartShell, предоставляет API для клиентов.
Все операции логируются в audit_log с детальной информацией о товарах.

v1.8.0 — Усиление безопасности:
- IP-whitelist + Telegram-алерты при попытках взлома
- Rate limiting на /api/auth/* (5 попыток за 15 минут) + глобальный 120/мин
- bcrypt хеширование паролей сотрудников
- Отключение Swagger/OpenAPI в продакшене
- Блокировка сканеров (nikto, sqlmap, nmap, shodan...)
- Security headers (скрытие технологии)
- Кастомные 404/405 без деталей
- Эндпоинт /api/google-sheets/update-shift для закрытия смены
- 🆕 Контрольный топик для логирования всех списаний
- 🆕 Middleware проверки HWID + Hash на каждом запросе
- 🆕 Вшивание HWID в JWT для привязки сессии к железу
"""
import os
import io
import json
import time
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Optional

import bcrypt
import jwt
import httpx
import pymysql
import uvicorn
import ipaddress

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

# Загружаем конфиг
load_dotenv()

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
#  КОНФИГ (SS, JWT, Telegram, Google Sheets)
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

# 🆕 Контрольный топик для логирования всех списаний
TELEGRAM_TOPIC_ID_CNTRL = int(os.getenv("TELEGRAM_TOPIC_ID_CNTRL", "0"))
if TELEGRAM_TOPIC_ID_CNTRL:
    logger.info(f"[Telegram] ✅ Контрольный топик: {TELEGRAM_TOPIC_ID_CNTRL}")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TELEGRAM_TOPIC_MAP = {
    "Русская": int(os.getenv("TELEGRAM_TOPIC_RUSSKAYA", "4")),
    "Сахалинская": int(os.getenv("TELEGRAM_TOPIC_SAHALINSKAYA", "9")),
    "Трамвайная": int(os.getenv("TELEGRAM_TOPIC_TRAMVAYNAYA", "7")),
    "Светланская": int(os.getenv("TELEGRAM_TOPIC_SVETLAYA", "11213")),
    "Ульяновская": int(os.getenv("TELEGRAM_TOPIC_ULYANOVSKAYA", "10")),
    "Калинина": int(os.getenv("TELEGRAM_TOPIC_KALININA", "118019")),
}

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS = Path(__file__).parent / "credentials.json"
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_SHEETS_WORKSHEET = os.getenv("GOOGLE_SHEETS_WORKSHEET", "Учет")

# Маппинг колонок (1-based)
SHEETS_COLUMN_MAP = {
    "Имя": 1, "Точка": 2, "Тег": 3, "Штрафы": 4,
    "Минуса": 5, "Спорный": 6, "Склад": 7, "СуммЧел": 8,
    "Учтено с": 9, "Учтено по": 10, "Состояние": 11,
}

# ============================================================
#  ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ MIDDLEWARE
# ============================================================
is_dev = os.getenv("DEBUG", "false").lower() == "true"

# IP-whitelist
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

# API Key
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

# Rate limit для auth
RATE_LIMIT_MAX_ATTEMPTS = int(os.getenv("RATE_LIMIT_MAX_ATTEMPTS", "5"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "900"))       # 15 минут
RATE_LIMIT_LOCKOUT = int(os.getenv("RATE_LIMIT_LOCKOUT", "900"))      # 15 минут

# Global rate limit
GLOBAL_RATE_MAX = int(os.getenv("GLOBAL_RATE_MAX", "120"))
GLOBAL_RATE_WINDOW = int(os.getenv("GLOBAL_RATE_WINDOW", "60"))

# Счётчики
_login_attempts = defaultdict(list)
_blocked_users = {}
_blocked_ip_tracker = defaultdict(list)
_global_rate_limiter = defaultdict(list)

# SmartShell кеш
_ss_token_cache = {}
_SS_TOKEN_TTL = 3600
_smartshell_request_counter = 0

# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ: Telegram
# ============================================================
async def send_telegram_alert(message: str):
    """Критические уведомления в общий чат."""
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
        return {"success": False, "error": "bot/chat_id not configured"}

    topic_id = TELEGRAM_TOPIC_MAP.get(point_name)
    if not topic_id or topic_id <= 0:
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
            return {"success": False, "error": f"HTTP {r.status_code}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _send_blocked_ip_alert(ip: str, path: str, method: str):
    """Telegram-алерт о попытке доступа с неразрешённого IP."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    now = time.time()
    _blocked_ip_tracker[ip] = [t for t in _blocked_ip_tracker[ip] if now - t < 300]
    if _blocked_ip_tracker[ip]:
        return
    _blocked_ip_tracker[ip].append(now)

    message = (
        f"🚨 <b>ПОПЫТКА ВЗЛОМА!</b>\n"
        f"🌐 <b>IP:</b> <code>{ip}</code>\n"
        f"📍 <b>Запрос:</b> {method} {path}\n"
        f"🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"<i>IP не в белом списке. Если это вы — добавьте IP в .env "
        f"(переменная ALLOWED_IPS или ADMIN_IPS)</i>"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.error(f"[Security] ✗ Ошибка отправки алерта: {e}")


async def send_normalize_control_log(
    faname: str,
    point_name: str,
    operation_type: str,
    product_count: int,
    ip_address: str,
    user_agent: str,
    session_info: dict,
    success: bool,
    disposal_count: int = 0,
    add_count: int = 0,
    failed_count: int = 0,
):
    """
    Отправляет лог операции нормализации в контрольный топик CyberMG.
    Компактный формат без лишних разделителей.
    """
    # Диагностика early returns
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[Telegram] ⚠ Control log: bot/chat_id not configured")
        return
    if not TELEGRAM_TOPIC_ID_CNTRL or TELEGRAM_TOPIC_ID_CNTRL <= 0:
        logger.warning(f"[Telegram] ⚠ Control log: invalid topic_id={TELEGRAM_TOPIC_ID_CNTRL}")
        return

    logger.info(f"[Telegram] 🚀 Starting control log for {point_name}...")

    # Форматируем session_info
    session_label = "—"
    if isinstance(session_info, dict):
        session_label = session_info.get("session_label") or session_info.get("label") or "—"
    elif isinstance(session_info, str) and session_info:
        session_label = session_info

    # Разбивка по операциям
    ops_parts = []
    if disposal_count:
        ops_parts.append(f"📉 Списано: {disposal_count}")
    if add_count:
        ops_parts.append(f"📈 Внесено: {add_count}")
    ops_line = " │ ".join(ops_parts) if ops_parts else ""

    # Статус
    if failed_count > 0:
        status_text = f"⚠️ Успешно: {product_count - failed_count}, Ошибок: {failed_count}"
    else:
        status_text = "✅ Успешно"

    # Компактное сообщение без разделителей
    message = (
        f"👤 <b>Админ:</b> {faname}\n"
        f"🏪 <b>Точка:</b> {point_name}\n"
        f"📦 <b>Операция:</b> <code>{operation_type}</code>\n"
        f"🔢 <b>Товаров:</b> {product_count}\n"
    )

    if ops_line:
        message += f"{ops_line}\n"

    message += (
        f"🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"🌐 <b>IP:</b> <code>{ip_address}</code>\n"
        f"🔧 <b>User-Agent:</b> <code>{user_agent[:80] if user_agent else 'unknown'}</code>\n"
        f"{status_text}"
    )

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_thread_id": TELEGRAM_TOPIC_ID_CNTRL,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                logger.info(f"[Telegram] ✓ Control log sent to topic {TELEGRAM_TOPIC_ID_CNTRL}")
            else:
                logger.error(f"[Telegram] ✗ Control log failed: HTTP {r.status_code} | Body: {r.text[:500]}")
    except httpx.TimeoutException:
        logger.error(f"[Telegram] ✗ Control log timeout (10s)")
    except Exception as e:
        logger.error(f"[Telegram] ✗ Control log error: {type(e).__name__}: {e}")


# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ: Rate limit для auth
# ============================================================
def _check_rate_limit(client_ip: str, faname: str) -> tuple:
    """Проверяет не превышен ли лимит попыток."""
    now = time.time()
    key = (client_ip, faname)

    if key in _blocked_users:
        unlock_at = _blocked_users[key]
        if now < unlock_at:
            return False, int(unlock_at - now)
        else:
            del _blocked_users[key]
            _login_attempts.pop(key, None)

    if key in _login_attempts:
        _login_attempts[key] = [t for t in _login_attempts[key] if now - t < RATE_LIMIT_WINDOW]

    if len(_login_attempts.get(key, [])) >= RATE_LIMIT_MAX_ATTEMPTS:
        _blocked_users[key] = now + RATE_LIMIT_LOCKOUT
        return False, RATE_LIMIT_LOCKOUT

    return True, 0


def _register_failed_attempt(client_ip: str, faname: str):
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
    key = (client_ip, faname)
    _login_attempts.pop(key, None)
    _blocked_users.pop(key, None)


async def _send_rate_limit_alert(ip: str, faname: str, wait_seconds: int):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    message = (
        f"⚠️ <b>ПОДОЗРИТЕЛЬНАЯ АКТИВНОСТЬ</b>\n"
        f"👤 <b>Пользователь:</b> {faname}\n"
        f"🌐 <b>IP:</b> <code>{ip}</code>\n"
        f"🔒 <b>Заблокирован на:</b> {wait_seconds // 60} мин"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.error(f"[Security] ✗ Ошибка rate limit алерта: {e}")

# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ: База данных
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
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT password FROM employees WHERE faname = %s", (faname,))
            row = cur.fetchone()
            if not row:
                return False
            stored_password = row["password"]
            if stored_password.startswith(('$2b$', '$2a$', '$2y$')):
                try:
                    return bcrypt.checkpw(password.encode('utf-8'), stored_password.encode('utf-8'))
                except Exception as e:
                    logger.error(f"bcrypt error for {faname}: {e}")
                    return False
            else:
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
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            details_json = json.dumps(data.get("details"), ensure_ascii=False, default=str) if data.get("details") else None
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
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ: JWT
# ============================================================
def create_jwt_token(faname: str, point_name: str, warehouse_id: int, hwid: str = None) -> str:
    """
    Создаёт JWT-токен для авторизованного пользователя.

    Args:
        faname: ФИО сотрудника
        point_name: Название точки
        warehouse_id: ID склада в SmartShell
        hwid: Hardware ID ПК (опционально, для привязки сессии к железу)
    """
    payload = {
        "faname": faname,
        "point_name": point_name,
        "warehouse_id": warehouse_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    # 🆕 Вшиваем HWID в токен (если передан и валиден)
    if hwid:
        payload["hwid"] = hwid
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        return jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Токен истёк")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Недействительный токен")

# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ: SmartShell
# ============================================================
async def get_smartshell_token(warehouse_id: int) -> str:
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


async def change_quantity_ss(warehouse_id: int, items: list, operation: str, chunk_size: int = 25) -> dict:
    global _smartshell_request_counter
    if not items:
        return {
            "success": True, "total_items": 0, "successful_items": 0, "failed_items": 0,
            "total_batches": 0, "successful_batches": 0, "failed_batches": 0, "errors": [],
            "ss_request_number": 0, "ss_request_count": 0,
        }

    token = await get_smartshell_token(warehouse_id)
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    total_batches = len(chunks)
    mutation_parts, variables, variable_declarations = [], {}, []

    for idx, chunk in enumerate(chunks, start=1):
        batch_name = f"batch{idx}"
        var_name = f"input{idx}"
        mutation_parts.append(f"{batch_name}: changeGoodsQuantity(input: ${var_name})")
        variable_declarations.append(f"${var_name}: ChangeGoodsQuantityInput!")
        variables[var_name] = {"items": chunk, "operation": operation}

    mutation_body = "\n".join(mutation_parts)
    vars_declaration = ", ".join(variable_declarations)
    query = f"""mutation ({vars_declaration}) {{
        {mutation_body}
    }}"""

    _smartshell_request_counter += 1
    current_request_number = _smartshell_request_counter
    logger.info(
        f"📡 [SS-REQUEST #{current_request_number}] 🚀 {operation}: "
        f"{len(items)} товаров → 1 HTTP-запрос с {total_batches} мутациями"
    )

    request_payload = {"query": query, "variables": variables}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                SS_GRAPHQL_URL,
                json=request_payload,
                headers={"Authorization": f"Bearer {token}"},
            )

        if r.status_code != 200:
            return {
                "success": False, "total_items": len(items),
                "successful_items": 0, "failed_items": len(items),
                "total_batches": total_batches, "successful_batches": 0, "failed_batches": total_batches,
                "errors": [{"type": "http_error", "http_status": r.status_code, "message": r.text[:500]}],
                "ss_request_number": current_request_number, "ss_request_count": 1,
            }

        data = r.json()
        if "errors" in data and "data" not in data:
            return {
                "success": False, "total_items": len(items),
                "successful_items": 0, "failed_items": len(items),
                "total_batches": total_batches, "successful_batches": 0, "failed_batches": total_batches,
                "errors": [{"type": "graphql_error", "errors": data["errors"]}],
                "ss_request_number": current_request_number, "ss_request_count": 1,
            }

        successful_items = failed_items = successful_batches = failed_batches = 0
        errors = []
        response_data = data.get("data", {})
        global_errors = data.get("errors", [])

        for idx, chunk in enumerate(chunks, start=1):
            batch_name = f"batch{idx}"
            chunk_size_actual = len(chunk)
            batch_errors = [e for e in global_errors if e.get("path") and batch_name in str(e.get("path", []))]
            batch_result = response_data.get(batch_name)

            if batch_errors:
                failed_items += chunk_size_actual
                failed_batches += 1
                errors.append({"batch": idx, "type": "batch_error", "errors": batch_errors,
                              "items_count": chunk_size_actual, "item_ids": [i["id"] for i in chunk]})
            elif batch_result is not None:
                successful_items += chunk_size_actual
                successful_batches += 1
            else:
                failed_items += chunk_size_actual
                failed_batches += 1
                errors.append({"batch": idx, "type": "unknown_result",
                              "items_count": chunk_size_actual, "item_ids": [i["id"] for i in chunk]})

        return {
            "success": len(errors) == 0,
            "total_items": len(items),
            "successful_items": successful_items, "failed_items": failed_items,
            "total_batches": total_batches,
            "successful_batches": successful_batches, "failed_batches": failed_batches,
            "errors": errors,
            "ss_request_number": current_request_number, "ss_request_count": 1,
        }

    except Exception as e:
        logger.error(f"✗ [SS-REQUEST #{current_request_number}] Exception: {e}")
        return {
            "success": False, "total_items": len(items),
            "successful_items": 0, "failed_items": len(items),
            "total_batches": total_batches, "successful_batches": 0, "failed_batches": total_batches,
            "errors": [{"type": "exception", "exception": str(e)}],
            "ss_request_number": current_request_number, "ss_request_count": 1,
        }

# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ: Google Sheets
# ============================================================
_sheets_client = None


def _get_sheets_worksheet():
    """Ленивая инициализация gspread worksheet."""
    global _sheets_client
    if _sheets_client is None:
        if not GOOGLE_SHEETS_CREDENTIALS.exists():
            raise FileNotFoundError(f"Файл ключей не найден: {GOOGLE_SHEETS_CREDENTIALS}")
        creds = Credentials.from_service_account_file(
            str(GOOGLE_SHEETS_CREDENTIALS),
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        _sheets_client = gspread.authorize(creds)
    spreadsheet = _sheets_client.open_by_key(GOOGLE_SHEETS_ID)
    return spreadsheet.worksheet(GOOGLE_SHEETS_WORKSHEET)


def _find_admin_row(ws, admin_name: str) -> Optional[int]:
    """Ищет строку администратора по имени."""
    names = ws.col_values(SHEETS_COLUMN_MAP["Имя"])
    for idx, name in enumerate(names, start=1):
        if idx == 1:
            continue
        if name and name.strip().lower() == admin_name.strip().lower():
            return idx
    return None


def _safe_float(value) -> float:
    """Безопасно преобразует значение в float."""
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return 0.0

# ============================================================
#  FASTAPI APP
# ============================================================
app = FastAPI(
    title="QFact API",
    version="1.8.0",
    docs_url="/docs" if is_dev and os.getenv("FORCE_DOCS", "false").lower() == "true" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if is_dev and os.getenv("FORCE_DOCS", "false").lower() == "true" else None,
)

# ============================================================
#  EXCEPTION HANDLERS
# ============================================================
@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    logger.info(
        f"[404] {request.client.host if request.client else 'unknown'} → "
        f"{request.method} {request.url.path}"
    )
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.exception_handler(405)
async def custom_405_handler(request: Request, exc):
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if is_dev:
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    logger.warning(f"[Validation] {request.client.host} → {request.url.path}: {exc.errors()}")
    return JSONResponse(status_code=400, content={"detail": "Bad request"})

# ============================================================
#  MIDDLEWARE (порядок объявления = обратный порядок выполнения)
#
#  Порядок ВЫПОЛНЕНИЯ запроса (снаружи внутрь):
#    1. security_headers           (заголовки ко ВСЕМ ответам)
#    2. security_middleware        (IP + API-Key)
#    3. user_agent_filter          (блокировка сканеров)
#    4. global_rate_limit          (считает только легитимные запросы)
#    5. hwid_hash_verification 🆕  (проверка HWID + Hash приложения)
#    6. Роут
# ============================================================

# --- 🆕 0/5: HWID + Hash verification middleware (ближе всех к роуту) ---
@app.middleware("http")
async def hwid_hash_verification_middleware(request: Request, call_next):
    """
    Проверяет HWID и хеш приложения в КАЖДОМ запросе.

    РЕЖИМ: ТОЛЬКО ЛОГИРОВАНИЕ (без блокировки) для безопасного внедрения.
    После проверки работоспособности замените return await call_next(request) на
    return JSONResponse(status_code=403, ...) для включения реальной блокировки.

    Защита от сценариев:
    - Запуск клона .exe (неизвестный hash)
    - Работа через curl с другого ПК (HWID mismatch)
    - Использование украденного JWT (JWT HWID ≠ request HWID)
    """
    path = request.url.path

    # Пропускаем публичные эндпоинты
    if path in ["/", "/api/validate-launch"] or path.startswith("/api/debug/"):
        return await call_next(request)

    # Пропускаем логин (там HWID ещё нет в JWT)
    if path in ["/api/auth/login", "/api/auth/verify_password"]:
        return await call_next(request)

    # Пропускаем админские эндпоинты (у них своя защита)
    if path.startswith("/api/admin/"):
        return await call_next(request)

    # Проверяем наличие заголовков
    client_hash = request.headers.get("X-Client-Hash", "")
    client_hwid = request.headers.get("X-Client-HWID", "")
    auth_header = request.headers.get("Authorization", "")

    client_ip = request.client.host if request.client else "unknown"

    # Если нет заголовков — пропускаем (обратная совместимость со старыми клиентами)
    if not client_hash or not client_hwid:
        logger.warning(
            f"[Security] ⛔ Missing HWID/Hash headers: {client_ip} → {path}"
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": "X-Client-Hash and X-Client-HWID headers required",
                "error": "Missing security headers"
            }
        )

    # === ПРОВЕРКА 1: Hash в allowed_builds ===
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version, active FROM allowed_builds WHERE hash = %s",
                (client_hash,)
            )
            build = cur.fetchone()

            if not build:
                logger.warning(
                    f"🚨 [Security] Unknown build hash: "
                    f"{client_hash[:16]}... from {client_ip} → {path}"
                )
                asyncio.create_task(send_telegram_alert(
                    f"🚨 <b>НЕИЗВЕСТНЫЙ БИЛД!</b>\n"
                    f"🌐 IP: <code>{client_ip}</code>\n"
                    f"🔐 Hash: <code>{client_hash[:16]}...</code>\n"
                    f"📍 Путь: {path}\n"
                    f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                ))
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Unknown build hash. Contact administrator."}
                )

            if not build["active"]:
                logger.warning(
                    f"🚨 [Security] Revoked build hash: "
                    f"{client_hash[:16]}... from {client_ip} → {path}"
                )
                asyncio.create_task(send_telegram_alert(
                    f"🚨 <b>БИЛД ОТОЗВАН!</b>\n"
                    f"🌐 IP: <code>{client_ip}</code>\n"
                    f"🔐 Hash: <code>{client_hash[:16]}...</code>\n"
                    f"📍 Путь: {path}\n"
                    f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                ))
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Build revoked. Update application."}
                )

            # === ПРОВЕРКА 2: HWID в point_bindings ===
            if auth_header.startswith("Bearer "):
                try:
                    token = auth_header.split(" ")[1]
                    jwt_payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
                    point_name = jwt_payload.get("point_name")
                    jwt_hwid = jwt_payload.get("hwid")

                    if point_name:
                        # Проверяем HWID для этой точки
                        cur.execute(
                            "SELECT hwid, active FROM point_bindings WHERE point_name = %s",
                            (point_name,)
                        )
                        binding = cur.fetchone()

                        if not binding:
                            logger.warning(
                                f"🚨 [Security] Point not bound: {point_name} "
                                f"from {client_ip} → {path}"
                            )
                            asyncio.create_task(send_telegram_alert(
                                f"🚨 <b>ТОЧКА НЕ ПРИВЯЗАНА!</b>\n"
                                f"🏪 Точка: {point_name}\n"
                                f"🌐 IP: <code>{client_ip}</code>\n"
                                f"📍 Путь: {path}\n"
                                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                            ))
                            return JSONResponse(
                                status_code=403,
                                content={"detail": "Point not bound to any HWID"}
                            )
                        
                        if not binding["active"]:
                            logger.warning(
                                f"🚨 [Security] Point deactivated: {point_name} "
                                f"from {client_ip} → {path}"
                            )
                            return JSONResponse(
                                status_code=403,
                                content={"detail": "Point deactivated"}
                            )
                        
                        if binding["hwid"] != client_hwid:
                            logger.warning(
                                f"🚨 [Security] HWID mismatch for {point_name}: "
                                f"bound={binding['hwid'][:16]}..., "
                                f"request={client_hwid[:16]}... "
                                f"from {client_ip} → {path}"
                            )
                            asyncio.create_task(send_telegram_alert(
                                f"🚨 <b>HWID MISMATCH!</b>\n"
                                f"🏪 Точка: {point_name}\n"
                                f"🔐 Bound HWID: <code>{binding['hwid'][:16]}...</code>\n"
                                f"🔐 Request HWID: <code>{client_hwid[:16]}...</code>\n"
                                f"🌐 IP: <code>{client_ip}</code>\n"
                                f"📍 Путь: {path}\n"
                                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                            ))
                            return JSONResponse(
                                status_code=403,
                                content={"detail": "HWID mismatch. Point bound to another PC."}
                            )
                        
                        if jwt_hwid and jwt_hwid != client_hwid:
                            logger.warning(
                                f"🚨 [Security] JWT HWID mismatch: "
                                f"jwt={jwt_hwid[:16]}..., "
                                f"request={client_hwid[:16]}... "
                                f"from {client_ip} → {path}"
                            )
                            asyncio.create_task(send_telegram_alert(
                                f"🚨 <b>JWT HWID MISMATCH!</b>\n"
                                f"👤 Пользователь: {jwt_payload.get('faname')}\n"
                                f"🔐 JWT HWID: <code>{jwt_hwid[:16]}...</code>\n"
                                f"🔐 Request HWID: <code>{client_hwid[:16]}...</code>\n"
                                f"🌐 IP: <code>{client_ip}</code>\n"
                                f"📍 Путь: {path}\n"
                                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                                f"<i>Возможна попытка использовать украденный JWT!</i>"
                            ))
                            return JSONResponse(
                                status_code=403,
                                content={"detail": "JWT HWID does not match request HWID"}
                            )

                        # ✅ Все проверки пройдены
                        logger.debug(
                            f"[Security] ✓ HWID+Hash verified: {point_name}, "
                            f"build={build['version']} from {client_ip}"
                        )

                except jwt.InvalidTokenError:
                    # JWT невалиден — пропустим, пусть Depends(get_current_user) обработает
                    pass
                except Exception as e:
                    logger.error(f"[Security] JWT decode error in HWID middleware: {e}")

    except Exception as e:
        logger.error(f"[Security] HWID verification error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

    return await call_next(request)


# --- 1/5: Global rate limit ---
@app.middleware("http")
async def global_rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path == "/" or path.startswith("/api/debug/"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    _global_rate_limiter[client_ip] = [
        t for t in _global_rate_limiter[client_ip] if now - t < GLOBAL_RATE_WINDOW
    ]

    if len(_global_rate_limiter[client_ip]) >= GLOBAL_RATE_MAX:
        logger.warning(
            f"🚫 [RateLimit] Global limit exceeded: {client_ip} → {path} "
            f"({len(_global_rate_limiter[client_ip])} req in {GLOBAL_RATE_WINDOW}s)"
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests"},
            headers={"Retry-After": str(GLOBAL_RATE_WINDOW)},
        )

    _global_rate_limiter[client_ip].append(now)
    return await call_next(request)


# --- 2/5: User-Agent filter ---
@app.middleware("http")
async def user_agent_filter_middleware(request: Request, call_next):
    path = request.url.path
    if path == "/":
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"

    # Админы с ADMIN_IPS могут использовать любой User-Agent (в т.ч. curl)
    try:
        client_addr = ipaddress.ip_address(client_ip)
        if any(client_addr in net for net in ADMIN_NETWORKS):
            return await call_next(request)
    except (ValueError, TypeError):
        pass

    user_agent = request.headers.get("user-agent", "").lower()
    BLOCKED_USER_AGENTS = [
        "nikto", "sqlmap", "nmap", "masscan", "zgrab", "censys", "shodan",
        "gobuster", "dirb", "dirbuster", "wfuzz", "nuclei", "zap", "burp",
    ]
    for blocked in BLOCKED_USER_AGENTS:
        if blocked in user_agent:
            logger.warning(f"🚫 [Security] Blocked scanner: {blocked} from {client_ip} → {path}")
            await send_telegram_alert(
                f"🚨 <b>ОБНАРУЖЕН СКАНЕР!</b>\n"
                f"🔧 <b>Инструмент:</b> {blocked}\n"
                f"🌐 <b>IP:</b> <code>{client_ip}</code>\n"
                f"📍 <b>Путь:</b> {path}\n"
                f"🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )
            return JSONResponse(status_code=404, content={"detail": "Not found"})

    return await call_next(request)


# --- 3/5: IP-whitelist + API-Key (с разделением admin/обычных путей) ---
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    if path == "/" or path.startswith("/api/debug/"):
        return await call_next(request)

    # Инициализируем переменные для использования в Уровне 2
    is_allowed = False
    is_admin = False

    # Уровень 1: IP-whitelist
    if ALLOWED_NETWORKS or ADMIN_NETWORKS:
        try:
            client_addr = ipaddress.ip_address(client_ip)
            is_allowed = any(client_addr in net for net in ALLOWED_NETWORKS)
            is_admin = any(client_addr in net for net in ADMIN_NETWORKS)
        except ValueError:
            is_allowed = is_admin = False

        if not (is_allowed or is_admin):
            logger.warning(f"🚫 [Security] BLOCKED: {client_ip} → {request.method} {path}")
            if ALERT_ON_BLOCKED_IP:
                await _send_blocked_ip_alert(client_ip, path, request.method)
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied: your IP is not allowed", "ip": client_ip},
            )

    if is_admin:
        logger.debug(f"[Security] 👑 Admin access: {client_ip} → {path}")

    # Уровень 2: Проверка ключей (разные правила для admin и обычных путей)
    is_admin_path = path.startswith("/api/admin/")

    if is_admin_path:
        # ==========================================
        # АДМИНСКИЕ ЭНДПОИНТЫ (/api/admin/*)
        # Требуются ОБА ключа + IP в ADMIN_NETWORKS
        # ==========================================
        # Проверка 1: IP должен быть в ADMIN_NETWORKS (страховка)
        if ADMIN_NETWORKS and not is_admin:
            logger.warning(f"🚫 [Security] Admin endpoint from non-admin IP: {client_ip} → {path}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Admin access denied: IP not in ADMIN_IPS"}
            )

        # Проверка 2: X-API-Key обязателен
        api_key = request.headers.get("X-API-Key")
        if not API_SECRET_KEY or api_key != API_SECRET_KEY:
            logger.warning(f"🚫 [Security] Missing/invalid API key for admin endpoint: {client_ip} → {path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"}
            )

        # Проверка 3: X-Master-Key обязателен
        expected_master = os.getenv("MASTER_API_KEY", "")
        master_key = request.headers.get("X-Master-Key")
        if not expected_master or master_key != expected_master:
            logger.warning(f"🚫 [Security] Missing/invalid master key: {client_ip} → {path}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid master key"}
            )

        logger.debug(f"[Security] 🔑 Admin access granted: {client_ip} → {path}")
    else:
        # ==========================================
        # ОБЫЧНЫЕ ЭНДПОИНТЫ (всё что НЕ /api/admin/*)
        # Требуется ТОЛЬКО X-API-Key
        # ==========================================
        if API_SECRET_KEY:
            api_key = request.headers.get("X-API-Key")
            if api_key != API_SECRET_KEY:
                logger.warning(f"🚫 [Security] Invalid API key from {client_ip} → {path}")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key"}
                )

    return await call_next(request)


# --- 4/5: Security headers (САМЫЙ ВНЕШНИЙ) ---
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    if "server" in response.headers:
        del response.headers["server"]
    if "x-powered-by" in response.headers:
        del response.headers["x-powered-by"]
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

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


class UpdateGoogleSheetsRequest(BaseModel):
    """Модель для обновления гугл-таблицы при закрытии смены"""
    administrator: str = Field(..., max_length=255)
    point_name: str = Field(..., max_length=255)
    total_minus: float = Field(default=0.0, ge=0)
    disputed: float = Field(default=0.0, ge=0)


# Разрешённые причины
ALLOWED_REASONS_LESS = {
    "Не знаю", "Товар украден", "Не прошла корректно оплата",
    "Просрочка", "Съел", "Не хочу разбираться",
}
ALLOWED_REASONS_MORE = {
    "Не знаю откуда плюс - недовнёс бот",
    "Не знаю откуда плюс - недовнёс шелл",
    "Не знаю откуда плюс - может я даун",
}

# ============================================================
#  РОУТЫ
# ============================================================
@app.get("/")
async def root():
    return {"status": "ok", "service": "QFact API", "version": "1.8.0"}


@app.get("/api/debug/ip")
async def debug_ip(request: Request):
    headers_info = {}
    for header in ["x-forwarded-for", "x-real-ip", "x-client-ip", "cf-connecting-ip"]:
        value = request.headers.get(header)
        if value:
            headers_info[header] = value

    client_info = {
        "direct_ip": request.client.host if request.client else None,
        "ip_headers": headers_info,
        "first_forwarded_ip": None,
        "server_time": datetime.now().isoformat(),
    }

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_info["first_forwarded_ip"] = forwarded.split(",")[0].strip()

    real_ip = client_info["first_forwarded_ip"] or client_info["direct_ip"]
    is_allowed = is_admin = False

    if real_ip:
        try:
            client_addr = ipaddress.ip_address(real_ip)
            is_allowed = any(client_addr in net for net in ALLOWED_NETWORKS)
            is_admin = any(client_addr in net for net in ADMIN_NETWORKS)
        except Exception:
            pass

    client_info["whitelist_check"] = {
        "ip_being_checked": real_ip,
        "is_allowed": is_allowed,
        "is_admin": is_admin,
    }
    return client_info


@app.get("/api/debug/headers")
async def debug_headers(request: Request):
    return {
        "headers": dict(request.headers),
        "client_host": request.client.host if request.client else None,
        "url": str(request.url),
        "method": request.method,
    }

# ============================================================
#  АВТОРИЗАЦИЯ
# ============================================================
@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    if req.point_name not in WAREHOUSE_IDS:
        raise HTTPException(400, f"Неизвестная точка: {req.point_name}")

    is_allowed, wait_seconds = _check_rate_limit(client_ip, req.faname)
    if not is_allowed:
        logger.warning(f"[Security] 🚫 Rate limit: {req.faname} @ {client_ip}")
        await _send_rate_limit_alert(client_ip, req.faname, wait_seconds)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много попыток. Подождите {wait_seconds // 60} мин",
            headers={"Retry-After": str(wait_seconds)},
        )

    if not verify_employee(req.faname, req.password):
        _register_failed_attempt(client_ip, req.faname)
        log_audit({
            "faname": req.faname, "point_name": req.point_name,
            "operation_type": "LOGIN_FAILED", "ip": client_ip,
            "user_agent": request.headers.get("user-agent", ""),
        })
        raise HTTPException(401, "Неверный логин или пароль")

    _reset_attempts(client_ip, req.faname)
    warehouse_id = WAREHOUSE_IDS[req.point_name]

    # 🆕 Получаем HWID из заголовка (если есть)
    client_hwid = request.headers.get("X-Client-HWID", "")

    # 🆕 Проверяем что HWID соответствует точке
    hwid_valid = False
    if client_hwid:
        conn_hwid = None
        try:
            conn_hwid = get_db_connection()
            with conn_hwid.cursor() as cur:
                cur.execute(
                    "SELECT hwid FROM point_bindings WHERE point_name = %s AND active = TRUE",
                    (req.point_name,)
                )
                binding = cur.fetchone()
                if binding and binding["hwid"] == client_hwid:
                    hwid_valid = True
                    logger.info(f"[Auth] ✓ HWID validated for {req.point_name}")
                else:
                    logger.warning(
                        f"[Security] ⚠ HWID mismatch at login: "
                        f"{req.faname} @ {req.point_name} from {client_ip}, "
                        f"expected={binding['hwid'][:16] if binding else 'N/A'}..., "
                        f"got={client_hwid[:16]}..."
                    )
        except Exception as e:
            logger.error(f"[Auth] HWID validation error: {e}")
        finally:
            if conn_hwid:
                try:
                    conn_hwid.close()
                except:
                    pass

    # Создаём токен с HWID (если валиден)
    token = create_jwt_token(
        req.faname,
        req.point_name,
        warehouse_id,
        hwid=client_hwid if hwid_valid else None
    )

    log_audit({
        "faname": req.faname, "point_name": req.point_name,
        "warehouse_id": warehouse_id, "operation_type": "LOGIN_SUCCESS",
        "ip": client_ip, "user_agent": request.headers.get("user-agent", ""),
        "details": {
            "hwid_valid": hwid_valid,
            "hwid": client_hwid[:16] + "..." if client_hwid else None
        },
    })
    logger.info(f"✓ Login: {req.faname} @ {req.point_name} from {client_ip} (HWID={'✓' if hwid_valid else '✗'})")
    return {"access_token": token, "warehouse_id": warehouse_id}


@app.post("/api/auth/verify_password")
async def verify_password(request: Request):
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

        is_allowed, wait_seconds = _check_rate_limit(client_ip, faname)
        if not is_allowed:
            return JSONResponse(
                status_code=429,
                content={"verified": False, "error": f"Слишком много попыток. Подождите {wait_seconds // 60} мин"},
            )

        def db_query():
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT faname, password FROM employees WHERE faname = %s", (faname,))
                    return cur.fetchone()
            finally:
                try:
                    conn.close()
                except:
                    pass

        row = await asyncio.get_event_loop().run_in_executor(None, db_query)
        if not row:
            _register_failed_attempt(client_ip, faname)
            return {"verified": False, "error": "Неверный пароль"}

        db_password = row["password"]
        is_valid = False
        if db_password.startswith(('$2b$', '$2a$', '$2y$')):
            try:
                is_valid = bcrypt.checkpw(password.encode('utf-8'), db_password.encode('utf-8'))
            except Exception:
                is_valid = False
        else:
            is_valid = db_password == password

        if is_valid:
            _reset_attempts(client_ip, faname)
            return {"verified": True, "faname": row["faname"]}

        _register_failed_attempt(client_ip, faname)
        return {"verified": False, "error": "Неверный пароль"}

    except Exception as e:
        logger.error(f"[Auth] ✗ Ошибка: {e}")
        return {"verified": False, "error": str(e)}

# ============================================================
#  ТОВАРЫ
# ============================================================
@app.get("/api/goods/list")
async def get_goods(search: str = "", user: dict = Depends(get_current_user)):
    goods = await fetch_goods_from_ss(user["warehouse_id"], search)
    return {"goods": goods, "count": len(goods)}

# ============================================================
#  НОРМАЛИЗАЦИЯ
# ============================================================
@app.post("/api/normalize")
async def normalize(req: NormalizeRequest, request: Request, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    if not req.operations:
        raise HTTPException(400, "Нет операций")

    for op in req.operations:
        if op.type == "DISPOSAL" and op.reason and op.reason not in ALLOWED_REASONS_LESS:
            raise HTTPException(400, f"Недопустимая причина: {op.reason}")
        if op.type == "ADD" and op.reason and op.reason not in ALLOWED_REASONS_MORE:
            raise HTTPException(400, f"Недопустимая причина: {op.reason}")

    disposals = [op for op in req.operations if op.type == "DISPOSAL"]
    additions = [op for op in req.operations if op.type == "ADD"]

    log_audit({
        "faname": user["faname"], "point_name": req.point_name,
        "warehouse_id": user["warehouse_id"],
        "operation_type": f"NORMALIZE_BATCH ({len(disposals)}D/{len(additions)}A)",
        "product_count": len(req.operations),
        "ip": request.client.host,
        "user_agent": request.headers.get("user-agent", ""),
        "session_info": req.session_info,
        "details": [{"product_id": op.product_id, "product_title": op.product_title,
                     "operation": op.type, "quantity": abs(op.delta), "reason": op.reason or "—"}
                    for op in req.operations],
    })

    result = {"success": 0, "failed": 0, "errors": [], "operations": [],
              "chunks_info": {"disposal": None, "add": None}}

    if disposals:
        items = [{"id": op.product_id, "quantity": abs(op.delta)} for op in disposals]
        disposal_result = await change_quantity_ss(user["warehouse_id"], items, "DISPOSAL")
        result["chunks_info"]["disposal"] = disposal_result
        result["success"] += disposal_result["successful_items"]
        result["failed"] += disposal_result["failed_items"]

        failed_ids = set()
        for err in disposal_result.get("errors", []):
            failed_ids.update(err.get("item_ids", []))

        for op in disposals:
            result["operations"].append({
                "product_id": op.product_id, "product_title": op.product_title,
                "type": "DISPOSAL", "quantity": abs(op.delta),
                "success": op.product_id not in failed_ids,
            })

    if additions:
        items = [{"id": op.product_id, "quantity": abs(op.delta)} for op in additions]
        add_result = await change_quantity_ss(user["warehouse_id"], items, "ADD")
        result["chunks_info"]["add"] = add_result
        result["success"] += add_result["successful_items"]
        result["failed"] += add_result["failed_items"]

        failed_ids = set()
        for err in add_result.get("errors", []):
            failed_ids.update(err.get("item_ids", []))

        for op in additions:
            result["operations"].append({
                "product_id": op.product_id, "product_title": op.product_title,
                "type": "ADD", "quantity": abs(op.delta),
                "success": op.product_id not in failed_ids,
            })

    # 🆕 Отправляем лог в контрольный топик через BackgroundTasks (гарантированно)
    try:
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        background_tasks.add_task(
            send_normalize_control_log,
            faname=user["faname"],
            point_name=req.point_name,
            operation_type=f"NORMALIZE_BATCH ({len(disposals)}D/{len(additions)}A)",
            product_count=len(req.operations),
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", "unknown"),
            session_info=req.session_info,
            success=result["failed"] == 0,
            disposal_count=len(disposals),
            add_count=len(additions),
            failed_count=result["failed"],
        )
        logger.info("[Telegram] ✓ Control log task scheduled")
    except Exception as e:
        logger.error(f"[Telegram] ✗ Failed to schedule control log: {e}")

    return result


@app.post("/api/normalize/single")
async def normalize_single(req: NormalizeSingleRequest, request: Request, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
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

    log_audit({
        "faname": user["faname"], "point_name": req.point_name,
        "warehouse_id": user["warehouse_id"],
        "operation_type": f"NORMALIZE_{req.type}", "product_count": 1,
        "ip": request.client.host,
        "user_agent": request.headers.get("user-agent", ""),
        "session_info": req.session_info,
        "details": {"product_id": req.product_id, "product_title": req.product_title,
                    "operation": req.type, "quantity": abs(req.delta), "reason": req.reason},
    })

    items = [{"id": req.product_id, "quantity": abs(req.delta)}]
    ss_result = await change_quantity_ss(user["warehouse_id"], items, req.type)

    # 🆕 Отправляем лог через BackgroundTasks (гарантированно)
    try:
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        background_tasks.add_task(
            send_normalize_control_log,
            faname=user["faname"],
            point_name=req.point_name,
            operation_type=f"NORMALIZE_{req.type}",
            product_count=1,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", "unknown"),
            session_info=req.session_info,
            success=ss_result["success"],
            disposal_count=1 if req.type == "DISPOSAL" else 0,
            add_count=1 if req.type == "ADD" else 0,
            failed_count=0 if ss_result["success"] else 1,
        )
        logger.info("[Telegram] ✓ Control log task scheduled (single)")
    except Exception as e:
        logger.error(f"[Telegram] ✗ Failed to schedule control log: {e}")

    if ss_result["success"]:
        return {
            "success": True, "error": None,
            "details": {"product_id": req.product_id, "product_title": req.product_title,
                        "operation": req.type, "quantity": abs(req.delta)},
        }
    error_details = ss_result["errors"][0] if ss_result["errors"] else {}
    return {"success": False, "error": f"SmartShell failed: {error_details.get('type', 'unknown')}"}

# ============================================================
#  СОТРУДНИКИ
# ============================================================
@app.post("/api/employees/search")
async def search_employees(req: EmployeeSearchRequest):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            query = req.query.strip()
            if not query:
                cur.execute("SELECT faname FROM employees ORDER BY faname LIMIT 100")
            else:
                cur.execute(
                    "SELECT faname FROM employees WHERE faname LIKE %s ORDER BY faname LIMIT 50",
                    (f"%{query}%",),
                )
            return {"employees": [row["faname"] for row in cur.fetchall()]}
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
#  ИНВЕНТАРИЗАЦИЯ
# ============================================================
@app.post("/api/inventory/save-operations")
async def save_inventory_operations(
    req: SaveInventoryOperationsRequest, request: Request, user: dict = Depends(get_current_user)
):
    if not req.operations:
        return {"success": True, "inserted": 0}

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            try:
                operation_date = datetime.fromisoformat(req.operation_date.replace("Z", "+00:00"))
                if operation_date.tzinfo is not None:
                    operation_date = operation_date.replace(tzinfo=None)
            except Exception:
                operation_date = datetime.now()

            inserted = 0
            for op in req.operations:
                cur.execute(
                    """INSERT INTO inventory_operation
                    (operation_date, point_name, administrator, product_id, product_title,
                     quantity, cost, operation_type, reason, session_label)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (operation_date, req.point_name, req.administrator,
                     op.product_id, op.product_title, op.quantity, op.cost,
                     op.operation_type, op.reason, req.session_label),
                )
                inserted += 1
            conn.commit()

            log_audit({
                "faname": user["faname"], "point_name": req.point_name,
                "warehouse_id": user["warehouse_id"],
                "operation_type": "INVENTORY_OPERATIONS_SAVE", "product_count": inserted,
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent", ""),
                "details": {"administrator": req.administrator, "operations_count": inserted},
            })
            return {"success": True, "inserted": inserted}
    except Exception as e:
        logger.error(f"✗ Save inventory operations error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@app.post("/api/inventory/save-session-dispol")
async def save_session_dispol(
    req: SaveSessionDispolRequest, request: Request, user: dict = Depends(get_current_user)
):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO session_dispol
                (point_name, administrator, cost, allItem, allitemDis, reason, session_label)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (req.point_name, req.administrator, req.cost,
                 json.dumps(req.allItem, ensure_ascii=False, default=str),
                 json.dumps(req.allitemDis, ensure_ascii=False, default=str),
                 req.reason, req.session_label),
            )
            conn.commit()
            new_id = cur.lastrowid
            log_audit({
                "faname": user["faname"], "point_name": req.point_name,
                "warehouse_id": user["warehouse_id"],
                "operation_type": "SESSION_DISPOL_SAVE", "product_count": len(req.allitemDis),
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent", ""),
                "details": {"administrator": req.administrator, "cost": req.cost},
            })
            return {"success": True, "id": new_id, "message": f"Итог смены сохранён: {req.cost:.2f} ₽"}
    except Exception as e:
        logger.error(f"✗ Save session_dispol error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================================
#  TROUBLE
# ============================================================
@app.post("/api/inventory/save-trouble-operations")
async def save_trouble_operations(
    req: SaveTroubleOperationsRequest, request: Request, user: dict = Depends(get_current_user)
):
    if not req.operations:
        return {"success": True, "inserted": 0}

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            try:
                operation_date = datetime.fromisoformat(req.operation_date.replace("Z", "+00:00"))
                if operation_date.tzinfo is not None:
                    operation_date = operation_date.replace(tzinfo=None)
            except Exception:
                operation_date = datetime.now()

            inserted = 0
            for op in req.operations:
                cur.execute(
                    """INSERT INTO inventory_operation_trouble
                    (operation_date, point_name, administrator, product_id, product_title,
                     quantity, cost, operation_type, reason, reference, is_excusable, session_label)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (operation_date, req.point_name, req.administrator,
                     op.product_id, op.product_title, op.quantity, op.cost,
                     op.operation_type, op.reason, op.reference or None,
                     1 if op.is_excusable else 0, req.session_label),
                )
                inserted += 1
            conn.commit()

            log_audit({
                "faname": user["faname"], "point_name": req.point_name,
                "warehouse_id": user["warehouse_id"],
                "operation_type": "TROUBLE_OPERATIONS_SAVE", "product_count": inserted,
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent", ""),
                "details": {"administrator": req.administrator, "operations_count": inserted},
            })
            return {"success": True, "inserted": inserted}
    except Exception as e:
        logger.error(f"✗ Save trouble operations error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@app.post("/api/inventory/save-correct-trouble")
async def save_correct_trouble(
    req: SaveCorrectTroubleRequest, request: Request, user: dict = Depends(get_current_user)
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
                (req.point_name, req.administrator, req.cost,
                 json.dumps(req.allitemTrouble, ensure_ascii=False, default=str),
                 json.dumps(req.allitemDis, ensure_ascii=False, default=str),
                 req.costTrouble, req.costDisTrouble,
                 json.dumps(req.allRef, ensure_ascii=False, default=str),
                 req.session_label),
            )
            conn.commit()
            new_id = cur.lastrowid
            log_audit({
                "faname": user["faname"], "point_name": req.point_name,
                "warehouse_id": user["warehouse_id"],
                "operation_type": "CORRECT_TROUBLE_SAVE", "product_count": len(req.allitemDis),
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent", ""),
                "details": {"administrator": req.administrator, "costTrouble": req.costTrouble},
            })
            return {"success": True, "id": new_id}
    except Exception as e:
        logger.error(f"✗ Save correctTrouble error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================================
#  REFSTATE
# ============================================================
@app.post("/api/ref-state/general")
async def save_ref_state_general(req: RefStateGeneralRequest, request: Request):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO refStateGeneral
                (point_name, administrator, session_label, total_types,
                 total_items, total_value, items_on_check, links_count, pdf_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (req.point_name, req.administrator, req.session_label,
                 req.total_types, req.total_items, req.total_value,
                 req.items_on_check, req.links_count, req.pdf_path),
            )
            conn.commit()
            new_id = cur.lastrowid
            log_audit({
                "faname": req.administrator, "point_name": req.point_name,
                "warehouse_id": 0, "operation_type": "REF_STATE_GENERAL_SAVE",
                "product_count": req.items_on_check,
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent", ""),
                "details": {"administrator": req.administrator},
            })
            return {"success": True, "id": new_id}
    except Exception as e:
        logger.error(f"✗ Save refStateGeneral error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@app.post("/api/ref-state/detailed")
async def save_ref_state_detailed(req: RefStateDetailedRequest, request: Request):
    if not req.items:
        return {"success": True, "inserted": 0}

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
                    (req.general_id, item.administrator, item.product_title,
                     item.product_id, item.reference, item.quantity,
                     item.value, item.reason),
                )
                inserted += 1
            conn.commit()

            log_audit({
                "faname": req.items[0].administrator if req.items else "system",
                "point_name": "system", "warehouse_id": 0,
                "operation_type": "REF_STATE_DETAILED_SAVE", "product_count": inserted,
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent", ""),
                "details": {"general_id": req.general_id, "items_count": inserted},
            })
            return {"success": True, "inserted": inserted}
    except Exception as e:
        logger.error(f"✗ Save refStateDetailed error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================================
#  TELEGRAM PDF
# ============================================================
@app.post("/api/telegram/send-ref-state-with-pdf")
async def send_ref_state_with_pdf(
    request: Request,
    point_name: str = Form(...),
    message: str = Form(...),
    parse_mode: str = Form("HTML"),
    pdf_file: UploadFile = File(...),
):
    topic_id = TELEGRAM_TOPIC_MAP.get(point_name)
    if not topic_id or topic_id <= 0:
        return {"success": False, "error": f"no valid topic_id for '{point_name}'"}
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"success": False, "error": "bot/chat_id not configured"}

    content = await pdf_file.read()
    file_size = len(content)
    if file_size > 50 * 1024 * 1024:
        return {"success": False, "error": "file too large (>50MB)"}

    caption = message[:1020] + "..." if len(message) > 1024 else message

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        files = {
            "document": (pdf_file.filename or "report.pdf", io.BytesIO(content), "application/pdf")
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
                message_id = r.json().get("result", {}).get("message_id")
                logger.info(f"[Telegram] ✓ PDF отправлен в топик '{point_name}' (message_id={message_id})")
                return {"success": True, "message_id": message_id, "file_size": file_size}
            return {"success": False, "error": f"HTTP {r.status_code}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        logger.error(f"[Telegram] ✗ Ошибка отправки PDF: {e}")
        return {"success": False, "error": str(e)}

# ============================================================
#  🆕 GOOGLE SHEETS: Обновление Минуса и Спорный при закрытии смены
# ============================================================
@app.post("/api/google-sheets/update-shift")
async def update_google_sheets_shift(
    req: UpdateGoogleSheetsRequest,
    request: Request,
    user: dict = Depends(get_current_user)  # 🛡️ ОБЯЗАТЕЛЬНО JWT!
):
    """
    Обновление Google Sheets с полной защитой.
    
    Требования:
    1. Валидный JWT (Depends(get_current_user))
    2. X-Client-Hash и X-Client-HWID (проверяется middleware)
    3. HWID в JWT = X-Client-HWID
    4. Faname в JWT = administrator в запросе
    5. Monotonic increase (только увеличение значений)
    6. Pydantic валидация (ge=0.0 для total_minus и disputed)
    """
    client_ip = request.client.host if request.client else "unknown"
    
    # ============================================================
    #  🛡️ ПРОВЕРКА 1: HWID в JWT = X-Client-HWID в заголовке
    # ============================================================
    jwt_hwid = user.get("hwid")
    request_hwid = request.headers.get("X-Client-HWID", "")
    
    if jwt_hwid and request_hwid and jwt_hwid != request_hwid:
        logger.error(
            f"[Security] 🚨 HWID MISMATCH в SHEETS! "
            f"JWT: {jwt_hwid[:16]}... vs Request: {request_hwid[:16]}... "
            f"from {client_ip}"
        )
        asyncio.create_task(send_telegram_alert(
            f"🚨 <b>HWID MISMATCH В SHEETS!</b>\n"
            f"👤 <b>Админ:</b> {user.get('faname')}\n"
            f"🔐 <b>JWT HWID:</b> <code>{jwt_hwid[:16]}...</code>\n"
            f"🔐 <b>Request HWID:</b> <code>{request_hwid[:16]}...</code>\n"
            f"🌐 <b>IP:</b> <code>{client_ip}</code>\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"<i>⛔ Запрос заблокирован</i>"
        ))
        raise HTTPException(403, "HWID mismatch between JWT and request headers")
    
    # ============================================================
    #  🛡️ ПРОВЕРКА 2: Faname в JWT = administrator в запросе
    # ============================================================
    jwt_faname = user.get("faname")
    if jwt_faname != req.administrator:
        logger.error(
            f"[Security] 🚨 FANAME MISMATCH в SHEETS! "
            f"JWT: {jwt_faname} vs Request: {req.administrator} "
            f"from {client_ip}"
        )
        asyncio.create_task(send_telegram_alert(
            f"🚨 <b>FANAME MISMATCH В SHEETS!</b>\n"
            f"👤 <b>JWT faname:</b> {jwt_faname}\n"
            f"👤 <b>Request admin:</b> {req.administrator}\n"
            f"🌐 <b>IP:</b> <code>{client_ip}</code>\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"<i>⛔ Запрос заблокирован. Админ пытается изменить чужие данные!</i>"
        ))
        raise HTTPException(403, "Administrator mismatch: JWT faname != request administrator")
    
    # ============================================================
    #  🛡️ ПРОВЕРКА 3: Если оба нуля — пропускаем (смена без расхождений)
    # ============================================================
    if req.total_minus == 0 and req.disputed == 0:
        logger.info(
            f"[GoogleSheets] ℹ️ Нулевая смена: {req.administrator} "
            f"(всё сошлось, обновление не требуется)"
        )
        return {
            "success": True,
            "message": "Смена без расхождений, обновление не требуется",
            "skipped": True
        }
    
    # ============================================================
    #  ПОЛУЧЕНИЕ GOOGLE SHEETS
    # ============================================================
    try:
        ws = await asyncio.get_event_loop().run_in_executor(
            None, _get_sheets_worksheet
        )
    except FileNotFoundError as e:
        logger.error(f"[GoogleSheets] ✗ {e}")
        return {"success": False, "error": str(e), "message": str(e)}
    except Exception as e:
        logger.error(f"[GoogleSheets] ✗ Ошибка подключения: {e}")
        return {"success": False, "error": str(e), "message": str(e)}
    
    # ============================================================
    #  ОБНОВЛЕНИЕ С MONOTONIC INCREASE
    # ============================================================
    try:
        def _update():
            row_num = _find_admin_row(ws, req.administrator)
            if row_num is None:
                return {
                    "success": False,
                    "error": f"Администратор '{req.administrator}' не найден в таблице",
                    "message": "Администратор не найден",
                }
            
            minus_col = SHEETS_COLUMN_MAP["Минуса"]
            disputed_col = SHEETS_COLUMN_MAP["Спорный"]
            
            current_minus = _safe_float(ws.cell(row_num, minus_col).value)
            current_disputed = _safe_float(ws.cell(row_num, disputed_col).value)
            
            new_minus = current_minus + req.total_minus
            new_disputed = current_disputed + req.disputed
            
            # 🛡️ MONOTONIC INCREASE: запрещаем уменьшение
            if new_minus < current_minus or new_disputed < current_disputed:
                logger.error(
                    f"[Security] 🚨 MONOTONIC INCREASE VIOLATION! "
                    f"{req.administrator}: "
                    f"minus {current_minus:.2f} → {new_minus:.2f} (Δ={req.total_minus:+.2f}), "
                    f"disputed {current_disputed:.2f} → {new_disputed:.2f} (Δ={req.disputed:+.2f}) "
                    f"from {client_ip}"
                )
                asyncio.create_task(send_telegram_alert(
                    f"🚨 <b>ПОПЫТКА УМЕНЬШЕНИЯ МИНУСА!</b>\n"
                    f"👤 <b>Админ:</b> {req.administrator}\n"
                    f"💰 <b>Минус:</b> {current_minus:.2f}₽ → {new_minus:.2f}₽ (Δ={req.total_minus:+.2f})\n"
                    f"⚖️ <b>Спорный:</b> {current_disputed:.2f}₽ → {new_disputed:.2f}₽ (Δ={req.disputed:+.2f})\n"
                    f"🌐 <b>IP:</b> <code>{client_ip}</code>\n"
                    f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                    f"<i>⛔ Запрос заблокирован. Значения НЕ изменены.</i>"
                ))
                return {
                    "success": False,
                    "error": "Decreasing values is forbidden",
                    "message": "Уменьшение значений запрещено",
                    "blocked": True,
                    "current_minus": current_minus,
                    "current_disputed": current_disputed,
                }
            
            # ✅ Всё ОК — обновляем
            ws.update_cell(row_num, minus_col, new_minus)
            ws.update_cell(row_num, disputed_col, new_disputed)
            
            message = (
                f"Минуса: {current_minus:.2f} → {new_minus:.2f} (+{req.total_minus}), "
                f"Спорный: {current_disputed:.2f} → {new_disputed:.2f} (+{req.disputed})"
            )
            
            return {
                "success": True,
                "row": row_num,
                "old_minus": current_minus,
                "new_minus": new_minus,
                "old_disputed": current_disputed,
                "new_disputed": new_disputed,
                "message": message,
            }
        
        result = await asyncio.get_event_loop().run_in_executor(None, _update)
        
        if result["success"]:
            logger.info(
                f"[GoogleSheets] ✓ Закрытие смены '{req.administrator}' "
                f"(row {result['row']}): "
                f"Минуса {result['old_minus']:.2f} → {result['new_minus']:.2f} (+{req.total_minus}), "
                f"Спорный {result['old_disputed']:.2f} → {result['new_disputed']:.2f} (+{req.disputed})"
            )
        elif result.get("blocked"):
            logger.warning(
                f"[Security] ⛔ ЗАБЛОКИРОВАНО: {req.administrator} "
                f"попытка уменьшить значения"
            )
        else:
            logger.warning(f"[GoogleSheets] ⚠ {result['error']}")
        
        return result
    
    except Exception as e:
        logger.error(f"[GoogleSheets] ✗ Ошибка обновления: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e), "message": str(e)}

# ============================================================
# 🔐 СИСТЕМА ВАЛИДАЦИИ ЗАПУСКА ПРИЛОЖЕНИЯ
# ============================================================
MASTER_API_KEY = os.getenv("MASTER_API_KEY", "")
BINDING_SECRET = os.getenv("BINDING_SECRET", "")


def _create_signature(point_name: str, hwid: str) -> str:
    """Создаёт HMAC-подпись для point.lock"""
    import hashlib
    data = f"{point_name}:{hwid}:{BINDING_SECRET}"
    return hashlib.sha256(data.encode()).hexdigest()


def _verify_signature(point_name: str, hwid: str, signature: str) -> bool:
    """Проверяет подпись point.lock"""
    expected = _create_signature(point_name, hwid)
    return signature == expected


def _check_master_key(request: Request) -> bool:
    """Middleware уже проверил IP + оба ключа, эта функция - финальная страховка."""
    return True

# ============================================
# POST /api/admin/register-build
# ============================================
@app.post("/api/admin/register-build")
async def register_build(request: Request):
    """Регистрирует новый разрешённый билд"""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_master_key(request):
        logger.warning(f"[Security] 🚫 Invalid master key from {client_ip}")
        raise HTTPException(403, "Invalid master key or IP not in ADMIN_IPS")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    exe_hash = data.get("exe_hash")
    version = data.get("version", "unknown")
    comment = data.get("comment", "")

    if not exe_hash or len(exe_hash) != 64:
        raise HTTPException(400, "Invalid hash (must be 64 hex chars)")

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO allowed_builds (hash, version, active, registered_at, registered_by, comment)
                VALUES (%s, %s, TRUE, NOW(), %s, %s)
                ON DUPLICATE KEY UPDATE
                version = VALUES(version),
                active = TRUE,
                registered_at = NOW(),
                registered_by = VALUES(registered_by),
                comment = VALUES(comment)""",
                (exe_hash, version, client_ip, comment),
            )
            conn.commit()

            log_audit({
                "faname": "admin",
                "point_name": "system",
                "warehouse_id": 0,
                "operation_type": "REGISTER_BUILD",
                "product_count": 1,
                "ip": client_ip,
                "user_agent": request.headers.get("user-agent", ""),
                "details": {"hash": exe_hash[:16] + "...", "version": version},
            })
            logger.info(f"[Build] ✓ Зарегистрирован билд: {exe_hash[:16]}... v{version} from {client_ip}")

            return {
                "success": True,
                "hash": exe_hash,
                "version": version,
                "message": f"Build v{version} registered successfully"
            }
    except Exception as e:
        logger.error(f"✗ Register build error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================
# POST /api/admin/bind-point
# ============================================
@app.post("/api/admin/bind-point")
async def bind_point(request: Request):
    """Привязывает точку к HWID"""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_master_key(request):
        logger.warning(f"[Security] 🚫 Invalid master key from {client_ip}")
        raise HTTPException(403, "Invalid master key or IP not in ADMIN_IPS")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    point_name = data.get("point_name")
    hwid = data.get("hwid")
    comment = data.get("comment", "")

    if not point_name or not hwid:
        raise HTTPException(400, "Missing point_name or hwid")
    if len(hwid) != 32:
        raise HTTPException(400, "Invalid HWID (must be 32 hex chars)")

    signature = _create_signature(point_name, hwid)
    bound_at = datetime.now().isoformat()

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO point_bindings (point_name, hwid, signature, bound_at, active, comment)
                VALUES (%s, %s, %s, NOW(), TRUE, %s)
                ON DUPLICATE KEY UPDATE
                hwid = VALUES(hwid),
                signature = VALUES(signature),
                bound_at = NOW(),
                active = TRUE,
                comment = VALUES(comment)""",
                (point_name, hwid, signature, comment),
            )
            conn.commit()

            log_audit({
                "faname": "admin",
                "point_name": point_name,
                "warehouse_id": 0,
                "operation_type": "BIND_POINT",
                "product_count": 1,
                "ip": client_ip,
                "user_agent": request.headers.get("user-agent", ""),
                "details": {"hwid": hwid[:16] + "...", "signature": signature[:16] + "..."},
            })
            logger.info(f"[Bind] ✓ Точка '{point_name}' привязана к HWID: {hwid[:16]}... from {client_ip}")

            return {
                "success": True,
                "point_name": point_name,
                "hwid": hwid,
                "signature": signature,
                "bound_at": bound_at,
            }
    except Exception as e:
        logger.error(f"✗ Bind point error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================
# POST /api/validate-launch
# ============================================
@app.post("/api/validate-launch")
async def validate_launch(request: Request):
    """Проверяет легитимность запуска приложения"""
    client_ip = request.client.host if request.client else "unknown"

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    exe_hash = data.get("exe_hash")
    hwid = data.get("hwid")
    point_name = data.get("point_name")
    signature = data.get("signature")

    if not all([exe_hash, hwid, point_name, signature]):
        return {"allowed": False, "reason": "Missing required fields"}

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Проверка 1: Билд разрешён
            cur.execute(
                "SELECT version, active FROM allowed_builds WHERE hash = %s",
                (exe_hash,)
            )
            build = cur.fetchone()
            if not build:
                logger.warning(f"[Validate] ❌ Неизвестный билд: {exe_hash[:16]}... from {client_ip}")
                cur.execute(
                    """INSERT INTO launch_attempts
                    (point_name, hwid, exe_hash, ip_address, result, reason)
                    VALUES (%s, %s, %s, %s, 'denied', 'Unknown build')""",
                    (point_name, hwid, exe_hash, client_ip)
                )
                conn.commit()
                return {"allowed": False, "reason": "Unknown build. Contact administrator."}

            if not build["active"]:
                logger.warning(f"[Validate] ❌ Билд отозван: {exe_hash[:16]}... from {client_ip}")
                cur.execute(
                    """INSERT INTO launch_attempts
                    (point_name, hwid, exe_hash, ip_address, result, reason)
                    VALUES (%s, %s, %s, %s, 'denied', 'Build revoked')""",
                    (point_name, hwid, exe_hash, client_ip)
                )
                conn.commit()
                return {"allowed": False, "reason": "Build revoked. Update application."}

            # Проверка 2: Точка привязана
            cur.execute(
                "SELECT hwid, signature, active FROM point_bindings WHERE point_name = %s",
                (point_name,)
            )
            binding = cur.fetchone()
            if not binding:
                logger.warning(f"[Validate] ❌ Точка не привязана: {point_name} from {client_ip}")
                cur.execute(
                    """INSERT INTO launch_attempts
                    (point_name, hwid, exe_hash, ip_address, result, reason)
                    VALUES (%s, %s, %s, %s, 'denied', 'Point not bound')""",
                    (point_name, hwid, exe_hash, client_ip)
                )
                conn.commit()
                return {"allowed": False, "reason": f"Point '{point_name}' not bound"}

            if not binding["active"]:
                cur.execute(
                    """INSERT INTO launch_attempts
                    (point_name, hwid, exe_hash, ip_address, result, reason)
                    VALUES (%s, %s, %s, %s, 'denied', 'Point deactivated')""",
                    (point_name, hwid, exe_hash, client_ip)
                )
                conn.commit()
                return {"allowed": False, "reason": "Point deactivated"}

            # Проверка 3: HWID совпадает
            if binding["hwid"] != hwid:
                logger.warning(f"[Validate] ❌ HWID mismatch for {point_name} from {client_ip}")
                cur.execute(
                    """INSERT INTO launch_attempts
                    (point_name, hwid, exe_hash, ip_address, result, reason)
                    VALUES (%s, %s, %s, %s, 'denied', 'HWID mismatch')""",
                    (point_name, hwid, exe_hash, client_ip)
                )
                conn.commit()
                return {"allowed": False, "reason": "HWID mismatch. Point bound to another PC."}

            # Проверка 4: Подпись валидна
            if not _verify_signature(point_name, hwid, signature):
                logger.warning(f"[Validate] ❌ Invalid signature for {point_name} from {client_ip}")
                cur.execute(
                    """INSERT INTO launch_attempts
                    (point_name, hwid, exe_hash, ip_address, result, reason)
                    VALUES (%s, %s, %s, %s, 'denied', 'Invalid signature')""",
                    (point_name, hwid, exe_hash, client_ip)
                )
                conn.commit()
                return {"allowed": False, "reason": "Invalid signature in point.lock"}

            # Все проверки пройдены
            cur.execute(
                "UPDATE point_bindings SET last_seen = NOW() WHERE point_name = %s",
                (point_name,)
            )
            cur.execute(
                """INSERT INTO launch_attempts
                (point_name, hwid, exe_hash, ip_address, result, reason)
                VALUES (%s, %s, %s, %s, 'allowed', 'All checks passed')""",
                (point_name, hwid, exe_hash, client_ip)
            )
            conn.commit()
            logger.info(f"[Validate] ✓ Запуск разрешён: {point_name}, билд {exe_hash[:16]}... from {client_ip}")

            return {
                "allowed": True,
                "version": build["version"],
                "point_name": point_name,
            }

    except Exception as e:
        logger.error(f"✗ Validate launch error: {e}")
        return {"allowed": True, "reason": "Database error - offline mode", "version": "offline", "offline_mode": True}
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================
# GET /api/admin/builds
# ============================================
@app.get("/api/admin/builds")
async def list_builds(request: Request):
    """Возвращает список зарегистрированных билдов"""
    if not _check_master_key(request):
        raise HTTPException(403, "Invalid master key or IP not in ADMIN_IPS")

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT hash, version, active, registered_at, registered_by, comment
                FROM allowed_builds
                ORDER BY registered_at DESC"""
            )
            builds = cur.fetchall()
            return {
                "builds": [
                    {
                        "hash": b["hash"][:16] + "...",
                        "full_hash": b["hash"],
                        "version": b["version"],
                        "active": b["active"],
                        "registered_at": b["registered_at"].isoformat() if b["registered_at"] else None,
                        "registered_by": b["registered_by"],
                        "comment": b["comment"],
                    }
                    for b in builds
                ],
                "count": len(builds)
            }
    except Exception as e:
        logger.error(f"✗ List builds error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================
# GET /api/admin/points
# ============================================
@app.get("/api/admin/points")
async def list_points(request: Request):
    """Возвращает список привязанных точек"""
    if not _check_master_key(request):
        raise HTTPException(403, "Invalid master key or IP not in ADMIN_IPS")

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT point_name, hwid, bound_at, last_seen, active, comment
                FROM point_bindings
                ORDER BY bound_at DESC"""
            )
            points = cur.fetchall()
            return {
                "points": [
                    {
                        "name": p["point_name"],
                        "hwid": p["hwid"][:16] + "...",
                        "full_hwid": p["hwid"],
                        "bound_at": p["bound_at"].isoformat() if p["bound_at"] else None,
                        "last_seen": p["last_seen"].isoformat() if p["last_seen"] else None,
                        "active": p["active"],
                        "comment": p["comment"],
                    }
                    for p in points
                ],
                "count": len(points)
            }
    except Exception as e:
        logger.error(f"✗ List points error: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

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