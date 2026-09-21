from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
from items.product import Product


@dataclass
class Session:
    point_name: Optional[str] = None
    point_id: Optional[str] = None
    giver: Optional[str] = None
    receiver: Optional[str] = None
    products: List[Product] = field(default_factory=list)
    is_open: bool = False
    actuals_cache: Dict[int, int] = field(default_factory=dict)
    
    # НОВОЕ: время и тип смены
    start_time: Optional[datetime] = None
    shift_type: Optional[str] = None   # "Дневная" или "Ночная"
    shift_label: Optional[str] = None  # Полная строка для лога

    def start(self, point_name, point_id, giver, receiver):
        self.point_name = point_name
        self.point_id = point_id
        self.giver = giver
        self.receiver = receiver
        self.is_open = True
        self.start_time = datetime.now()
        
        # Определяем тип смены по времени
        hour = self.start_time.hour
        if hour >= 16 or hour < 1:
            self.shift_type = "Дневная"
        else:
            self.shift_type = "Ночная"
        
        # Формируем строку для лога
        self.shift_label = (
            f"{self.point_name}, {self.giver}, "
            f"{self.start_time.strftime('%Y-%m-%d %H:%M')}, {self.shift_type}"
        )

    @property
    def elapsed_str(self) -> str:
        """Возвращает время с начала пересчёта в формате HH:MM:SS."""
        if not self.start_time:
            return "00:00:00"
        delta = datetime.now() - self.start_time
        total_seconds = int(delta.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def reset(self):
        self.point_name = None
        self.point_id = None
        self.giver = None
        self.receiver = None
        self.products = []
        self.is_open = False
        self.actuals_cache = {}
        self.start_time = None
        self.shift_type = None
        self.shift_label = None


current_session = Session()