"""
Модель группы товаров (по бренду/производителю).

Группа объединяет варианты одного бренда (например, все вкусы HQD).
Позволяет админам считать "30 штук HQD" без разбивки по вкусам.
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional
from items.product import Product


@dataclass
class ProductGroup:
    """Группа товаров одного бренда."""
    
    name: str
    products: List[Product] = field(default_factory=list)
    expanded: bool = False
    
    # ============================================================
    #  АГРЕГАТЫ
    # ============================================================
    @property
    def total_stock(self) -> int:
        """Суммарный учёт по всем вкусам."""
        return sum(p.stock for p in self.products)
    
    @property
    def total_actual(self) -> Optional[int]:
        """
        Суммарный факт по всем вкусам.
        Возвращает None если ни один вкус не посчитан.
        """
        counted = [p.actual for p in self.products if p.actual is not None]
        if not counted:
            return None
        return sum(p.actual if p.actual is not None else 0 for p in self.products)
    
    @property
    def delta(self) -> Optional[int]:
        """Разница между фактом и учётом."""
        if self.total_actual is None:
            return None
        return self.total_actual - self.total_stock

    def get_delta_by_status(self) -> dict:
        """
        Возвращает сумму дельт в денежном эквиваленте по типам.
        
        Для недостачи (less) — это деньги, которые нужно удержать.
        Для избытка (more) — товар, который нужно оприходовать.
        """
        less_value = 0.0
        more_count = 0
        less_items = 0
        more_items = 0
        
        for p in self.products:
            if p.actual is None:
                continue
            
            delta = p.actual - p.stock
            
            if delta < 0:
                cost = getattr(p, 'cost', 0) or getattr(p, 'wholesale_cost', 0) or 0
                less_value += abs(delta) * cost
                less_items += 1
            elif delta > 0:
                more_count += delta
                more_items += 1
        
        return {
            "less_value": less_value,
            "more_count": more_count,
            "less_items": less_items,
            "more_items": more_items,
        }

    def get_financial_liability(self) -> dict:
        """
        Считает финансовую ответственность админа за группу.
        
        Принцип: списываем только за чистую разницу (net_delta).
        Пересорт внутри бренда не влияет на деньги админа.
        
        Returns:
            {
                "group_name": str,
                "net_delta": int,
                "liability_value": float,       # сумма к списанию в ₽
                "liability_items": int,         # количество единиц к списанию
                "all_disposals_value": float,   # если бы списывали всё
                "compensation_applied": bool,   # была ли компенсация
                "minus_products": list,         # товары с недостачей
                "plus_products": list,          # товары с избытком
            }
        """
        # 🆕 Работаем только с видимыми товарами (stock > 0)
        counted = [p for p in self.products if p.actual is not None and p.stock > 0]
        
        if not counted:
            return {
                "group_name": self.name,
                "net_delta": 0,
                "liability_value": 0.0,
                "liability_items": 0,
                "all_disposals_value": 0.0,
                "compensation_applied": False,
                "minus_products": [],
                "plus_products": [],
            }
        
        # Реальные дельты каждого товара
        deltas = [(p.actual - p.stock, p) for p in counted]
        
        # Разделяем на минусы и плюсы
        minus_products = [(d, p) for d, p in deltas if d < 0]
        plus_products = [(d, p) for d, p in deltas if d > 0]
        
        total_minus = sum(d for d, p in deltas if d < 0)
        total_plus = sum(d for d, p in deltas if d > 0)
        
        # Чистая дельта группы
        net_delta = total_minus + total_plus
        
        # Сумма если бы списывали ВСЕ минусы
        all_disposals_value = sum(
            abs(d) * (getattr(p, 'cost', 0) or getattr(p, 'wholesale_cost', 0) or 0)
            for d, p in minus_products
        )
        
        # Финансовая ответственность = только чистая недостача
        if net_delta < 0 and minus_products:
            total_minus_qty = sum(abs(d) for d, p in minus_products)
            if total_minus_qty > 0:
                weighted_cost = sum(
                    abs(d) * (getattr(p, 'cost', 0) or getattr(p, 'wholesale_cost', 0) or 0)
                    for d, p in minus_products
                ) / total_minus_qty
                
                liability_value = abs(net_delta) * weighted_cost
                liability_items = abs(net_delta)
            else:
                liability_value = 0.0
                liability_items = 0
        else:
            liability_value = 0.0
            liability_items = 0
        
        compensation_applied = (abs(total_minus) + abs(total_plus)) != abs(net_delta)
        
        return {
            "group_name": self.name,
            "net_delta": net_delta,
            "liability_value": liability_value,
            "liability_items": liability_items,
            "all_disposals_value": all_disposals_value,
            "compensation_applied": compensation_applied,
            "minus_products": [p for d, p in minus_products],
            "plus_products": [p for d, p in plus_products],
        }

    @property
    def status(self) -> str:
        """Статус группы: more / less / equal / unknown."""
        if self.total_actual is None:
            return "unknown"
        if self.delta == 0:
            return "equal"
        return "more" if self.delta > 0 else "less"
    
    @property
    def all_counted(self) -> bool:
        return all(p.actual is not None for p in self.products)
    
    @property
    def any_counted(self) -> bool:
        return any(p.actual is not None for p in self.products)
    
    # ============================================================
    #  РАСПРЕДЕЛЕНИЕ ФАКТА ПО ВКУСАМ
    # ============================================================
    def distribute_actual(self, group_actual: int):
        """
        Распределяет общий факт группы по отдельным вкусам.
        Использует алгоритм Largest Remainder для корректного распределения
        даже малых дельт (например, -1 на 10 товаров).
        Распределяет ТОЛЬКО по товарам с stock > 0 (видимым в UI).
        """
        # Работаем только с видимыми товарами (stock > 0)
        visible = [p for p in self.products if p.stock > 0]
        
        if not visible:
            # Если нет видимых — распределяем по всем
            visible = self.products
        
        if not visible:
            return
        
        total_stock = sum(p.stock for p in visible)
        delta = group_actual - total_stock
        
        if total_stock == 0:
            # Все товары с нулевым остатком — распределяем равномерно
            per_item = delta // len(visible)
            remainder = abs(delta) - abs(per_item) * len(visible)
            for i, p in enumerate(visible):
                sign = 1 if delta > 0 else -1
                extra = sign * (1 if i < remainder else 0)
                p.actual = p.stock + per_item + extra
            return
        
        # === Largest Remainder Method ===
        # Точные доли (могут быть дробными)
        exact = [delta * (p.stock / total_stock) for p in visible]
        
        # Целые части (floor)
        floored = [math.floor(e) for e in exact]
        
        # Сколько уже распределили
        distributed_sum = sum(floored)
        leftover = delta - distributed_sum  # всегда >= 0
        
        # Дробные остатки для приоритета
        remainders = [(exact[i] - floored[i], i) for i in range(len(visible))]
        # Сортируем по убыванию остатка — кому нужнее +1
        remainders.sort(key=lambda x: x[0], reverse=True)
        
        # Распределяем leftover по единице
        for j in range(leftover):
            idx = remainders[j % len(remainders)][1]
            floored[idx] += 1
        
        # Применяем к товарам
        for p, d in zip(visible, floored):
            p.actual = p.stock + d
        
        # Невидимые товары (stock=0) — не трогаем, actual остаётся None
        invisible = [p for p in self.products if p.stock == 0]
        for p in invisible:
            p.actual = None

    def apply_exact_actuals(self, actuals_by_pid: dict) -> int:
        """
        Применяет ТОЧНЫЕ факты по товарам БЕЗ алгоритма распределения.
        
        Используется когда данные пришли с телефона и сменщик вручную
        ввёл факт по каждому вкусу. Значения применяются как есть,
        никакая балансировка не выполняется.
        
        Args:
            actuals_by_pid: словарь {product_id: actual_value}
        
        Returns:
            Количество применённых значений
        """
        applied = 0
        for p in self.products:
            if p.id in actuals_by_pid:
                p.actual = int(actuals_by_pid[p.id])
                applied += 1
            elif str(p.id) in actuals_by_pid:
                p.actual = int(actuals_by_pid[str(p.id)])
                applied += 1
        return applied
           
    def apply_exact_actuals(self, actuals_by_pid: dict):
        """
        Применяет ТОЧНЫЕ факты по товарам БЕЗ алгоритма распределения.
        
        Используется когда данные пришли с телефона и сменщик
        вручную ввёл факт по каждому вкусу. В этом случае
        никакая балансировка не нужна — значения применяются как есть.
        
        Args:
            actuals_by_pid: словарь {product_id: actual_value}
                           Пример: {12345: 5, 12346: 15}
        """
        applied = 0
        for p in self.products:
            if p.id in actuals_by_pid:
                p.actual = int(actuals_by_pid[p.id])
                applied += 1
            elif str(p.id) in actuals_by_pid:
                p.actual = int(actuals_by_pid[str(p.id)])
                applied += 1
        
        print(f"  [ProductGroup] ✓ {self.name}: применено {applied} точных фактов "
              f"(без алгоритма)")
        return applied
    
    def set_all_actual(self, value: int):
        self.distribute_actual(value)
    
    def clear_actual(self):
        for p in self.products:
            p.actual = None
    
    def get_discrepancies(self) -> List[Product]:
        """Возвращает товары с расхождениями (для нормализации)."""
        result = []
        for p in self.products:
            if p.actual is None:
                continue
            if p.actual != p.stock:
                result.append(p)
        return result
    
    # ============================================================
    #  СОРТИРОВКА
    # ============================================================
    def sort_products(self):
        self.products.sort(key=lambda p: p.title.lower())
    
    def __repr__(self):
        return f"<ProductGroup '{self.name}' ({len(self.products)} товаров, stock={self.total_stock})>"