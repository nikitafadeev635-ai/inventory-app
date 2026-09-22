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

Временно отключены (для безопасности):
- Поиск клиентов по телефону
- Корректировка депозита
"""
import os
import json
import time
import logging
import asyncio
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import jwt
import httpx
import pymysql
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Request
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
# Базовые значения в коде, можно переопределить через .env
TELEGRAM_TOPIC_MAP = {
    "Русская": int(os.getenv("TELEGRAM_TOPIC_RUSSKAYA", "4")),
    "Сахалинская": int(os.getenv("TELEGRAM_TOPIC_SAHALINSKAYA", "9")),
    "Трамвайная": int(os.getenv("TELEGRAM_TOPIC_TRAMVAYNAYA", "7")),
    "Светланская": int(os.getenv("TELEGRAM_TOPIC_SVETLAYA", "11213")),
    "Ульяновская": int(os.getenv("TELEGRAM_TOPIC_ULYANOVSKAYA", "10")),
    "Калинина": int(os.getenv("TELEGRAM_TOPIC_KALININA", "118019")),
}


async def send_telegram_alert(message: str):
    """
    Отправляет критические уведомления (crash-логи) в общий чат супергруппы.
    Используется для алертов которые должны видеть ВСЕ филиалы.
    """
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
        # 🆕 v1.4.0: Убрали TELEGRAM_TOPIC_ID — теперь алерты идут в основной чат супергруппы
        # (без message_thread_id — сообщение попадает в general чат, а не в конкретный топик)
        
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            
            if r.status_code == 200:
                logger.info("[Telegram] ✓ Уведомление отправлено")
            else:
                logger.error(f"[Telegram] ✗ HTTP {r.status_code}: {r.text[:200]}")
    
    except Exception as e:
        logger.error(f"[Telegram] ✗ Ошибка отправки: {e}")


async def send_telegram_to_topic(point_name: str, message: str, parse_mode: str = "HTML") -> dict:
    """
    🆕 v1.4.0: Отправляет сообщение в конкретный топик супергруппы
    в зависимости от точки (филиала).
    
    Используется для отчётов refState — каждый филиал получает
    только свои товары на проверке в свой топик.
    
    Args:
        point_name: Название точки ("Русская", "Сахалинская" и т.д.)
        message: Текст сообщения (поддерживает HTML если parse_mode="HTML")
        parse_mode: "HTML" или "Markdown"
    
    Returns:
        {"success": bool, "message_id": int|None, "error": str|None}
    """
    # Проверка базовой конфигурации
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[Telegram] ⚠ Не настроен бот или chat_id — пропуск")
        return {"success": False, "error": "bot/chat_id not configured"}
    
    # Получаем topic_id для точки
    topic_id = TELEGRAM_TOPIC_MAP.get(point_name)
    
    # 🆕 Валидация: topic_id должен быть положительным числом
    # (0 или None = топик не настроен)
    if not topic_id or topic_id <= 0:
        logger.warning(
            f"[Telegram] ⚠ Нет валидного topic_id для точки '{point_name}' "
            f"(получено: {topic_id}). Доступные: {list(TELEGRAM_TOPIC_MAP.keys())}"
        )
        return {
            "success": False, 
            "error": f"no valid topic_id for '{point_name}'"
        }
    
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
            
            # Telegram вернул ошибку — разбираем причину
            error_text = r.text[:300]
            logger.error(
                f"[Telegram] ✗ HTTP {r.status_code} для точки '{point_name}' "
                f"(topic_id={topic_id}): {error_text}"
            )
            
            # Специфичные ошибки Telegram
            if r.status_code == 400 and "message_thread_id" in error_text.lower():
                return {
                    "success": False,
                    "error": f"Invalid topic_id {topic_id} for point '{point_name}'"
                }
            if r.status_code == 401:
                return {"success": False, "error": "Invalid bot token"}
            
            return {"success": False, "error": f"HTTP {r.status_code}"}
    
    except httpx.TimeoutException:
        logger.error(f"[Telegram] ✗ Таймаут отправки в топик {point_name}")
        return {"success": False, "error": "timeout"}
    
    except Exception as e:
        logger.error(f"[Telegram] ✗ Ошибка отправки в топик '{point_name}': {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

# ============================================================
#  FASTAPI APP
# ============================================================
# 🛡️ Отключаем документацию в production (если DEBUG=false)
is_dev = os.getenv("DEBUG", "false").lower() == "true"

app = FastAPI(
    title="QFact API",
    version="1.3.0",
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
    openapi_url="/openapi.json" if is_dev else None,
)

# ============================================================
#  API SECRET KEY — защита от несанкционированного доступа
# ============================================================
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")


@app.middleware("http")
async def check_api_key(request: Request, call_next):
    """Проверяет наличие API Secret Key в заголовке X-API-Key."""
    # 1. Health-check всегда доступен (для мониторинга)
    if request.url.path == "/":
        return await call_next(request)
    
    # 2. Если API_SECRET_KEY не настроен — пропускаем (dev режим)
    if not API_SECRET_KEY:
        return await call_next(request)
    
    # 3. Проверяем заголовок X-API-Key
    api_key = request.headers.get("X-API-Key")
    if api_key != API_SECRET_KEY:
        logger.warning(
            f"🚫 Заблокирован запрос без API key: "
            f"{request.client.host} → {request.method} {request.url.path}"
        )
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Invalid or missing API key",
                "hint": "Требуется заголовок X-API-Key"
            }
        )
    
    # 4. Всё ок — пропускаем запрос дальше
    return await call_next(request)

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
    """Схема для нормализации ОДНОГО товара."""
    product_id: int
    product_title: str = Field(default="Неизвестный товар", max_length=500)
    delta: int
    reason: str
    type: str  # "DISPOSAL" или "ADD"
    session_info: dict
    giver: str
    receiver: str
    point_name: str


class NormalizeOperation(BaseModel):
    """Одна операция в пакетном запросе."""
    product_id: int
    product_title: str = Field(default="Неизвестный товар", max_length=500)
    delta: int
    reason: str
    type: str


class NormalizeRequest(BaseModel):
    """Пакетная нормализация."""
    operations: list[NormalizeOperation]
    session_info: dict
    giver: str
    receiver: str
    point_name: str


class EmployeeSearchRequest(BaseModel):
    """Схема для поиска сотрудников."""
    query: str = Field(default="", max_length=100)


# ============================================================
#  ❌ ВРЕМЕННО ОТКЛЮЧЕНО: Модели клиентов
# ============================================================
# class ClientSearchRequest(BaseModel):
#     """Схема для поиска клиента по телефону."""
#     phone: str = Field(..., min_length=10, max_length=15)
#     point_name: str
#
#
# class DepositUpdateRequest(BaseModel):
#     """Схема для корректировки депозита."""
#     client_uuid: str
#     new_deposit: float = Field(..., ge=0)
#     reason: str = Field(..., min_length=5, max_length=700)
#     point_name: str


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
    """Проверяет пароль сотрудника в БД."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT password FROM employees WHERE faname = %s", (faname,))
            row = cur.fetchone()
            return bool(row) and row["password"] == password
    except Exception as e:
        logger.error(f"DB error: {e}")
        return False


def log_audit(data: dict):
    """Записывает аудит-лог в БД."""
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
#  Использует множественные GraphQL мутации в одном HTTP-запросе
# ============================================================
async def change_quantity_ss(
    warehouse_id: int, 
    items: list, 
    operation: str, 
    chunk_size: int = 25
) -> dict:
    """
    Изменяет количество товаров в SmartShell ОДНИМ HTTP-запросом
    с несколькими именованными мутациями внутри.
    
    Это позволяет обработать 100+ товаров, потратив только 1 единицу
    rate limit (1 из 50 в минуту).
    
    Принцип работы:
    1. Разбиваем товары на чанки по chunk_size (по умолчанию 25)
    2. Строим ОДИН GraphQL запрос с несколькими именованными мутациями:
       mutation {
         batch1: changeGoodsQuantity(input: $input1)
         batch2: changeGoodsQuantity(input: $input2)
         ...
       }
    3. Отправляем ОДИН HTTP-запрос к SmartShell
    4. Анализируем результат каждой мутации отдельно
    
    Args:
        warehouse_id: ID склада
        items: список товаров [{"id": int, "quantity": int}, ...]
        operation: "DISPOSAL" или "ADD"
        chunk_size: размер чанка (по умолчанию 25)
    
    Returns:
        dict: {
            "success": bool,           # True если ВСЕ мутации успешны
            "total_items": int,
            "successful_items": int,
            "failed_items": int,
            "total_batches": int,
            "successful_batches": int,
            "failed_batches": int,
            "errors": list,
            "ss_request_number": int,  # номер запроса в счётчике
            "ss_request_count": int,   # всегда 1
        }
    """
    global _smartshell_request_counter
    
    # ============================================================
    #  Пустой список — сразу возвращаем успех
    # ============================================================
    if not items:
        return {
            "success": True,
            "total_items": 0,
            "successful_items": 0,
            "failed_items": 0,
            "total_batches": 0,
            "successful_batches": 0,
            "failed_batches": 0,
            "errors": [],
            "ss_request_number": 0,
            "ss_request_count": 0,
        }
    
    # ============================================================
    #  Получаем токен SmartShell
    # ============================================================
    token = await get_smartshell_token(warehouse_id)
    
    # ============================================================
    #  Разбиваем на чанки
    # ============================================================
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    total_batches = len(chunks)
    
    # ============================================================
    #  🎯 СТРОИМ ОДИН GraphQL запрос с несколькими мутациями
    # ============================================================
    mutation_parts = []
    variables = {}
    variable_declarations = []
    
    for idx, chunk in enumerate(chunks, start=1):
        batch_name = f"batch{idx}"
        var_name = f"input{idx}"
        
        # Именованная мутация: batch1: changeGoodsQuantity(input: $input1)
        mutation_parts.append(
            f"{batch_name}: changeGoodsQuantity(input: ${var_name})"
        )
        
        # Объявление переменной для GraphQL
        variable_declarations.append(f"${var_name}: ChangeGoodsQuantityInput!")
        
        # Значение переменной
        variables[var_name] = {
            "items": chunk,
            "operation": operation
        }
    
    # Итоговый GraphQL запрос
    mutation_body = "\n    ".join(mutation_parts)
    vars_declaration = ", ".join(variable_declarations)
    query = f"""mutation ({vars_declaration}) {{
    {mutation_body}
}}"""
    
    # ============================================================
    #  🆕 УВЕЛИЧИВАЕМ СЧЁТЧИК (ДОКАЗАТЕЛЬСТВО ЧТО 1 ЗАПРОС)
    # ============================================================
    _smartshell_request_counter += 1
    current_request_number = _smartshell_request_counter
    
    # ============================================================
    #  📡 ЛОГИРУЕМ ОТПРАВКУ
    # ============================================================
    logger.info(
        f"📡 [SS-REQUEST #{current_request_number}] "
        f"🚀 {operation}: {len(items)} товаров → "
        f"1 HTTP-запрос с {total_batches} мутациями внутри"
    )
    
    # Структура чанков
    chunk_info = ", ".join(
        f"batch{i}={len(chunks[i-1])}шт" 
        for i in range(1, total_batches + 1)
    )
    logger.info(
        f"📋 [SS-REQUEST #{current_request_number}] "
        f"Структура: {chunk_info}"
    )
    
    # Размер запроса (доказательство что всё в одном пакете)
    request_payload = {"query": query, "variables": variables}
    request_size = len(json.dumps(request_payload, ensure_ascii=False))
    logger.info(
        f"📦 [SS-REQUEST #{current_request_number}] "
        f"Размер HTTP-запроса: {request_size} байт "
        f"({request_size / 1024:.2f} KB)"
    )
    
    # ============================================================
    #  🚀 ОТПРАВЛЯЕМ ОДИН HTTP-ЗАПРОС К SMARTSHELL
    # ============================================================
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                SS_GRAPHQL_URL,
                json=request_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            
            # ============================================================
            #  📨 ЛОГИРУЕМ ОДИН HTTP-ОТВЕТ
            # ============================================================
            logger.info(
                f"📨 [SS-REQUEST #{current_request_number}] "
                f"Получен ОДИН HTTP-ответ: HTTP {r.status_code}, "
                f"размер: {len(r.text)} байт"
            )
            
            # ============================================================
            #  Обработка HTTP ошибок
            # ============================================================
            if r.status_code != 200:
                logger.error(
                    f"✗ [SS-REQUEST #{current_request_number}] "
                    f"HTTP error: {r.status_code} — {r.text[:500]}"
                )
                return {
                    "success": False,
                    "total_items": len(items),
                    "successful_items": 0,
                    "failed_items": len(items),
                    "total_batches": total_batches,
                    "successful_batches": 0,
                    "failed_batches": total_batches,
                    "errors": [{
                        "type": "http_error",
                        "http_status": r.status_code,
                        "message": r.text[:500]
                    }],
                    "ss_request_number": current_request_number,
                    "ss_request_count": 1,
                }
            
            data = r.json()
            
            # ============================================================
            #  Обработка глобальных GraphQL ошибок (без data)
            # ============================================================
            if "errors" in data and "data" not in data:
                logger.error(
                    f"✗ [SS-REQUEST #{current_request_number}] "
                    f"GraphQL error (no data): {data['errors']}"
                )
                return {
                    "success": False,
                    "total_items": len(items),
                    "successful_items": 0,
                    "failed_items": len(items),
                    "total_batches": total_batches,
                    "successful_batches": 0,
                    "failed_batches": total_batches,
                    "errors": [{
                        "type": "graphql_error",
                        "errors": data["errors"]
                    }],
                    "ss_request_number": current_request_number,
                    "ss_request_count": 1,
                }
            
            # ============================================================
            #  📊 АНАЛИЗИРУЕМ РЕЗУЛЬТАТ КАЖДОЙ МУТАЦИИ
            # ============================================================
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
                
                # Ищем ошибки именно для этой мутации (по path)
                batch_errors = [
                    err for err in global_errors
                    if err.get("path") and batch_name in str(err.get("path", []))
                ]
                
                # Результат этой мутации в data
                batch_result = response_data.get(batch_name)
                
                if batch_errors:
                    # ❌ Мутация упала
                    failed_items += chunk_size_actual
                    failed_batches += 1
                    errors.append({
                        "batch": idx,
                        "type": "batch_error",
                        "errors": batch_errors,
                        "items_count": chunk_size_actual,
                        "item_ids": [item["id"] for item in chunk]
                    })
                    logger.error(
                        f"✗ [SS-REQUEST #{current_request_number}] "
                        f"{operation} batch {idx}/{total_batches} FAILED: "
                        f"{batch_errors}"
                    )
                elif batch_result is not None:
                    # ✅ Мутация успешна
                    successful_items += chunk_size_actual
                    successful_batches += 1
                    logger.info(
                        f"✓ [SS-REQUEST #{current_request_number}] "
                        f"{operation} batch {idx}/{total_batches}: "
                        f"{chunk_size_actual} items"
                    )
                else:
                    # ⚠️ Неоднозначный результат — считаем упавшим
                    failed_items += chunk_size_actual
                    failed_batches += 1
                    errors.append({
                        "batch": idx,
                        "type": "unknown_result",
                        "items_count": chunk_size_actual,
                        "item_ids": [item["id"] for item in chunk]
                    })
                    logger.warning(
                        f"⚠ [SS-REQUEST #{current_request_number}] "
                        f"{operation} batch {idx}/{total_batches}: "
                        f"ambiguous result"
                    )
            
            # ============================================================
            #  ✅ ИТОГОВЫЙ ЛОГ
            # ============================================================
            logger.info(
                f"✅ [SS-REQUEST #{current_request_number}] ЗАВЕРШЁН: "
                f"{successful_items}/{len(items)} товаров успешно, "
                f"{successful_batches}/{total_batches} мутаций успешно, "
                f"использовано 1 из 50 rate limit"
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
                "ss_request_count": 1,  # всегда 1 HTTP-запрос
            }
    
    except Exception as e:
        logger.error(
            f"✗ [SS-REQUEST #{current_request_number}] Exception: {e}"
        )
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "total_items": len(items),
            "successful_items": 0,
            "failed_items": len(items),
            "total_batches": total_batches,
            "successful_batches": 0,
            "failed_batches": total_batches,
            "errors": [{
                "type": "exception",
                "exception": str(e)
            }],
            "ss_request_number": current_request_number,
            "ss_request_count": 1,
        }


# ============================================================
#  РОУТЫ
# ============================================================
@app.get("/")
async def root():
    return {"status": "ok", "service": "QFact API", "version": "1.3.0"}


# ------------------------------------------------------------
#  Авторизация
# ------------------------------------------------------------
@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    if req.point_name not in WAREHOUSE_IDS:
        raise HTTPException(400, f"Неизвестная точка: {req.point_name}")

    if not verify_employee(req.faname, req.password):
        log_audit({
            "faname": req.faname,
            "point_name": req.point_name,
            "operation_type": "LOGIN_FAILED",
            "ip": request.client.host,
            "user_agent": request.headers.get("user-agent", ""),
        })
        raise HTTPException(401, "Неверный логин или пароль")

    warehouse_id = WAREHOUSE_IDS[req.point_name]
    token = create_jwt_token(req.faname, req.point_name, warehouse_id)

    log_audit({
        "faname": req.faname,
        "point_name": req.point_name,
        "warehouse_id": warehouse_id,
        "operation_type": "LOGIN_SUCCESS",
        "ip": request.client.host,
        "user_agent": request.headers.get("user-agent", ""),
    })

    logger.info(f"✓ Login: {req.faname} @ {req.point_name} from {request.client.host}")
    return {"access_token": token, "warehouse_id": warehouse_id}


@app.post("/api/auth/verify_password")
async def verify_password(request: Request):
    """
    Проверяет пароль конкретного сотрудника БЕЗ выдачи JWT.
    """
    try:
        data = await request.json()
        faname = data.get("faname", "").strip()
        password = data.get("password", "").strip()
        
        if not faname or not password:
            return {"verified": False, "error": "Не указан ФИО или пароль"}
        
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
            logger.warning(f"[Auth] ✗ Сотрудник не найден: {faname}")
            return {"verified": False, "error": "Сотрудник не найден"}
        
        db_faname = row["faname"]
        db_password = row["password"]
        
        if db_password == password:
            logger.info(f"[Auth] ✓ Пароль верен для: {faname}")
            return {"verified": True, "faname": db_faname}
        else:
            logger.warning(f"[Auth] ✗ Неверный пароль для: {faname}")
            return {"verified": False, "error": "Неверный пароль"}
    
    except Exception as e:
        logger.error(f"[Auth] ✗ Ошибка verify_password: {e}")
        import traceback
        traceback.print_exc()
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
#  🚀 ПАКЕТНАЯ НОРМАЛИЗАЦИЯ (основной endpoint)
#  Все товары в одном запросе, VPS автоматически:
#  1. Разделяет на DISPOSAL и ADD
#  2. Разбивает на батчи по 25
#  3. Формирует множественные GraphQL мутации
#  4. Делает 1 HTTP-запрос к SmartShell на каждый тип операции
# ------------------------------------------------------------
@app.post("/api/normalize")
async def normalize(
    req: NormalizeRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not req.operations:
        raise HTTPException(400, "Нет операций")

    # Валидация причин (разрешаем пустую строку — причина заполняется позже в TroubleDialog)
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

    # Audit log — одна запись на весь пакет
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
        "success": 0,
        "failed": 0,
        "errors": [],
        "operations": [],
        "chunks_info": {
            "disposal": None,
            "add": None
        }
    }

    # === DISPOSAL (один HTTP-запрос к SmartShell) ===
    if disposals:
        items = [{"id": op.product_id, "quantity": abs(op.delta)} for op in disposals]
        
        logger.info(
            f"🚀 DISPOSAL: {len(disposals)} товаров в одном запросе → "
            f"{(len(disposals) + 24) // 25} батчей"
        )
        
        disposal_result = await change_quantity_ss(
            user["warehouse_id"],
            items,
            "DISPOSAL"
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
                    f"✓ DISPOSAL {op.product_title} (id={op.product_id}, qty={abs(op.delta)}) "
                    f"by {user['faname']} @ {req.point_name}"
                )

    # === ADD (один HTTP-запрос к SmartShell) ===
    if additions:
        items = [{"id": op.product_id, "quantity": abs(op.delta)} for op in additions]
        
        logger.info(
            f"🚀 ADD: {len(additions)} товаров в одном запросе → "
            f"{(len(additions) + 24) // 25} батчей"
        )
        
        add_result = await change_quantity_ss(
            user["warehouse_id"],
            items,
            "ADD"
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
                    f"✓ ADD {op.product_title} (id={op.product_id}, qty={abs(op.delta)}) "
                    f"by {user['faname']} @ {req.point_name}"
                )

    logger.info(
        f"📊 Нормализация завершена: "
        f"✓ {result['success']} успешно, "
        f"✗ {result['failed']} ошибок"
    )

    return result


# ------------------------------------------------------------
#  Нормализация ОДНОГО товара (legacy endpoint)
# ------------------------------------------------------------
@app.post("/api/normalize/single")
async def normalize_single(
    req: NormalizeSingleRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Нормализация ОДНОГО товара через серверный прокси."""
    if req.type == "DISPOSAL":
        if req.reason not in ALLOWED_REASONS_LESS:
            raise HTTPException(400, f"Недопустимая причина списания: {req.reason}")
        if req.delta >= 0:
            raise HTTPException(400, f"Для DISPOSAL delta должен быть < 0: {req.delta}")
    elif req.type == "ADD":
        if req.reason not in ALLOWED_REASONS_MORE:
            raise HTTPException(400, f"Недопустимая причина внесения: {req.reason}")
        if req.delta <= 0:
            raise HTTPException(400, f"Для ADD delta должен быть > 0: {req.delta}")
    else:
        raise HTTPException(400, f"Неизвестный тип операции: {req.type}")

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
            f"✓ {req.type} {product_title} (id={req.product_id}, qty={quantity}) "
            f"by {user['faname']} @ {req.point_name} — reason: {req.reason}"
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
            f"✗ Failed {req.type} {product_title} (id={req.product_id}) "
            f"by {user['faname']} @ {req.point_name}: {error_details}"
        )
        return {
            "success": False,
            "error": f"SmartShell operation failed: {error_details.get('type', 'unknown')}"
        }


# ------------------------------------------------------------
#  Поиск сотрудников (публичный, без JWT)
# ------------------------------------------------------------
@app.post("/api/employees/search")
async def search_employees(req: EmployeeSearchRequest):
    """
    Публичный поиск сотрудников по ФИО (для автодополнения).
    Возвращает только ФИО — без паролей и другой чувствительной информации.
    Не требует JWT-токена.
    """
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


# ============================================================
#  ❌ ВРЕМЕННО ОТКЛЮЧЕНО: Поиск клиентов по телефону
# ============================================================
# @app.post("/api/clients/search")
# async def search_client(req: ClientSearchRequest, request: Request):
#     """Поиск клиента по номеру телефона в SmartShell."""
#     ... (код сохранён в твоём текущем main.py)


# ============================================================
#  ❌ ВРЕМЕННО ОТКЛЮЧЕНО: Корректировка депозита
# ============================================================
# class DepositUpdatePublicRequest(BaseModel):
#     ...
#
# @app.post("/api/clients/deposit")
# async def update_deposit(req: DepositUpdatePublicRequest, request: Request):
#     ... (код сохранён в твоём текущем main.py)


# ============================================================
#  🆕 МОДЕЛИ ДЛЯ СОХРАНЕНИЯ ИТОГОВ ПЕРЕСЧЁТА
# ============================================================
class InventoryOperationItem(BaseModel):
    """Одна операция нормализации."""
    product_id: int
    product_title: str = Field(..., max_length=500)
    quantity: int = Field(..., ge=0)
    cost: float = 0.0
    operation_type: str  # "DISPOSAL" или "ADD"
    reason: str = ""


class SaveInventoryOperationsRequest(BaseModel):
    """Пакетное сохранение операций инвентаризации."""
    operations: list[InventoryOperationItem]
    point_name: str
    administrator: str = Field(..., max_length=255)
    session_label: str = Field(..., max_length=255)
    operation_date: str  # ISO format


class SaveSessionDispolRequest(BaseModel):
    """Сохранение итога смены с чистым минусом."""
    point_name: str
    administrator: str = Field(..., max_length=255)
    cost: float = Field(..., ge=0)
    allItem: list = []
    allitemDis: list = []
    reason: str = Field(default="Пересчёт смены", max_length=500)
    session_label: str = Field(..., max_length=255)


# ============================================================
#  🆕 ИНВЕНТАРИЗАЦИЯ: Сохранение операций нормализации
# ============================================================
@app.post("/api/inventory/save-operations")
async def save_inventory_operations(
    req: SaveInventoryOperationsRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Сохраняет batch операций нормализации в таблицу inventory_operation."""
    if not req.operations:
        return {"success": True, "inserted": 0, "message": "Нет операций"}
    
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
                        operation_date,
                        req.point_name,
                        req.administrator,
                        op.product_id,
                        op.product_title,
                        op.quantity,
                        op.cost,
                        op.operation_type,
                        op.reason,
                        req.session_label,
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
            f"{req.administrator} @ {req.point_name} ({req.session_label})"
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


# ============================================================
#  🆕 ИНВЕНТАРИЗАЦИЯ: Сохранение итога смены (чистый минус)
# ============================================================
@app.post("/api/inventory/save-session-dispol")
async def save_session_dispol(
    req: SaveSessionDispolRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Сохраняет итог смены в таблицу session_dispol."""
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
                    req.point_name,
                    req.administrator,
                    req.cost,
                    all_item_json,
                    all_item_dis_json,
                    req.reason,
                    req.session_label,
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
                "all_items_count": len(req.allItem),
                "dis_items_count": len(req.allitemDis),
            },
        })
        
        logger.info(
            f"✓ Saved session_dispol (id={new_id}) for {req.administrator} @ {req.point_name}: "
            f"cost={req.cost:.2f}, items={len(req.allitemDis)} ({req.session_label})"
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


# ============================================================
#  🆕 МОДЕЛИ ДЛЯ TROUBLE (причины недостач/избытков)
# ============================================================
class TroubleOperationItem(BaseModel):
    """Одна операция с причиной и ссылкой."""
    product_id: int
    product_title: str = Field(..., max_length=500)
    quantity: int = Field(..., ge=0)
    cost: float = 0.0
    operation_type: str  # "DISPOSAL" или "ADD"
    reason: str = Field(..., max_length=500)
    reference: str = Field(default="", max_length=2000)
    is_excusable: bool = False  # уважительная причина + reference


class SaveTroubleOperationsRequest(BaseModel):
    """Пакетное сохранение trouble-операций."""
    operations: list[TroubleOperationItem]
    point_name: str
    administrator: str = Field(..., max_length=255)
    session_label: str = Field(..., max_length=255)
    operation_date: str  # ISO format


class SaveCorrectTroubleRequest(BaseModel):
    """Сохранение итога смены с учётом помилований."""
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
#  🆕 TROUBLE: Сохранение операций с причинами
# ============================================================
@app.post("/api/inventory/save-trouble-operations")
async def save_trouble_operations(
    req: SaveTroubleOperationsRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Сохраняет операции с причинами и ссылками в inventory_operation_trouble."""
    if not req.operations:
        return {"success": True, "inserted": 0, "message": "Нет операций"}
    
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
                        operation_date,
                        req.point_name,
                        req.administrator,
                        op.product_id,
                        op.product_title,
                        op.quantity,
                        op.cost,
                        op.operation_type,
                        op.reason,
                        op.reference or None,
                        1 if op.is_excusable else 0,
                        req.session_label,
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
            f"{req.administrator} @ {req.point_name} ({req.session_label})"
        )
        
        return {"success": True, "inserted": inserted}
    
    except Exception as e:
        logger.error(f"✗ Save trouble operations error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Database error: {str(e)}")

# ============================================================
#  🆕 TROUBLE: Сохранение итога с учётом помилований
# ============================================================
@app.post("/api/inventory/save-correct-trouble")
async def save_correct_trouble(
    req: SaveCorrectTroubleRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Сохраняет итог смены с учётом уважительных причин."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO correctTrouble 
                   (point_name, administrator, cost, allitemTrouble, allitemDis, 
                    costTrouble, costDisTrouble, allRef, session_label)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    req.point_name,
                    req.administrator,
                    req.cost,
                    json.dumps(req.allitemTrouble, ensure_ascii=False, default=str),
                    json.dumps(req.allitemDis, ensure_ascii=False, default=str),
                    req.costTrouble,
                    req.costDisTrouble,
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
            f"✓ Saved correctTrouble (id={new_id}) for {req.administrator} @ {req.point_name}: "
            f"cost={req.cost:.2f}, costTrouble={req.costTrouble:.2f}, "
            f"costDisTrouble={req.costDisTrouble:.2f} ({req.session_label})"
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