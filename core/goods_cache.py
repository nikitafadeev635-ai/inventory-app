"""
Клиентский кеш товаров с группировкой по брендам.

Хранит:
- Полный список товаров (включая stock=0) - для группировки
- Группы по брендам - для UI
- Методы фильтрации и поиска
"""
import time
from typing import List, Optional, Callable
from items.product import Product
from core.product_grouper import group_products
from core.product_group import ProductGroup


class GoodsCache:
    """Singleton-кеш товаров текущей точки."""
    
    _instance: Optional['GoodsCache'] = None
    
    def __init__(self):
        # Полные данные (включая stock=0) - для группировки
        self._all_products: List[Product] = []
        self._groups: List[ProductGroup] = []
        
        self._loaded_at: float = 0
        self._ttl: int = 600  # 10 минут
        self._warehouse_id: Optional[int] = None
        self._listeners: List[Callable] = []
    
    @classmethod
    def instance(cls) -> 'GoodsCache':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # ============================================================
    #  ЗАГРУЗКА И СБРОС
    # ============================================================
    def load(self, products: List[Product], warehouse_id: Optional[int] = None):
        """
        Загружает полный список товаров и автоматически группирует.
        
        Args:
            products: список ВСЕХ товаров (включая stock=0)
            warehouse_id: ID склада
        """
        if self._warehouse_id is not None and warehouse_id != self._warehouse_id:
            print(f"[Cache] Сменилась точка: {self._warehouse_id} → {warehouse_id}")
            self._all_products = []
        
        self._all_products = products
        self._warehouse_id = warehouse_id
        self._loaded_at = time.time()
        
        # Автоматическая группировка
        self._groups = group_products(products)
        
        print(f"[Cache] ✓ Загружено {len(products)} товаров в {len(self._groups)} групп")
        self._notify_listeners()
    
    def invalidate(self):
        """Сбрасывает кеш."""
        self._all_products = []
        self._groups = []
        self._loaded_at = 0
        print("[Cache] 🔄 Кеш сброшен")
        self._notify_listeners()
    
    def is_fresh(self) -> bool:
        if not self._all_products:
            return False
        return (time.time() - self._loaded_at) < self._ttl
    
    def is_loaded(self) -> bool:
        return len(self._all_products) > 0
    
    # ============================================================
    #  ДОСТУП К ДАННЫМ
    # ============================================================
    def get_all_products(self) -> List[Product]:
        """ВСЕ товары (включая stock=0) - для отчётов."""
        return self._all_products
    
    def get_groups(self) -> List[ProductGroup]:
        """Все группы (включая те, где все товары stock=0)."""
        return self._groups
    
    def get_ui_groups(self) -> List[ProductGroup]:
        """
        Группы для UI — только те, где есть хотя бы 1 товар со stock>0.
        Внутри групп оставляем только товары со stock>0.
        """
        result = []
        for group in self._groups:
            visible_products = [p for p in group.products if p.stock > 0]
            if not visible_products:
                continue  # все товары закончились - не показываем
            
            # Создаём копию группы только с видимыми товарами
            ui_group = ProductGroup(name=group.name)
            ui_group.products = visible_products
            ui_group.expanded = group.expanded
            result.append(ui_group)
        
        return result
    
    # ============================================================
    #  ПОИСК И ФИЛЬТРАЦИЯ
    # ============================================================
    def filter_local(self, query: str) -> List[ProductGroup]:
        """
        Фильтрует группы по названию бренда или товара.
        Возвращает ТОЛЬКО группы (с фильтрацией внутри).
        
        Args:
            query: строка поиска
        
        Returns:
            Список ProductGroup с отфильтрованными товарами
        """
        ui_groups = self.get_ui_groups()
        
        if not query or not query.strip():
            return ui_groups
        
        query_lower = query.lower().strip()
        result = []
        
        for group in ui_groups:
            # Фильтруем товары внутри группы
            matched_products = []
            for p in group.products:
                if query_lower in p.title.lower():
                    matched_products.append(p)
            
            # Если группа сама по себе совпадает - оставляем все товары
            if query_lower in group.name.lower():
                matched_products = group.products
            
            if matched_products:
                filtered_group = ProductGroup(name=group.name)
                filtered_group.products = matched_products
                filtered_group.expanded = group.expanded
                result.append(filtered_group)
        
        return result
    
    def get_by_id(self, product_id: int) -> Optional[Product]:
        for p in self._all_products:
            if p.id == product_id:
                return p
        return None
    
    def count(self) -> int:
        return len(self._all_products)
    
    def count_in_stock(self) -> int:
        return sum(1 for p in self._all_products if p.stock > 0)
    
    # ============================================================
    #  ПОДПИСКИ
    # ============================================================
    def subscribe(self, callback: Callable):
        if callback not in self._listeners:
            self._listeners.append(callback)
    
    def unsubscribe(self, callback: Callable):
        if callback in self._listeners:
            self._listeners.remove(callback)
    
    def _notify_listeners(self):
        for cb in self._listeners:
            try:
                cb()
            except Exception as e:
                print(f"[Cache] Ошибка в listener: {e}")


# Глобальный экземпляр
goods_cache = GoodsCache.instance()