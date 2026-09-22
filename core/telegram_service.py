"""
Сервис отправки уведомлений в Telegram.
Отправляет отчёты о товарах на проверке в соответствующий топик филиала.
"""
import httpx
from config import PROXY_SERVER_URL, API_SECRET_KEY


class TelegramService:
    def __init__(self):
        self.base_url = f"{PROXY_SERVER_URL}/api/telegram"
        self.headers = {
            "X-API-Secret": API_SECRET_KEY,
            "Content-Type": "application/json",
        }
    
    def send_ref_state_report(
        self,
        point_name: str,
        administrator: str,
        date_str: str,
        total_types: int,
        total_items: int,
        total_value: float,
        items_on_check: int,
        references: list,
    ) -> dict:
        """
        Отправляет отчёт о товарах на проверке в Telegram.
        
        Формат сообщения:
            <Дата> <Отдающий смену>
            <Количество видов>, <количество позиций>, <общая цена минусов>
            Переданные товары на проверку: <количество>
            
            Ссылки:
            <ссылка1>
            <ссылка2>
        """
        # Формирование текста сообщения
        lines = [
            f"<b>{date_str}</b> {administrator}",
            f"<b>{total_types}</b> видов, <b>{total_items}</b> позиций, "
            f"<b>{total_value:.2f}₽</b>",
            f"Переданные товары на проверку: <b>{items_on_check}</b>",
            "",
            "<b>Ссылки:</b>",
        ]
        
        # Уникальные ссылки
        unique_refs = sorted(set(ref for ref in references if ref))
        for ref in unique_refs:
            lines.append(f"• {ref}")
        
        message = "\n".join(lines)
        
        payload = {
            "point_name": point_name,
            "message": message,
            "parse_mode": "HTML",
        }
        
        try:
            with httpx.Client(timeout=15.0, verify=False) as http:
                r = http.post(
                    f"{self.base_url}/send-ref-state",
                    headers=self.headers,
                    json=payload,
                )
                r.raise_for_status()
                result = r.json()
                print(f"[Telegram] ✓ Отчёт отправлен в топик {point_name}")
                return {"success": True, "message_id": result.get("message_id")}
        except Exception as e:
            print(f"[Telegram] ✗ Ошибка отправки: {e}")
            return {"success": False, "error": str(e)}