"""
Клиент для обновления Google Sheets через VPS.
Отправляет итоговые суммы смены (totalMinus, disputed) на сервер,
который обновляет Google Sheets через gspread.

v1.1 — Убраны дублирующие print (вся визуализация в inventory_window.py)
v1.2 — Добавлены HWID/Hash заголовки + JWT для защиты Google Sheets
"""
import logging
import httpx
from config import PROXY_SERVER_URL, API_SECRET_KEY

# 🆕 Импорт для HWID и Hash
try:
    from core.integrity_checker import get_exe_hash, get_hardware_id
    _INTEGRITY_AVAILABLE = True
except ImportError:
    _INTEGRITY_AVAILABLE = False
    get_exe_hash = lambda: ""
    get_hardware_id = lambda: ""

logger = logging.getLogger("inventory_app")


class GoogleSheetsClient:
    """Клиент для работы с Google Sheets через VPS API."""

    def __init__(self, api_client):
        """
        Args:
            api_client: экземпляр ApiClient для получения токена (опционально)
        """
        self.api_client = api_client
        self.base_url = PROXY_SERVER_URL
        self.api_key = API_SECRET_KEY
        
        # 🆕 Вычисляем HWID и Hash один раз
        self._client_hash = ""
        self._client_hwid = ""
        if _INTEGRITY_AVAILABLE:
            try:
                self._client_hash = get_exe_hash() or ""
                self._client_hwid = get_hardware_id() or ""
            except Exception as e:
                print(f"[GoogleSheets] ⚠ Ошибка HWID/Hash: {e}")

    async def update_shift(
        self,
        administrator: str,
        point_name: str,
        total_minus: float,
        disputed: float,
    ) -> dict:
        """
        Обновляет поля 'Минуса' и 'Спорный' в Google Sheets
        для указанного администратора.
        """
        url = f"{self.base_url}/api/google-sheets/update-shift"
        
        # 🆕 Заголовки с HWID/Hash + JWT
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        
        # 🆕 Добавляем HWID и Hash
        if self._client_hash:
            headers["X-Client-Hash"] = self._client_hash
        if self._client_hwid:
            headers["X-Client-HWID"] = self._client_hwid
        
        # 🆕 Добавляем JWT из api_client (сервер теперь требует JWT!)
        if self.api_client and hasattr(self.api_client, '_token') and self.api_client._token:
            headers["Authorization"] = f"Bearer {self.api_client._token}"

        payload = {
            "administrator": administrator,
            "point_name": point_name,
            "total_minus": total_minus,
            "disputed": disputed,
        }

        logger.info(f"[GoogleSheets] → POST {url}")
        logger.info(f"[GoogleSheets] administrator: {administrator}")
        logger.info(f"[GoogleSheets] point_name: {point_name}")
        logger.info(f"[GoogleSheets] total_minus: {total_minus}")
        logger.info(f"[GoogleSheets] disputed: {disputed}")

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                verify=False,
                trust_env=False,
                proxy=None,
            ) as client:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("success"):
                        logger.info(f"[GoogleSheets] ✓ {data.get('message')}")
                    else:
                        logger.warning(f"[GoogleSheets] ⚠ {data.get('error')}")
                    return data
                elif r.status_code == 403:
                    logger.error(f"[GoogleSheets] ✗ HTTP 403: {r.text[:200]}")
                    logger.error("[GoogleSheets] Проверьте что JWT валидный и HWID совпадает")
                    return {
                        "success": False,
                        "error": f"HTTP 403: {r.text[:200]}",
                    }
                elif r.status_code == 401:
                    logger.error(f"[GoogleSheets] ✗ HTTP 401: {r.text[:200]}")
                    logger.error("[GoogleSheets] JWT отсутствует или невалидный")
                    return {
                        "success": False,
                        "error": f"HTTP 401: {r.text[:200]}",
                    }
                elif r.status_code == 404:
                    logger.warning("[GoogleSheets] ⚠ Эндпоинт не найден (сервер не обновлён)")
                    return {
                        "success": False,
                        "error": "Эндпоинт /api/google-sheets/update-shift не найден на сервере",
                    }
                elif r.status_code == 500:
                    logger.error(f"[GoogleSheets] ✗ Ошибка сервера: {r.text[:200]}")
                    return {
                        "success": False,
                        "error": f"HTTP 500: {r.text[:200]}",
                    }
                else:
                    logger.error(f"[GoogleSheets] ✗ HTTP {r.status_code}: {r.text[:200]}")
                    return {
                        "success": False,
                        "error": f"HTTP {r.status_code}",
                    }
        except httpx.ConnectError as e:
            logger.error(f"[GoogleSheets] ✗ Ошибка подключения к VPS: {e}")
            return {"success": False, "error": f"ConnectError: {e}"}
        except httpx.TimeoutException:
            logger.error("[GoogleSheets] ✗ Таймаут подключения (30 сек)")
            return {"success": False, "error": "Timeout"}
        except Exception as e:
            logger.error(f"[GoogleSheets] ✗ Непредвиденная ошибка: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}