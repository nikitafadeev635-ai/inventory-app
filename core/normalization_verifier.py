"""
Верификатор результатов нормализации.

ВАЖНО: Верификатор ТОЛЬКО ПРОВЕРЯЕТ что операции применились.
Он НИКОГДА не отправляет повторные операции в SmartShell.

Алгоритм:
1. Ждёт задержку (SmartShell обрабатывает)
2. Запрашивает актуальные остатки
3. Сравнивает с ожидаемыми
4. Если не совпадают — ждёт и проверяет снова
5. После MAX_CHECK_ROUNDS проверок — фиксирует результат
"""
import time
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from core.api_client import ApiClient
from items.product import Product


@dataclass
class OperationResult:
    """Результат одной операции нормализации."""
    product_id: int
    product_title: str
    operation_type: str       # "DISPOSAL" или "ADD"
    delta: int
    expected_stock: int       # что ожидали после операции
    old_stock: int            # что было до операции
    reason: str
    
    # Результаты проверки
    actual_stock: Optional[int] = None
    is_verified: bool = False
    check_attempts: int = 0   # сколько раз проверяли
    last_error: Optional[str] = None


@dataclass
class VerificationResult:
    """Результат полной верификации."""
    operations: List[OperationResult] = field(default_factory=list)
    check_rounds: int = 0     # сколько раундов проверки было
    max_check_rounds: int = 3
    
    @property
    def total(self) -> int:
        return len(self.operations)
    
    @property
    def verified_count(self) -> int:
        return sum(1 for op in self.operations if op.is_verified)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for op in self.operations if not op.is_verified)
    
    @property
    def all_ok(self) -> bool:
        return self.failed_count == 0 and self.total > 0
    
    @property
    def failed_operations(self) -> List[OperationResult]:
        return [op for op in self.operations if not op.is_verified]
    
    @property
    def can_recheck(self) -> bool:
        """Можно ли ещё раз проверить."""
        if not self.failed_operations:
            return False
        return self.check_rounds < self.max_check_rounds
    
    def summary(self) -> str:
        if self.all_ok:
            return f"✓ Все {self.total} операций подтверждены"
        return (f"⚠ {self.verified_count}/{self.total} подтверждено, "
                f"{self.failed_count} не подтверждены")


class NormalizationVerifier:
    """
    Проверяет что операции нормализации применились в SmartShell.
    
    ВАЖНО: Этот класс ТОЛЬКО ЧИТАЕТ данные из SmartShell.
    Он НИКОГДА не отправляет операции списания/внесения.
    """
    
    MAX_CHECK_ROUNDS = 3           # максимум раундов проверки
    DELAY_BEFORE_FIRST_CHECK = 3.0 # задержка перед первой проверкой (сек)
    DELAY_BETWEEN_CHECKS = 5.0     # задержка между раундами проверки (сек)
    
    def __init__(self, client: ApiClient):
        self.client = client
    
    def verify(self, operations: List[OperationResult],
               progress_callback: Optional[Callable] = None) -> VerificationResult:
        """
        Проверяет что все операции применились.
        
        НЕ отправляет никаких операций — только читает остатки.
        """
        # Фильтруем невалидные операции
        valid_operations = [
            op for op in operations
            if op.product_id is not None and op.delta != 0
        ]
        
        result = VerificationResult(
            operations=valid_operations,
            max_check_rounds=self.MAX_CHECK_ROUNDS,
        )
        
        if not valid_operations:
            print("[Verifier] ⚠ Нет валидных операций для проверки")
            return result
        
        # Даём SmartShell время обработать
        if progress_callback:
            progress_callback(0, len(valid_operations),
                             f"⏳ Ожидание обработки SmartShell ({int(self.DELAY_BEFORE_FIRST_CHECK)}с)...")
        time.sleep(self.DELAY_BEFORE_FIRST_CHECK)
        
        # Раунды проверки
        for round_num in range(1, self.MAX_CHECK_ROUNDS + 1):
            result.check_rounds = round_num
            
            # Проверяем только те что ещё не подтверждены
            unverified = [op for op in valid_operations if not op.is_verified]
            if not unverified:
                break
            
            if progress_callback:
                progress_callback(0, len(unverified),
                                 f"🔄 Раунд проверки {round_num}/{self.MAX_CHECK_ROUNDS}...")
            
            # Загружаем актуальные остатки
            try:
                raw_goods = self.client.fetch_goods("")
                if not raw_goods:
                    print("[Verifier] ⚠ Пустой ответ от сервера")
                    if round_num < self.MAX_CHECK_ROUNDS:
                        time.sleep(self.DELAY_BETWEEN_CHECKS)
                        continue
                    else:
                        for op in unverified:
                            op.last_error = "Сервер вернул пустой список"
                        break
                
                # Приводим все ID к int для корректного сравнения
                goods_map = {}
                for g in raw_goods:
                    pid = g.get("id")
                    if pid is not None:
                        try:
                            goods_map[int(pid)] = g
                        except (ValueError, TypeError):
                            continue
                print(f"[Verifier] 📊 Загружено {len(goods_map)} товаров для проверки")
                
            except Exception as e:
                print(f"[Verifier] ✗ Ошибка загрузки: {e}")
                for op in unverified:
                    op.last_error = f"Ошибка загрузки: {e}"
                if round_num < self.MAX_CHECK_ROUNDS:
                    time.sleep(self.DELAY_BETWEEN_CHECKS)
                    continue
                else:
                    break
            
            # Проверяем каждую операцию
            for i, op in enumerate(unverified):
                if progress_callback:
                    progress_callback(i + 1, len(unverified),
                                     f"Проверка [{round_num}]: {op.product_title}")
                
                op.check_attempts = round_num
                
                # Ищем по приведённому к int ID
                remote_data = goods_map.get(int(op.product_id)) if op.product_id is not None else None
                if not remote_data:
                    op.last_error = f"Товар ID={op.product_id} не найден в SmartShell"
                    op.is_verified = False
                    print(f"[Verifier] ✗ {op.product_title} (ID={op.product_id}): товар не найден")
                    continue
                
                # Получаем текущий остаток
                actual_stock = remote_data.get("amount", 0)
                if actual_stock is None:
                    actual_stock = 0
                op.actual_stock = actual_stock
                
                # Сравниваем
                if actual_stock == op.expected_stock:
                    op.is_verified = True
                    op.last_error = None
                    print(f"[Verifier] ✓ {op.product_title}: "
                          f"{op.old_stock} → {actual_stock} "
                          f"(ожидалось {op.expected_stock}) [раунд {round_num}]")
                else:
                    op.is_verified = False
                    op.last_error = (f"Ожидалось {op.expected_stock}, "
                                    f"получено {actual_stock}")
                    print(f"[Verifier] ✗ {op.product_title}: {op.last_error} "
                          f"[раунд {round_num}]")
            
            # Если всё подтверждено — выходим
            if all(op.is_verified for op in valid_operations):
                print(f"[Verifier] ✅ Все операции подтверждены на раунде {round_num}")
                break
            
            # Задержка перед следующим раундом
            if round_num < self.MAX_CHECK_ROUNDS:
                unverified_count = sum(1 for op in valid_operations if not op.is_verified)
                if progress_callback:
                    progress_callback(len(unverified), len(unverified),
                                     f"⏳ Ожидание перед повторной проверкой "
                                     f"({int(self.DELAY_BETWEEN_CHECKS)}с)...")
                time.sleep(self.DELAY_BETWEEN_CHECKS)
        
        return result
    
    def auto_verify_with_retries(self, operations: List[OperationResult],
                                 progress_callback: Optional[Callable] = None) -> VerificationResult:
        """
        Автоматическая верификация с повторными проверками.
        
        ВАЖНО: НЕ отправляет повторных операций!
        Только проверяет несколько раз с задержками.
        """
        return self.verify(operations, progress_callback)