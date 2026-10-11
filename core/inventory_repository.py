"""
Репозиторий для сохранения итогов инвентаризации в БД через VPS прокси.
"""
from datetime import datetime
from typing import List, Dict, Any, Optional
import httpx
import json

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
        self._client_hash = ""
        self._client_hwid = ""
        
        if _INTEGRITY_AVAILABLE:
            try:
                self._client_hash = get_exe_hash() or ""
                self._client_hwid = get_hardware_id() or ""
            except Exception as e:
                print(f"[InventoryRepository] ⚠ Ошибка вычисления HWID/Hash: {e}")
        
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
        
        with httpx.Client(
            timeout=30, 
            verify=False, 
            trust_env=False
        ) as http_client:
            response = http_client.post(url, json=payload, headers=headers)
            print(f"[InventoryRepository] ← HTTP {response.status_code}")
            return response
    
    # ============================================================
    #  БАЗОВЫЕ МЕТОДЫ СОХРАНЕНИЯ
    # ============================================================
    
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
        print(f"\n[InventoryRepository] 🔥 save_correct_trouble")
        print(f"  point: {point_name}, admin: {administrator}")
        print(f"  cost: {cost}")
        
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
    
    # ============================================================
    #  🆕 RETRY ЛОГИКА ДЛЯ ЗАПИСИ В БД
    # ============================================================
    
    def _retry_request(self, request_func, max_retries=3, delay=2.0):
        """Выполняет запрос с retry логикой."""
        import time
        last_result = None
        
        for attempt in range(1, max_retries + 1):
            try:
                result = request_func()
                if result.get("success"):
                    if attempt > 1:
                        print(f"[DB] ✓ Успех на попытке {attempt}")
                    return True, result, attempt
                else:
                    last_result = result
                    print(f"[DB] ⚠ Попытка {attempt}/{max_retries}: {result.get('error')}")
            except Exception as e:
                last_result = {"success": False, "error": str(e)}
                print(f"[DB] ⚠ Попытка {attempt}/{max_retries}: Exception {e}")
            
            if attempt < max_retries:
                print(f"[DB] 🔄 Повтор через {delay}с...")
                time.sleep(delay)
        
        return False, last_result or {"error": "Max retries exceeded"}, max_retries
    
    def save_operations_with_retry(self, operations, point_name, administrator,
                                    session_label, operation_date, max_retries=3):
        """save_operations с retry."""
        def _do_save():
            return self.save_operations(
                operations=operations,
                point_name=point_name,
                administrator=administrator,
                session_label=session_label,
                operation_date=operation_date
            )
        return self._retry_request(_do_save, max_retries)
    
    def save_session_dispol_with_retry(self, point_name, administrator, cost,
                                        all_item, all_item_dis, session_label,
                                        reason, max_retries=3):
        """save_session_dispol с retry."""
        def _do_save():
            return self.save_session_dispol(
                point_name=point_name,
                administrator=administrator,
                cost=cost,
                all_item=all_item,
                all_item_dis=all_item_dis,
                session_label=session_label,
                reason=reason
            )
        return self._retry_request(_do_save, max_retries)
    
    def save_trouble_operations_with_retry(self, operations, point_name,
                                            administrator, session_label,
                                            operation_date, max_retries=3):
        """save_trouble_operations с retry."""
        def _do_save():
            return self.save_trouble_operations(
                operations=operations,
                point_name=point_name,
                administrator=administrator,
                session_label=session_label,
                operation_date=operation_date
            )
        return self._retry_request(_do_save, max_retries)
    
    def save_correct_trouble_with_retry(self, point_name, administrator, cost,
                                         allitemTrouble, allitemDis, costTrouble,
                                         costDisTrouble, allRef, session_label,
                                         max_retries=3):
        """save_correct_trouble с retry."""
        def _do_save():
            return self.save_correct_trouble(
                point_name=point_name,
                administrator=administrator,
                cost=cost,
                allitemTrouble=allitemTrouble,
                allitemDis=allitemDis,
                costTrouble=costTrouble,
                costDisTrouble=costDisTrouble,
                allRef=allRef,
                session_label=session_label
            )
        return self._retry_request(_do_save, max_retries)
    
    # ============================================================
    #  🆕 БЛОКИРОВКА ТОЧЕК ДЛЯ СИНХРОНИЗАЦИИ
    # ============================================================
    
    def lock_point_for_sync(self, point_name: str, reason: str,
                            pending_operation_id: int = None) -> Dict[str, Any]:
        """Блокирует точку до синхронизации со SmartShell."""
        print(f"\n[InventoryRepository] 🔒 lock_point_for_sync")
        print(f"  point: {point_name}")
        print(f"  pending_id: {pending_operation_id}")
        
        payload = {
            "point_name": point_name,
            "reason": reason,
            "pending_operation_id": pending_operation_id,
        }
        
        try:
            response = self._post("/api/inventory/lock-point", payload)
            if response is None:
                return {"success": False, "error": "No response"}
            
            if response.status_code == 200:
                data = response.json()
                print(f"[InventoryRepository] ✓ Точка заблокирована (lock_id={data.get('lock_id')})")
                return {
                    "success": True,
                    "lock_id": data.get("lock_id"),
                    "error": None,
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"[InventoryRepository] ✗ Ошибка блокировки: {error_msg}")
                return {"success": False, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def is_point_locked(self, point_name: str) -> Dict[str, Any]:
        """Проверяет заблокирована ли точка."""
        payload = {
            "point_name": point_name,
        }
        
        try:
            response = self._post("/api/inventory/is-point-locked", payload)
            if response is None:
                return {"locked": False, "error": "No response"}
            
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                print(f"[InventoryRepository] ⚠ HTTP {response.status_code} при проверке блокировки")
                return {"locked": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            print(f"[InventoryRepository] ⚠ Ошибка проверки блокировки: {e}")
            return {"locked": False, "error": str(e)}
    
    def unlock_point(self, lock_id: int) -> Dict[str, Any]:
        """Разблокирует точку по ID блокировки."""
        payload = {
            "lock_id": lock_id,
        }
        
        try:
            response = self._post("/api/inventory/unlock-point", payload)
            if response is None:
                return {"success": False, "error": "No response"}
            
            if response.status_code == 200:
                print(f"[InventoryRepository] 🔓 Точка разблокирована (lock_id={lock_id})")
                return {"success": True, "error": None}
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                return {"success": False, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def unlock_point_by_pending_id(self, pending_operation_id: int) -> Dict[str, Any]:
        """Разблокирует точку по ID pending операции."""
        payload = {
            "pending_operation_id": pending_operation_id,
        }
        
        try:
            response = self._post("/api/inventory/unlock-point-by-pending", payload)
            if response is None:
                return {"success": False, "unlocked": 0, "error": "No response"}
            
            if response.status_code == 200:
                data = response.json()
                print(f"[InventoryRepository] 🔓 Точка разблокирована (pending_id={pending_operation_id})")
                return {
                    "success": True,
                    "unlocked": data.get("unlocked", 0),
                    "error": None,
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                return {"success": False, "unlocked": 0, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            return {"success": False, "unlocked": 0, "error": str(e)}
    
    # ============================================================
    #  🆕 PENDING SMARTSHELL ОПЕРАЦИИ
    # ============================================================
    
    def save_pending_smartshell_operation(self, plan: Dict, session_info: Dict,
                                           error_details: str, point_name: str,
                                           administrator: str) -> Dict[str, Any]:
        """Сохраняет операцию которая не применилась в SmartShell."""
        print(f"\n[InventoryRepository] 💾 save_pending_smartshell_operation")
        print(f"  point: {point_name}, admin: {administrator}")
        
        payload = {
            "plan": plan,
            "session_info": session_info,
            "error_details": error_details,
            "point_name": point_name,
            "administrator": administrator,
        }
        
        try:
            response = self._post("/api/inventory/save-pending-operation", payload)
            if response is None:
                return {"success": False, "error": "No response"}
            
            if response.status_code == 200:
                data = response.json()
                print(f"[InventoryRepository] ✓ Pending операция сохранена (id={data.get('id')})")
                return {
                    "success": True,
                    "id": data.get("id"),
                    "error": None,
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"[InventoryRepository] ✗ Ошибка: {error_msg}")
                return {"success": False, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def get_pending_operations(self, limit: int = 10) -> List[Dict]:
        """Получает pending операции для повторной попытки."""
        payload = {
            "limit": limit,
        }
        
        try:
            response = self._post("/api/inventory/get-pending-operations", payload)
            if response is None:
                return []
            
            if response.status_code == 200:
                data = response.json()
                return data.get("operations", [])
            else:
                print(f"[InventoryRepository] ⚠ HTTP {response.status_code} при получении pending")
                return []
        except Exception as e:
            print(f"[InventoryRepository] ⚠ Ошибка получения pending: {e}")
            return []
    
    def mark_operation_success(self, operation_id: int) -> Dict[str, Any]:
        """Отмечает операцию как успешную."""
        payload = {
            "operation_id": operation_id,
        }
        
        try:
            response = self._post("/api/inventory/mark-operation-success", payload)
            if response is None:
                return {"success": False, "error": "No response"}
            
            if response.status_code == 200:
                return {"success": True, "error": None}
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                return {"success": False, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def mark_operation_failed(self, operation_id: int, reason: str) -> Dict[str, Any]:
        """Отмечает операцию как проваленную."""
        payload = {
            "operation_id": operation_id,
            "reason": reason,
        }
        
        try:
            response = self._post("/api/inventory/mark-operation-failed", payload)
            if response is None:
                return {"success": False, "error": "No response"}
            
            if response.status_code == 200:
                return {"success": True, "error": None}
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                return {"success": False, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def increment_retry_count(self, operation_id: int) -> Dict[str, Any]:
        """Увеличивает счётчик попыток."""
        payload = {
            "operation_id": operation_id,
        }
        
        try:
            response = self._post("/api/inventory/increment-retry-count", payload)
            if response is None:
                return {"success": False, "error": "No response"}
            
            if response.status_code == 200:
                return {"success": True, "error": None}
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                return {"success": False, "error": error_msg}
        except Exception as e:
            print(f"[InventoryRepository] ✗ Exception: {e}")
            return {"success": False, "error": str(e)}