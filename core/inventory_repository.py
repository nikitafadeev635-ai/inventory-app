"""
Репозиторий для сохранения итогов инвентаризации в БД через VPS прокси.
"""
from datetime import datetime
from typing import List, Dict, Any, Optional
import httpx

# 🆕 Импорт функций для HWID и хеша (для middleware проверки на сервере)
try:
    from core.integrity_checker import get_exe_hash, get_hardware_id
    _INTEGRITY_AVAILABLE = True
except ImportError:
    _INTEGRITY_AVAILABLE = False
    get_exe_hash = lambda: ""
    get_hardware_id = lambda: ""


class InventoryRepository:
    """Сохраняет операции и итоги смен в БД через прокси-сервер."""
    
    def __init__(self, client):
        self.client = client
        
        # Получаем base_url из PROXY_SERVER_URL
        self._base_url = None
        try:
            from config import PROXY_SERVER_URL
            self._base_url = PROXY_SERVER_URL
        except ImportError:
            pass
        
        if not self._base_url:
            self._base_url = (
                getattr(client, 'base_url', None) or 
                getattr(client, '_base_url', None) or
                getattr(client, 'api_base_url', None)
            )
        
        # Получаем API_SECRET_KEY из config
        self._api_key = None
        try:
            from config import API_SECRET_KEY
            self._api_key = API_SECRET_KEY
        except ImportError:
            pass
        
        # Получаем token из current_session
        self._token = None
        try:
            from core.session import current_session
            self._token = getattr(current_session, 'token', None)
        except ImportError:
            pass
        
        if not self._token:
            self._token = (
                getattr(client, 'token', None) or 
                getattr(client, '_token', None) or
                getattr(client, '_access_token', None)
            )
        
        # 🆕 ВЫЧИСЛЕНИЕ HWID И HASH (один раз при инициализации)
        # Критически важно для middleware проверки на сервере!
        self._client_hash = ""
        self._client_hwid = ""
        
        if _INTEGRITY_AVAILABLE:
            try:
                self._client_hash = get_exe_hash() or ""
                self._client_hwid = get_hardware_id() or ""
            except Exception as e:
                print(f"[InventoryRepository] ⚠ Ошибка вычисления HWID/Hash: {e}")
                self._client_hash = ""
                self._client_hwid = ""
        
        print(f"[InventoryRepository] Инициализация:")
        print(f"  base_url: {self._base_url}")
        print(f"  token: {'есть' if self._token else 'НЕТ!'}")
        print(f"  api_key: {'есть' if self._api_key else 'НЕТ'}")
        print(f"  HWID: {self._client_hwid[:16] + '...' if self._client_hwid else '—'}")
        print(f"  Hash: {self._client_hash[:16] + '...' if self._client_hash else '—'}")
    
    def _get_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        
        # 🆕 КРИТИЧНО: Добавляем HWID и Hash для middleware проверки на сервере
        # Без этих заголовков сервер видит запрос как "Legacy client"
        if self._client_hash:
            headers["X-Client-Hash"] = self._client_hash
        if self._client_hwid:
            headers["X-Client-HWID"] = self._client_hwid
        
        return headers
    
    def _post(self, endpoint: str, payload: dict) -> Optional[httpx.Response]:
        if not self._base_url:
            raise RuntimeError("PROXY_SERVER_URL не настроен в config.py")
        
        url = f"{self._base_url.rstrip('/')}{endpoint}"
        headers = self._get_headers()
        
        print(f"[InventoryRepository] → POST {url}")
        
        # 🆕 КРИТИЧНО: trust_env=False чтобы НЕ использовать системный прокси Windows
        # Иначе httpx пытается идти через HTTP_PROXY/HTTPS_PROXY и падает с ConnectError
        with httpx.Client(
            timeout=30, 
            verify=False, 
            trust_env=False
        ) as http_client:
            response = http_client.post(url, json=payload, headers=headers)
            print(f"[InventoryRepository] ← HTTP {response.status_code}")
            return response
    
    def save_operations(
        self,
        operations: List[Dict[str, Any]],
        point_name: str,
        administrator: str,
        session_label: str,
        operation_date: datetime = None,
    ) -> Dict[str, Any]:
        print(f"\n[InventoryRepository] 🔥 save_operations")
        print(f"  operations: {len(operations)} шт")
        print(f"  point: {point_name}, admin: {administrator}")
        
        if not operations:
            return {"success": True, "inserted": 0, "error": None}
        
        if operation_date is None:
            operation_date = datetime.now()
        
        payload = {
            "operations": operations,
            "point_name": point_name,
            "administrator": administrator,
            "session_label": session_label,
            "operation_date": operation_date.isoformat(),
        }
        
        try:
            response = self._post("/api/inventory/save-operations", payload)
            if response is None:
                return {"success": False, "inserted": 0, "error": "No response"}
            
            if response.status_code == 200:
                data = response.json()
                print(f"[InventoryRepository] ✓ Успех: {data}")
                return {
                    "success": True,
                    "inserted": data.get("inserted", 0),
                    "error": None,
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"[InventoryRepository] ✗ Ошибка: {error_msg}")
                return {"success": False, "inserted": 0, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "inserted": 0, "error": str(e)}
    
    def save_session_dispol(
        self,
        point_name: str,
        administrator: str,
        cost: float,
        all_item: List[Dict],
        all_item_dis: List[Dict],
        session_label: str,
        reason: str = "Пересчёт смены",
    ) -> Dict[str, Any]:
        print(f"\n[InventoryRepository] 🔥 save_session_dispol")
        print(f"  point: {point_name}, admin: {administrator}")
        print(f"  cost: {cost}, allItem: {len(all_item)}, allitemDis: {len(all_item_dis)}")
        
        payload = {
            "point_name": point_name,
            "administrator": administrator,
            "cost": cost,
            "allItem": all_item,
            "allitemDis": all_item_dis,
            "reason": reason,
            "session_label": session_label,
        }
        
        try:
            response = self._post("/api/inventory/save-session-dispol", payload)
            if response is None:
                return {"success": False, "id": None, "error": "No response"}
            
            if response.status_code == 200:
                data = response.json()
                print(f"[InventoryRepository] ✓ Успех: {data}")
                return {
                    "success": True,
                    "id": data.get("id"),
                    "error": None,
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"[InventoryRepository] ✗ Ошибка: {error_msg}")
                return {"success": False, "id": None, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "id": None, "error": str(e)}
    
    def save_trouble_operations(
        self,
        operations: List[Dict[str, Any]],
        point_name: str,
        administrator: str,
        session_label: str,
        operation_date: datetime = None,
    ) -> Dict[str, Any]:
        """Сохраняет операции с причинами и ссылками в inventory_operation_trouble."""
        print(f"\n[InventoryRepository] 🔥 save_trouble_operations")
        print(f"  operations: {len(operations)} шт")
        print(f"  point: {point_name}, admin: {administrator}")
        
        if not operations:
            return {"success": True, "inserted": 0, "error": None}
        
        if operation_date is None:
            operation_date = datetime.now()
        
        payload = {
            "operations": operations,
            "point_name": point_name,
            "administrator": administrator,
            "session_label": session_label,
            "operation_date": operation_date.isoformat(),
        }
        
        try:
            response = self._post("/api/inventory/save-trouble-operations", payload)
            if response is None:
                return {"success": False, "inserted": 0, "error": "No response"}
            
            if response.status_code == 200:
                data = response.json()
                print(f"[InventoryRepository] ✓ Успех: {data}")
                return {
                    "success": True,
                    "inserted": data.get("inserted", 0),
                    "error": None,
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"[InventoryRepository] ✗ Ошибка: {error_msg}")
                return {"success": False, "inserted": 0, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "inserted": 0, "error": str(e)}
    
    def save_correct_trouble(
        self,
        point_name: str,
        administrator: str,
        cost: float,
        allitemTrouble: List[Dict],
        allitemDis: List[Dict],
        costTrouble: float,
        costDisTrouble: float,
        allRef: List[Dict],
        session_label: str,
    ) -> Dict[str, Any]:
        """Сохраняет итог смены с учётом помилований в correctTrouble."""
        print(f"\n[InventoryRepository] 🔥 save_correct_trouble")
        print(f"  point: {point_name}, admin: {administrator}")
        print(f"  cost: {cost}")
        print(f"  costTrouble (админ платит): {costTrouble}")
        print(f"  costDisTrouble (списано): {costDisTrouble}")
        print(f"  allitemTrouble: {len(allitemTrouble)}")
        print(f"  allitemDis: {len(allitemDis)}")
        print(f"  allRef: {len(allRef)}")
        
        payload = {
            "point_name": point_name,
            "administrator": administrator,
            "cost": cost,
            "allitemTrouble": allitemTrouble,
            "allitemDis": allitemDis,
            "costTrouble": costTrouble,
            "costDisTrouble": costDisTrouble,
            "allRef": allRef,
            "session_label": session_label,
        }
        
        try:
            response = self._post("/api/inventory/save-correct-trouble", payload)
            if response is None:
                return {"success": False, "id": None, "error": "No response"}
            
            if response.status_code == 200:
                data = response.json()
                print(f"[InventoryRepository] ✓ Успех: {data}")
                return {
                    "success": True,
                    "id": data.get("id"),
                    "error": None,
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"[InventoryRepository] ✗ Ошибка: {error_msg}")
                return {"success": False, "id": None, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "id": None, "error": str(e)}