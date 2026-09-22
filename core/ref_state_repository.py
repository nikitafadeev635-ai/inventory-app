"""
Репозиторий для работы с таблицами refStateGeneral и refStateDetailed.
Сохраняет отчёты о товарах на ручной проверке (с ссылками-подтверждениями).
"""
import httpx
from datetime import datetime
from config import PROXY_SERVER_URL, API_SECRET_KEY


class RefStateRepository:
    def __init__(self):
        self.base_url = f"{PROXY_SERVER_URL}/api/ref-state"
        self.headers = {
            "X-API-Key": API_SECRET_KEY,  # ✅ ИСПРАВЛЕНО: было X-API-Secret
            "Content-Type": "application/json",
        }
    
    def save_general(self, data: dict) -> dict:
        """
        Сохраняет общую запись в refStateGeneral.
        
        Args:
            data: {
                "point_name": str,
                "administrator": str,
                "session_label": str,
                "total_types": int,
                "total_items": int,
                "total_value": float,
                "items_on_check": int,
                "links_count": int,
                "pdf_path": str,
            }
        
        Returns:
            {"success": bool, "id": int, "error": str}
        """
        try:
            with httpx.Client(timeout=15.0, verify=False) as http:
                r = http.post(
                    f"{self.base_url}/general",
                    headers=self.headers,
                    json=data,
                )
                
                if r.status_code == 200:
                    result = r.json()
                    if result.get("success"):
                        print(f"[RefState] ✓ general сохранён (id={result.get('id')})")
                        return {"success": True, "id": result.get("id")}
                    else:
                        print(f"[RefState] ✗ Сервер вернул ошибку: {result}")
                        return {"success": False, "error": str(result)}
                
                elif r.status_code == 401:
                    print(f"[RefState] ✗ Ошибка авторизации: неверный API key")
                    return {"success": False, "error": "unauthorized"}
                
                elif r.status_code == 422:
                    print(f"[RefState] ✗ Ошибка валидации: {r.text[:200]}")
                    return {"success": False, "error": f"validation: {r.text[:200]}"}
                
                else:
                    print(f"[RefState] ✗ HTTP {r.status_code}: {r.text[:200]}")
                    return {"success": False, "error": f"http_{r.status_code}"}
        
        except httpx.TimeoutException:
            print(f"[RefState] ✗ Таймаут при сохранении general")
            return {"success": False, "error": "timeout"}
        except Exception as e:
            print(f"[RefState] ✗ Ошибка сохранения general: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def save_detailed(self, general_id: int, items: list) -> dict:
        """
        Сохраняет детализацию (каждая ссылка по товару) в refStateDetailed.
        
        Args:
            general_id: ID из refStateGeneral
            items: list of {
                "administrator": str,
                "product_title": str,
                "product_id": int,
                "reference": str,
                "quantity": int,
                "value": float,
                "reason": str,
            }
        
        Returns:
            {"success": bool, "inserted": int, "error": str}
        """
        if not items:
            return {"success": True, "inserted": 0}
        
        payload = {
            "general_id": general_id,
            "items": items,
        }
        
        try:
            with httpx.Client(timeout=30.0, verify=False) as http:
                r = http.post(
                    f"{self.base_url}/detailed",
                    headers=self.headers,
                    json=payload,
                )
                
                if r.status_code == 200:
                    result = r.json()
                    if result.get("success"):
                        print(f"[RefState] ✓ detailed сохранён ({result.get('inserted', 0)} записей)")
                        return {"success": True, "inserted": result.get("inserted", 0)}
                    else:
                        print(f"[RefState] ✗ Сервер вернул ошибку: {result}")
                        return {"success": False, "error": str(result)}
                
                elif r.status_code == 401:
                    print(f"[RefState] ✗ Ошибка авторизации: неверный API key")
                    return {"success": False, "error": "unauthorized"}
                
                elif r.status_code == 422:
                    print(f"[RefState] ✗ Ошибка валидации: {r.text[:200]}")
                    return {"success": False, "error": f"validation: {r.text[:200]}"}
                
                else:
                    print(f"[RefState] ✗ HTTP {r.status_code}: {r.text[:200]}")
                    return {"success": False, "error": f"http_{r.status_code}"}
        
        except httpx.TimeoutException:
            print(f"[RefState] ✗ Таймаут при сохранении detailed")
            return {"success": False, "error": "timeout"}
        except Exception as e:
            print(f"[RefState] ✗ Ошибка сохранения detailed: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}