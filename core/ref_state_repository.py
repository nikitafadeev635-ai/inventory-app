"""
Репозиторий для работы с таблицами refStateGeneral и refStateDetailed.
Сохраняет отчёты о товарах на ручной проверке (с ссылками-подтверждениями).
"""
import httpx
from datetime import datetime
from config import PROXY_SERVER_URL, API_SECRET_KEY


class RefStateRepository:
    def __init__(self, client=None):
        self.client = client
        self.base_url = f"{PROXY_SERVER_URL}/api/ref-state"
        self.headers = {
            "X-API-Secret": API_SECRET_KEY,
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
                r.raise_for_status()
                result = r.json()
                print(f"[RefState] ✓ general сохранён (id={result.get('id')})")
                return {"success": True, "id": result.get("id")}
        except Exception as e:
            print(f"[RefState] ✗ Ошибка сохранения general: {e}")
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
                r.raise_for_status()
                result = r.json()
                print(f"[RefState] ✓ detailed сохранён ({result.get('inserted', 0)} записей)")
                return {"success": True, "inserted": result.get("inserted", 0)}
        except Exception as e:
            print(f"[RefState] ✗ Ошибка сохранения detailed: {e}")
            return {"success": False, "error": str(e)}