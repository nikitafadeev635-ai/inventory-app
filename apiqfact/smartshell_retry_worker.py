"""
Фоновый процесс для повторного применения зависших операций SmartShell.

ЗАПУСКАЕТСЯ НА СЕРВЕРЕ (не на клиенте!):
    python -m apiqfact.smartshell_retry_worker

Логика:
- Каждые 5 минут проверяет таблицу pending_smartshell_operations
- Пытается применить операции в SmartShell (до 10 попыток)
- При успехе: разблокирует точку, помечает как success
- При провале 10 попыток: отправляет критический алерт руководителю

Установка как сервис:
    /etc/systemd/system/inventory-retry.service
"""
import sys
import os
import time
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime

# Настройка путей для сервера
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "logs" / "retry_worker.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("retry_worker")

# Импортируем серверные функции из main.py
from main import (
    _get_pending_operations_on_server,
    _mark_operation_status_on_server,
    _unlock_point_by_pending_id_on_server,
    send_telegram_alert,
    change_quantity_ss,
    WAREHOUSE_IDS,
)


class SmartShellRetryWorker:
    """Worker для повторных попыток применения операций в SmartShell."""
    
    MAX_RETRIES = 10
    CHECK_INTERVAL = 300  # 5 минут
    
    def process_pending_operations(self):
        """Обрабатывает все pending операции."""
        pending = _get_pending_operations_on_server(limit=10)
        
        if not pending:
            return
        
        logger.info(f"🔄 Найдено {len(pending)} pending операций")
        
        for operation in pending:
            self._process_single_operation(operation)
    
    def _process_single_operation(self, operation: dict):
        """Обрабатывает одну pending операцию."""
        operation_id = operation["id"]
        retry_count = operation["retry_count"]
        point_name = operation["point_name"]
        
        # Превышен лимит попыток
        if retry_count >= self.MAX_RETRIES:
            logger.warning(f"⚠ Операция {operation_id}: превышен лимит ({self.MAX_RETRIES})")
            
            _mark_operation_status_on_server(
                operation_id,
                "failed",
                f"Max retries ({self.MAX_RETRIES}) exceeded"
            )
            
            self._send_critical_alert(operation, f"Превышен лимит {self.MAX_RETRIES} попыток")
            return
        
        logger.info(f"🔄 Попытка {retry_count + 1}/{self.MAX_RETRIES} "
                    f"для операции {operation_id} ({point_name})")
        
        try:
            plan = json.loads(operation["plan_json"])
            
            # Пытаемся применить
            success = self._apply_operations(plan, point_name)
            
            if success:
                # ✅ УСПЕХ
                _mark_operation_status_on_server(operation_id, "success")
                logger.info(f"✅ Операция {operation_id} применена (попытка {retry_count + 1})")
                
                # 🔓 Разблокируем точку
                unlock_result = _unlock_point_by_pending_id_on_server(operation_id)
                if unlock_result.get("unlocked", 0) > 0:
                    logger.info(f"🔓 Точка {point_name} разблокирована")
                
                # Уведомление об успехе
                self._send_success_alert(operation, retry_count + 1)
            else:
                # ❌ НЕУДАЧА
                _mark_operation_status_on_server(operation_id, "increment")
                logger.warning(f"❌ Операция {operation_id}: не применена")
            
            # Пауза между операциями
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"✗ Ошибка обработки {operation_id}: {e}")
            import traceback
            traceback.print_exc()
            _mark_operation_status_on_server(operation_id, "increment")
    
    def _apply_operations(self, plan: dict, point_name: str) -> bool:
        """Применяет операции в SmartShell. Возвращает True если всё успешно."""
        warehouse_id = WAREHOUSE_IDS.get(point_name)
        if not warehouse_id:
            logger.warning(f"⚠ Неизвестная точка: {point_name}")
            return False
        
        operations = plan.get("operations", [])
        disposals = [op for op in operations if op.get("type") == "DISPOSAL"]
        additions = [op for op in operations if op.get("type") == "ADD"]
        
        def _format_items(ops):
            items = []
            for op in ops:
                items.append({
                    "id": op.get("product_id"),
                    "quantity": op.get("quantity", 1),
                    "title": op.get("product_title", ""),
                })
            return items
        
        async def _apply():
            total_failed = 0
            
            if disposals:
                disposal_items = _format_items(disposals)
                ss_result = await change_quantity_ss(warehouse_id, disposal_items, "DISPOSAL")
                total_failed += ss_result.get("failed_items", 0)
            
            if additions:
                addition_items = _format_items(additions)
                ss_result = await change_quantity_ss(warehouse_id, addition_items, "ADD")
                total_failed += ss_result.get("failed_items", 0)
            
            return total_failed == 0
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_apply())
            loop.close()
            return result
        except Exception as e:
            logger.error(f"✗ Ошибка применения: {e}")
            return False
    
    def _send_critical_alert(self, operation: dict, reason: str):
        """Отправляет критический алерт руководителю."""
        try:
            plan = json.loads(operation["plan_json"])
            operations_count = len(plan.get("operations", []))
            
            alert_message = (
                f"🚨 <b>КРИТИЧЕСКАЯ ОШИБКА СИНХРОНИЗАЦИИ!</b>\n\n"
                f"🏪 <b>Точка:</b> {operation['point_name']}\n"
                f"👤 <b>Админ:</b> {operation['administrator']}\n"
                f"📦 <b>Операций:</b> {operations_count}\n"
                f"🆔 <b>Pending ID:</b> {operation['id']}\n"
                f"🔄 <b>Попыток:</b> {operation['retry_count']}\n"
                f"❌ <b>Причина:</b> {reason}\n"
                f"🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                f"<b>⚠️ Точка заблокирована!</b>\n"
                f"Требуется ручное вмешательство."
            )
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(send_telegram_alert(alert_message))
            loop.close()
            
            logger.info("🚨 Критический алерт отправлен")
        except Exception as e:
            logger.error(f"✗ Не удалось отправить алерт: {e}")
    
    def _send_success_alert(self, operation: dict, attempt: int):
        """Отправляет уведомление об успешной синхронизации."""
        try:
            plan = json.loads(operation["plan_json"])
            operations_count = len(plan.get("operations", []))
            
            alert_message = (
                f"✅ <b>СИНХРОНИЗАЦИЯ УСПЕШНА</b>\n\n"
                f"🏪 <b>Точка:</b> {operation['point_name']}\n"
                f"👤 <b>Админ:</b> {operation['administrator']}\n"
                f"📦 <b>Операций применено:</b> {operations_count}\n"
                f"🔄 <b>Попыток потребовалось:</b> {attempt}\n"
                f"🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                f"🔓 <b>Точка разблокирована</b>"
            )
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(send_telegram_alert(alert_message))
            loop.close()
            
            logger.info("✅ Уведомление об успехе отправлено")
        except Exception as e:
            logger.error(f"✗ Не удалось отправить уведомление: {e}")


def run_retry_worker():
    """Запускает worker в бесконечном цикле."""
    print("=" * 60)
    print("🚀 SmartShell Retry Worker запущен (СЕРВЕР)")
    print("=" * 60)
    print(f"PID: {os.getpid()}")
    print(f"Старт: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print(f"Интервал: {SmartShellRetryWorker.CHECK_INTERVAL // 60} минут")
    print("=" * 60)
    
    worker = SmartShellRetryWorker()
    cycle = 0
    
    while True:
        cycle += 1
        try:
            logger.info(f"=== Цикл #{cycle} ===")
            worker.process_pending_operations()
        except KeyboardInterrupt:
            logger.info("⛔ Остановка по Ctrl+C")
            break
        except Exception as e:
            logger.error(f"✗ Ошибка цикла #{cycle}: {e}")
            import traceback
            traceback.print_exc()
        
        try:
            time.sleep(SmartShellRetryWorker.CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("⛔ Остановка во время ожидания")
            break
    
    logger.info("Завершён")


if __name__ == "__main__":
    run_retry_worker()