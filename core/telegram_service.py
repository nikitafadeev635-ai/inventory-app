"""
Сервис отправки уведомлений в Telegram.

Поддерживает:
- Текстовые сообщения (send-ref-state)
- PDF-документы с подписью (send-ref-state-with-pdf)
"""
import httpx
import os
from pathlib import Path
from config import PROXY_SERVER_URL, API_SECRET_KEY

# 🆕 Импорт для HWID и Hash
try:
    from core.integrity_checker import get_exe_hash, get_hardware_id
    _INTEGRITY_AVAILABLE = True
except ImportError:
    _INTEGRITY_AVAILABLE = False
    get_exe_hash = lambda: ""
    get_hardware_id = lambda: ""


class TelegramService:
    def __init__(self):
        self.base_url = f"{PROXY_SERVER_URL}/api/telegram"
        
        # 🆕 Вычисляем HWID и Hash один раз
        self._client_hash = ""
        self._client_hwid = ""
        if _INTEGRITY_AVAILABLE:
            try:
                self._client_hash = get_exe_hash() or ""
                self._client_hwid = get_hardware_id() or ""
            except Exception as e:
                print(f"[Telegram] ⚠ Ошибка HWID/Hash: {e}")
        
        # 🆕 Базовые заголовки с HWID/Hash
        self.headers_base = {
            "X-API-Key": API_SECRET_KEY,
        }
        
        if self._client_hash:
            self.headers_base["X-Client-Hash"] = self._client_hash
        if self._client_hwid:
            self.headers_base["X-Client-HWID"] = self._client_hwid

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
        pdf_path: str = None,
        check_value: float = 0.0,
        pay_value: float = 0.0,
        all_ref: list = None,
    ) -> dict:
        """Отправляет отчёт с финансовой разбивкой."""
        # Формируем текст СТРОГО ПО ШАБЛОНУ
        lines = [
            f"{date_str} {administrator}",
            f"{total_types} видов, {total_items} позиций, {total_value:.2f}₽",
            f"Предварительный минус: {total_value:.2f}₽",
        ]
        
        if items_on_check > 0:
            lines.append(f"Товары на проверке: {check_value:.2f}₽ ({items_on_check} шт)")
        else:
            lines.append(f"Товары на проверке: 0.00₽ (0 шт)")
        
        lines.append(f"К возмещению: {pay_value:.2f}₽")
        lines.append("")
        lines.append("Ссылки:")
        
        if all_ref:
            for ref in all_ref:
                title = ref.get("product_title") or "Товар"
                qty = ref.get("quantity", 0)
                link = ref.get("reference") or "—"
                lines.append(f"• {title} ({qty} шт): {link}")
        else:
            lines.append("—")
        
        message = "\n".join(lines)
        
        print(f"[Telegram] 📝 Финальный текст:\n{'─'*40}")
        print(message)
        print(f"{'─'*40}")
        
        if pdf_path and os.path.exists(pdf_path):
            return self._send_with_pdf(point_name, message, pdf_path)
        else:
            return self._send_text_only(point_name, message)

    def _send_text_only(self, point_name: str, message: str) -> dict:
        """Отправка текстового сообщения."""
        payload = {
            "point_name": point_name,
            "message": message,
            "parse_mode": "HTML",
        }
        
        try:
            headers = {**self.headers_base, "Content-Type": "application/json"}
            with httpx.Client(timeout=15.0, verify=False) as http:
                r = http.post(
                    f"{self.base_url}/send-ref-state",
                    headers=headers,
                    json=payload,
                )
                r.raise_for_status()
                result = r.json()
                print(f"[Telegram] ✓ Текстовый отчёт отправлен в топик {point_name}")
                return {"success": True, "message_id": result.get("message_id")}
        except Exception as e:
            print(f"[Telegram] ✗ Ошибка отправки текста: {e}")
            return {"success": False, "error": str(e)}

    def _send_with_pdf(self, point_name: str, message: str, pdf_path: str) -> dict:
        """Отправка PDF с подписью (caption)."""
        try:
            pdf_name = Path(pdf_path).name
            with open(pdf_path, "rb") as f:
                files = {
                    "pdf_file": (pdf_name, f, "application/pdf"),
                }
                data = {
                    "point_name": point_name,
                    "message": message,
                    "parse_mode": "HTML",
                }
                
                # 🆕 Используем headers_base который содержит HWID/Hash
                # НЕ добавляем Content-Type — httpx сам поставит для multipart
                with httpx.Client(timeout=60.0, verify=False) as http:
                    r = http.post(
                        f"{self.base_url}/send-ref-state-with-pdf",
                        headers=self.headers_base,
                        data=data,
                        files=files,
                    )
                    r.raise_for_status()
                    result = r.json()
                    if result.get("success"):
                        size_kb = result.get("file_size", 0) / 1024
                        print(
                            f"[Telegram] ✓ PDF ({size_kb:.1f} KB) отправлен "
                            f"в топик {point_name}"
                        )
                        if result.get("caption_truncated"):
                            print("[Telegram] ⚠ Caption был обрезан до 1024 символов")
                        return {"success": True, "message_id": result.get("message_id")}
                    else:
                        print(f"[Telegram] ✗ VPS вернул ошибку: {result.get('error')}")
                        return result
        except Exception as e:
            print(f"[Telegram] ✗ Ошибка отправки PDF: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}