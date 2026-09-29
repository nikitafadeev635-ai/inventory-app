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

    def apply_normalization_plan(self, plan: Dict, session_info: dict) -> Dict:
        """
        🆕 ФАЗА 2: Применяет план в SmartShell (атомарно, пакетно).
        
        Вызывается ТОЛЬКО после того как:
        - Пройден TroubleDialog
        - Все данные записаны в БД
        - Сформирован PDF отчёт
        - Программа заблокирована от закрытия
        
        Returns:
            Результат от VPS (success/failed/chunks_info/operations)
        """
        operations = plan.get("operations", [])
        if not operations:
            return {"success": 0, "failed": 0, "errors": [], "operations": []}
        
        print(f"\n[Normalization] 🚀 ПРИМЕНЕНИЕ ПЛАНА В SMARTSHELL:")
        print(f"  {len(operations)} операций")
        
        response = self.client.normalize(
            operations=operations,
            session_info=session_info,
            giver=current_session.giver,
            receiver=current_session.receiver,
            point_name=current_session.point_name,
        )
        
        # Обогащаем операции статусом успеха
        response_errors = response.get("errors", [])
        operations_list = response.get("operations", [])
        
        successful_ids = set()
        if operations_list and isinstance(operations_list, list):
            for op in operations_list:
                if isinstance(op, dict) and op.get("success", True):
                    successful_ids.add(op.get("product_id"))
        else:
            # Fallback: если VPS не вернул operations, считаем все успешными при отсутствии failed
            if response.get("failed", 0) == 0 and response.get("success", 0) > 0:
                successful_ids = {op["product_id"] for op in operations}
        
        enriched_ops = []
        for op in operations:
            enriched_ops.append({
                **op,
                "success": op["product_id"] in successful_ids,
                "expected_stock": plan["actuals_before"].get(op["product_id"], 0) + op["delta"],
            })
        
        response["operations"] = enriched_ops
        
        chunks_info = response.get("chunks_info", {})
        disposal_info = chunks_info.get("disposal") if isinstance(chunks_info, dict) else None
        add_info = chunks_info.get("add") if isinstance(chunks_info, dict) else None
        
        print(f"[Normalization] ✅ Результат SmartShell: "
              f"✓ {response.get('success', 0)} успешно, "
              f"✗ {response.get('failed', 0)} ошибок")
        
        if disposal_info and isinstance(disposal_info, dict):
            print(f"  📊 DISPOSAL: {disposal_info.get('successful_items', 0)}/"
                  f"{disposal_info.get('total_items', 0)} товаров")
        if add_info and isinstance(add_info, dict):
            print(f"  📊 ADD: {add_info.get('successful_items', 0)}/"
                  f"{add_info.get('total_items', 0)} товаров")
        
        return response

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