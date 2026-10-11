"""
Модуль нормализации товаров после пересменки.

v4.1 — Разделение на планирование и применение + исправления:
- prepare_normalization_plan() — формирует план БЕЗ обращения к SmartShell
  (включает "reason": "" для совместимости с VPS моделью NormalizeOperation)
- apply_normalization_plan() — применяет план в SmartShell (атомарно)
- verify_application() — автоматическая пост-верификация
- sync_products_to_db() — ОТКЛЮЧЁН (БД на VPS, локальная не нужна)

Это позволяет сначала записать все данные в БД и сформировать отчёт,
и только потом применять изменения в SmartShell.
"""
from typing import List, Dict, Any
from dataclasses import dataclass

from core.session import current_session


# ============================================================
#  ПРИЧИНЫ РАСХОЖДЕНИЙ (используются в TroubleDialog)
#  ⚠️ ВАЖНО: написания должны совпадать в REASONS_LESS и EXCUSABLE_REASONS_LESS
# ============================================================
REASONS_LESS = [
    "Не знаю",                        # ⚠️ обязательна ссылка
    "Товар украден",                  # ⚠️ обязательна ссылка + уважительная
    "Не прошла корректно оплата",     # ⚠️ обязательна ссылка + уважительная
    "Просрочка",                      # ⚠️ обязательна ссылка + уважительная
    "Съел",                           # ✅ ссылка не нужна
    "Не хочу разбираться",            # ✅ ссылка не нужна
]

REASONS_MORE = [
    "Не знаю откуда плюс - недовнёс бот",
    "Не знаю откуда плюс - недовнёс шелл",
    "Не знаю откуда плюс - может я даун",
]

# ============================================================
#  УВАЖИТЕЛЬНЫЕ ПРИЧИНЫ (идут "на проверку")
#  ⚠️ НАПИСАНИЕ ДОЛЖНО ТОЧНО СОВПАДАТЬ С REASONS_LESS / REASONS_MORE
# ============================================================
EXCUSABLE_REASONS_LESS = {
    "Товар украден",
    "Не прошла корректно оплата",
    "Просрочка",
}

EXCUSABLE_REASONS_MORE = {
    "Не знаю откуда плюс - недовнёс бот",
    "Не знаю откуда плюс - недовнёс шелл",
    "Не знаю откуда плюс - может я даун",
}

# Все уважительные причины (объединённые)
ALL_EXCUSABLE_REASONS = EXCUSABLE_REASONS_LESS | EXCUSABLE_REASONS_MORE

@dataclass
class DiscrepancyItem:
    """Один товар с расхождением."""
    product_id: int
    title: str
    stock: int
    actual: int
    delta: int
    status: str
    cost: float
    reason: str = ""


class NormalizationService:
    """
    Сервис нормализации товаров.
    
    v4.1: Двухфазная архитектура:
    1. prepare_normalization_plan() — формирует план БЕЗ SmartShell
    2. apply_normalization_plan() — применяет в SmartShell (атомарно)
    3. verify_application() — автоматическая пост-верификация
    """

    def __init__(self, client):
        self.client = client

    def get_discrepancies(self, products: list) -> List[DiscrepancyItem]:
        """Извлекает товары с расхождениями из списка."""
        items = []
        for p in products:
            if p.actual is None:
                continue
            if p.status == "less":
                items.append(DiscrepancyItem(
                    product_id=p.id,
                    title=p.title,
                    stock=p.stock,
                    actual=p.actual,
                    delta=p.actual - p.stock,
                    status="less",
                    cost=p.cost,
                ))
            elif p.status == "more":
                items.append(DiscrepancyItem(
                    product_id=p.id,
                    title=p.title,
                    stock=p.stock,
                    actual=p.actual,
                    delta=p.actual - p.stock,
                    status="more",
                    cost=p.cost,
                ))
        return items

    def prepare_normalization_plan(self, items: List[DiscrepancyItem]) -> Dict:
        """
        🆕 ФАЗА 1: Формирует план нормализации БЕЗ обращения к SmartShell.
        
        Это позволяет:
        - Показать план администратору для подтверждения
        - Пройти TroubleDialog для указания причин
        - Записать все данные в БД
        - Сформировать PDF отчёт
        - И только ПОТОМ применять изменения в SmartShell
        
        Returns:
            {
                "operations": [
                    {"product_id", "product_title", "delta", "type", "quantity", "reason"},
                    ...
                ],
                "total": int,
                "disposals": int,
                "additions": int,
                "actuals_before": {product_id: stock_before, ...},
                "success": int,
                "failed": 0,
                "errors": [],
            }
        """
        operations = []
        actuals_before = {}
        
        for item in items:
            operation_type = "DISPOSAL" if item.status == "less" else "ADD"
            operations.append({
                "product_id": item.product_id,
                "product_title": item.title,
                "delta": item.delta,
                "type": operation_type,
                "quantity": abs(item.delta),
                "reason": "",  # 🆕 ИСПРАВЛЕНО: пустая причина для совместимости с VPS
                              # (Pydantic модель NormalizeOperation требует это поле)
                              # Реальная причина заполняется позже в TroubleDialog
            })
            actuals_before[item.product_id] = item.stock
        
        disposals = [op for op in operations if op["type"] == "DISPOSAL"]
        additions = [op for op in operations if op["type"] == "ADD"]
        
        print(f"\n{'='*60}")
        print(f"[Normalization] 📋 ПЛАН НОРМАЛИЗАЦИИ (без применения):")
        print(f"  Всего операций: {len(operations)}")
        print(f"  DISPOSAL: {len(disposals)} товаров")
        for op in disposals:
            print(f"    • {op['product_title']} (id={op['product_id']}, delta={op['delta']})")
        print(f"  ADD: {len(additions)} товаров")
        for op in additions:
            print(f"    • {op['product_title']} (id={op['product_id']}, delta={op['delta']})")
        print(f"{'='*60}\n")
        
        return {
            "operations": operations,
            "total": len(operations),
            "disposals": len(disposals),
            "additions": len(additions),
            "actuals_before": actuals_before,
            "success": len(operations),  # всё запланировано
            "failed": 0,
            "errors": [],
        }

    def apply_normalization_plan(self, plan: dict, session_info: dict = None) -> dict:
        """
        Применяет план нормализации в SmartShell с retry-логикой.
        
        Retry на уровне ПАКЕТОВ: если пакет не прошёл — повторяем ВЕСЬ пакет.
        4 попытки с интервалом 5 секунд.
        
        Args:
            plan: План нормализации с операциями
            session_info: Информация о сессии (для логирования)
        
        Returns:
            dict: Результат применения
        """
        operations = plan.get("operations", [])
        if not operations:
            return {
                "success": True,
                "total": 0,
                "success_count": 0,
                "failed": 0,
                "errors": []
            }
        
        # Группируем операции по типам
        disposals = [op for op in operations if op.get("type") == "DISPOSAL"]
        additions = [op for op in operations if op.get("type") == "ADD"]
        
        print(f"\n[Normalization] 🚀 ПРИМЕНЕНИЕ ПЛАНА В SMARTSHELL:")
        print(f"  {len(operations)} операций")
        
        all_results = {
            "success": True,
            "total": len(operations),
            "success_count": 0,
            "failed": 0,
            "errors": [],
            "ss_request_count": 0,
            "retry_details": [],
        }
        
        MAX_RETRIES = 4
        RETRY_DELAY = 5  # секунд
        
        # === Обрабатываем DISPOSAL с retry ===
        if disposals:
            print(f"[Normalization] 📉 DISPOSAL: {len(disposals)} товаров")
            disposal_result = self._apply_batch_with_retry(
                disposals, "DISPOSAL", MAX_RETRIES, RETRY_DELAY
            )
            all_results["success_count"] += disposal_result.get("success_count", 0)
            all_results["failed"] += disposal_result.get("failed", 0)
            all_results["errors"].extend(disposal_result.get("errors", []))
            all_results["ss_request_count"] += disposal_result.get("ss_request_count", 0)
            all_results["retry_details"].append({
                "type": "DISPOSAL",
                "attempts": disposal_result.get("attempts", 1),
                "final_status": "success" if disposal_result.get("failed", 0) == 0 else "failed"
            })
        
        # === Обрабатываем ADD с retry ===
        if additions:
            print(f"[Normalization] 📈 ADD: {len(additions)} товаров")
            addition_result = self._apply_batch_with_retry(
                additions, "ADD", MAX_RETRIES, RETRY_DELAY
            )
            all_results["success_count"] += addition_result.get("success_count", 0)
            all_results["failed"] += addition_result.get("failed", 0)
            all_results["errors"].extend(addition_result.get("errors", []))
            all_results["ss_request_count"] += addition_result.get("ss_request_count", 0)
            all_results["retry_details"].append({
                "type": "ADD",
                "attempts": addition_result.get("attempts", 1),
                "final_status": "success" if addition_result.get("failed", 0) == 0 else "failed"
            })
        
        # === Итоговый результат ===
        all_results["success"] = (all_results["failed"] == 0)
        
        print(f"[Normalization] ✅ Результат SmartShell: "
            f"✓ {all_results['success_count']} успешно, "
            f"✗ {all_results['failed']} ошибок")
        
        if disposals:
            disp_detail = next((d for d in all_results["retry_details"] if d["type"] == "DISPOSAL"), None)
            print(f"  📊 DISPOSAL: {len(disposals)}/{len(disposals)} товаров "
                f"({disp_detail['attempts']} попыток)")
        if additions:
            add_detail = next((d for d in all_results["retry_details"] if d["type"] == "ADD"), None)
            print(f"  📊 ADD: {len(additions)}/{len(additions)} товаров "
                f"({add_detail['attempts']} попыток)")
        
        return all_results


    def _apply_batch_with_retry(self, operations: list, operation_type: str,
                                max_retries: int = 4, retry_delay: int = 5) -> dict:
        """
        Применяет пакет операций с retry-логикой.
        
        Если пакет не прошёл — повторяем ВЕСЬ пакет целиком.
        НЕ делим на успешные/неуспешные товары.
        
        Args:
            operations: Список операций для применения
            operation_type: Тип операции ("DISPOSAL" или "ADD")
            max_retries: Максимальное количество попыток (по умолчанию 4)
            retry_delay: Задержка между попытками в секундах
        
        Returns:
            dict: {
                "success_count": int,
                "failed": int,
                "errors": list,
                "attempts": int,  # Сколько попыток потребовалось
                "ss_request_count": int
            }
        """
        import time
        
        last_result = None
        
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                print(f"[Normalization] 🔄 Попытка {attempt}/{max_retries} "
                    f"(через {retry_delay}с)...")
                time.sleep(retry_delay)
            
            # Применяем ВЕСЬ пакет целиком
            result = self._apply_operations_batch(operations, operation_type)
            last_result = result
            
            # Если все операции успешны — выходим
            if result.get("failed", 0) == 0:
                if attempt > 1:
                    print(f"[Normalization] ✅ Пакет {operation_type} "
                        f"успешно применён на попытке {attempt}")
                return {
                    "success_count": len(operations),
                    "failed": 0,
                    "errors": [],
                    "attempts": attempt,
                    "ss_request_count": result.get("ss_request_count", 1)
                }
            
            # Если есть ошибки — логируем и пробуем снова
            print(f"[Normalization] ⚠️ Попытка {attempt}/{max_retries}: "
                f"✗ {result.get('failed', 0)} ошибок в пакете {operation_type}")
        
        # Все попытки исчерпаны — возвращаем последнюю неудачную попытку
        print(f"[Normalization] ❌ Все {max_retries} попытки исчерпаны для {operation_type}")
        return {
            "success_count": result.get("success", 0),
            "failed": result.get("failed", len(operations)),
            "errors": result.get("errors", []),
            "attempts": max_retries,
            "ss_request_count": result.get("ss_request_count", max_retries)
        }


    def _apply_operations_batch(self, operations: list, operation_type: str) -> dict:
        """
        Применяет пакет операций ОДИН раз (без retry).
        
        Это обёртка над существующей логикой SmartShell.
        
        Args:
            operations: Список операций
            operation_type: "DISPOSAL" или "ADD"
        
        Returns:
            dict: Результат применения
        """
        # Формируем items для SmartShell
        items = []
        for op in operations:
            items.append({
                "id": op.get("product_id"),
                "quantity": op.get("quantity", 1),
                "title": op.get("product_title", ""),
            })
        
        # Вызываем существующую функцию SmartShell
        # Это должна быть твоя текущая функция которая делает GraphQL-запрос
        result = self._apply_to_smartshell(items, operation_type)
        
        return result


    def _apply_to_smartshell(self, items: list, operation: str) -> dict:
        """
        Отправляет пакет товаров в SmartShell через GraphQL.
        
        Это ТВОЯ СУЩЕСТВУЮЩАЯ логика отправки в SmartShell.
        Перенеси её сюда из текущего apply_normalization_plan.
        """
        # Скопируй сюда код который у тебя сейчас в apply_normalization_plan
        # который делает change_quantity_ss или аналогичный вызов
        
        # Пример (замени на свой реальный код):
        from core.api_client import change_quantity_ss
        from config import SMARTSHELL_WAREHOUSE_IDS
        from core.session import current_session
        
        warehouse_id = SMARTSHELL_WAREHOUSE_IDS.get(current_session.point_name)
        if not warehouse_id:
            return {
                "success": False,
                "failed": len(items),
                "errors": ["Unknown warehouse_id"]
            }
        
        result = change_quantity_ss(warehouse_id, items, operation)
        
        return {
            "success": result.get("successful_items", 0),
            "failed": result.get("failed_items", 0),
            "errors": result.get("errors", []),
            "ss_request_count": result.get("ss_request_count", 1)
        }

    def verify_application(self, plan: Dict) -> Dict:
        """
        🆕 ФАЗА 3: Умная пост-верификация применения в SmartShell.
        
        Получает СВЕЖИЕ данные из SmartShell (минуя кеш!) и сравнивает
        текущий stock с ОЖИДАЕМЫМ stock после применения.
        
        Returns:
            {"all_ok": bool, "total": int, "verified": int, "failed": int, "failed_items": [...]}
        """
        print(f"\n[Normalization] 🔍 Пост-верификация применения в SmartShell...")
        
        # Получаем СВЕЖИЕ данные напрямую из SmartShell
        try:
            fresh_items = self.client.fetch_goods("")
            from items.product import Product
            fresh_products = [Product.from_api(i) for i in fresh_items]
            fresh_by_id = {p.id: p for p in fresh_products}
        except Exception as e:
            print(f"[Normalization] ⚠ Не удалось получить свежие данные: {e}")
            return {
                "all_ok": False, 
                "total": len(plan.get("operations", [])),
                "verified": 0, 
                "failed": len(plan.get("operations", [])),
                "failed_items": [],
                "error": "Не удалось получить данные из SmartShell"
            }
        
        verified = 0
        failed_items = []
        
        for op in plan.get("operations", []):
            product_id = op["product_id"]
            fresh_product = fresh_by_id.get(product_id)
            
            if not fresh_product:
                failed_items.append({
                    "product_id": product_id,
                    "product_title": op.get("product_title", "?"),
                    "expected": "товар не найден",
                    "actual_stock": "N/A",
                })
                continue
            
            # Ожидаемый stock после применения
            stock_before = plan["actuals_before"].get(product_id, 0)
            expected_stock = stock_before + op["delta"]
            actual_stock = fresh_product.stock
            
            # Проверка: current stock == expected stock?
            if actual_stock == expected_stock:
                verified += 1
            else:
                failed_items.append({
                    "product_id": product_id,
                    "product_title": op.get("product_title", "?"),
                    "expected": expected_stock,
                    "actual_stock": actual_stock,
                    "delta_expected": op["delta"],
                    "delta_actual": actual_stock - stock_before,
                })
        
        result = {
            "all_ok": len(failed_items) == 0,
            "total": len(plan.get("operations", [])),
            "verified": verified,
            "failed": len(failed_items),
            "failed_items": failed_items,
        }
        
        if result["all_ok"]:
            print(f"[Normalization] ✅ Все {verified} операций применены корректно")
        else:
            print(f"[Normalization] ⚠ {len(failed_items)} операций требуют проверки:")
            for item in failed_items[:10]:
                print(f"    • {item['product_title']}: "
                      f"ожидалось {item['expected']}, в SmartShell {item['actual_stock']}")
        
        return result

    # ============================================================
    #  УСТАРЕВШИЕ МЕТОДЫ (для обратной совместимости)
    # ============================================================
    def execute_normalization(self, items: List[DiscrepancyItem]) -> Dict:
        """@deprecated — используйте prepare_normalization_plan + apply_normalization_plan"""
        return self.prepare_normalization_plan(items)

    def sync_products_to_db(self, products: list):
        """
        Синхронизирует список товаров в локальную таблицу точки.
        
        ⚠️ ОТКЛЮЧЕНО: БД находится на VPS, локальная синхронизация не нужна.
        Все данные сохраняются через InventoryRepository → VPS API.
        
        Раньше этот метод пытался импортировать DB_HOST из config.py,
        что вызывало ошибку "cannot import name 'DB_HOST' from 'config'".
        Теперь просто pass.
        """
        # Локальная БД не используется — все данные на VPS
        pass