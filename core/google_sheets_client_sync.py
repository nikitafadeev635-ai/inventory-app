"""
Синхронный клиент для обновления Google Sheets.
Заменяет async-версию для упрощения кода и устранения риска deadlock.
"""
import logging
import httpx
from config import PROXY_SERVER_URL, API_SECRET_KEY

logger = logging.getLogger("inventory_app")

# Импорт для HWID и Hash
try:
    from core.integrity_checker import get_exe_hash, get_hardware_id
    _INTEGRITY_AVAILABLE = True
except ImportError:
    _INTEGRITY_AVAILABLE = False


class GoogleSheetsClientSync:
    """Синхронный клиент для работы с Google Sheets через VPS API."""

    def __init__(self, api_client):
        """
        Args:
            api_client: экземпляр ApiClient для получения токена
        """
        self.api_client = api_client
        self.base_url = PROXY_SERVER_URL
        self.api_key = API_SECRET_KEY
        
        # Вычисляем HWID и Hash один раз
        self._client_hash = ""
        self._client_hwid = ""
        if _INTEGRITY_AVAILABLE:
            try:
                self._client_hash = get_exe_hash() or ""
                self._client_hwid = get_hardware_id() or ""
            except Exception as e:
                logger.warning(f"[GoogleSheetsSync] Ошибка HWID/Hash: {e}")

    def update_shift(
        self,
        administrator: str,
        point_name: str,
        total_minus: float,
        disputed: float,
    ) -> dict:
        """
        Обновляет поля 'Минуса' и 'Спорный' в Google Sheets.
        
        Returns:
            dict: {"success": bool, "message": str, ...}
        """
        url = f"{self.base_url}/api/google-sheets/update-shift"
        
        # Формируем заголовки
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        
        if self._client_hash:
            headers["X-Client-Hash"] = self._client_hash
        if self._client_hwid:
            headers["X-Client-HWID"] = self._client_hwid
        
        # JWT из api_client
        if self.api_client and hasattr(self.api_client, '_token') and self.api_client._token:
            headers["Authorization"] = f"Bearer {self.api_client._token}"

        payload = {
            "administrator": administrator,
            "point_name": point_name,
            "total_minus": total_minus,
            "disputed": disputed,
        }

        logger.info(f"[GoogleSheetsSync] → POST {url}")

        try:
            with httpx.Client(
                timeout=30.0,
                verify=False,
                trust_env=False,
                proxy=None,
            ) as client:
                r = client.post(url, json=payload, headers=headers)
                
                if r.status_code == 200:
                    data = r.json()
                    if data.get("success"):
                        logger.info(f"[GoogleSheetsSync] ✓ {data.get('message')}")
                    else:
                        logger.warning(f"[GoogleSheetsSync] ⚠ {data.get('error')}")
                    return data
                
                elif r.status_code == 403:
                    logger.error(f"[GoogleSheetsSync] ✗ HTTP 403: {r.text[:200]}")
                    return {"success": False, "error": f"HTTP 403: {r.text[:200]}"}
                
                elif r.status_code == 401:
                    logger.error(f"[GoogleSheetsSync] ✗ HTTP 401: {r.text[:200]}")
                    return {"success": False, "error": f"HTTP 401: {r.text[:200]}"}
                
                elif r.status_code == 404:
                    logger.warning("[GoogleSheetsSync] ⚠ Эндпоинт не найден")
                    return {"success": False, "error": "Эндпоинт не найден на сервере"}
                
                else:
                    logger.error(f"[GoogleSheetsSync] ✗ HTTP {r.status_code}: {r.text[:200]}")
                    return {"success": False, "error": f"HTTP {r.status_code}"}
        
        except httpx.ConnectError as e:
            logger.error(f"[GoogleSheetsSync] ✗ ConnectError: {e}")
            return {"success": False, "error": f"ConnectError: {e}"}
        
        except httpx.TimeoutException:
            logger.error("[GoogleSheetsSync] ✗ Timeout (30s)")
            return {"success": False, "error": "Timeout"}
        
        except Exception as e:
            logger.error(f"[GoogleSheetsSync] ✗ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}