from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class Product:
    id: int
    title: str
    stock: int              # БЫЛО: float → СТАЛО: int
    actual: Optional[int] = None   # БЫЛО: float → СТАЛО: int
    
    # Остальные поля (цены — float, они могут быть дробными)
    cost: float = 0.0
    wholesale_cost: float = 0.0
    eans: Optional[str] = None
    vat: Optional[float] = None
    use_global_discounts: bool = False
    use_fair_sign: bool = False
    comment: Optional[str] = None
    is_excise: bool = False
    category: Optional[Dict[str, Any]] = None
    show_in_shell: bool = True
    image: Optional[str] = None
    in_combo: bool = False
    low_stock_notification: Optional[Dict[str, Any]] = None
    highlighted: bool = False

    @classmethod
    def from_api(cls, data: dict) -> "Product":
        """Создаёт Product из ответа SmartShell API."""
        return cls(
            id=data.get("id"),
            title=data.get("title", ""),
            stock=int(float(data.get("amount", 0) or 0)),   # ← int
            cost=float(data.get("cost", 0) or 0),
            wholesale_cost=float(data.get("wholesale_cost", 0) or 0),
            eans=data.get("eans"),
            vat=data.get("vat"),
            use_global_discounts=data.get("use_global_discounts", False),
            use_fair_sign=data.get("use_fair_sign", False),
            comment=data.get("comment"),
            is_excise=data.get("is_excise", False),
            category=data.get("category"),
            show_in_shell=data.get("show_in_shell", True),
            image=data.get("image"),
            in_combo=data.get("in_combo", False),
            low_stock_notification=data.get("low_stock_notification"),
            highlighted=data.get("highlighted", False),
        )

    @property
    def status(self) -> str:
        if self.actual is None:
            return "unknown"
        if self.actual > self.stock:
            return "more"
        if self.actual < self.stock:
            return "less"
        return "equal"

    @property
    def color(self) -> str:
        return {
            "more": "#3B82F6",   # синий
            "less": "#EF4444",   # красный
            "equal": "#10B981",  # зелёный
        }.get(self.status, "transparent")