"""
Верификатор результатов нормализации.

Проверяет что все операции списания/внесения действительно применились
в SmartShell. При обнаружении расхождений — повторяет проблемные операции.

Используется после нормализации и ПЕРЕД генерацией PDF-отчёта.
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
    delta: int                # что хотели (например -2)
    expected_stock: int       # что ожидали после операции
    old_stock: int            # что было до операции
    reason: str
    
    # Результаты проверки
    actual_stock: Optional[int] = None
    is_verified: bool = False
    attempts: int = 0
    last_error: Optional[str] = None


@dataclass
class VerificationResult:
    """Результат полной верификации."""
    operations: List[OperationResult] = field(default_factory=list)
    attempts_count: int = 0
    max_attempts: int = 3
    
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
    def can_retry(self) -> bool:
        """Можно ли ещё повторить попытку."""
        if not self.failed_operations:
            return False
        # Проверяем что хотя бы одна операция не достигла максимума попыток
        return any(op.attempts < self.max_attempts for op in self.failed_operations)
    
    def summary(self) -> str:
        if self.all_ok:
            return f"✓ Все {self.total} операций подтверждены"
        return f"⚠ {self.verified_count}/{self.total} подтверждено, {self.failed_count} требуют внимания"


class NormalizationVerifier:
    """
    Проверяет что операции нормализации применились в SmartShell.
    
    Алгоритм:
    1. Сохраняет список выполненных операций с ожидаемыми остатками
    2. Делает запрос к SmartShell (через сервер)
    3. Сравнивает реальные остатки с ожидаемыми
    4. При расхождениях — повторяет операцию
    5. Возвращает VerificationResult
    """
    
    MAX_ATTEMPTS = 3
    DELAY_BETWEEN_ATTEMPTS = 2.0  # секунды между попытками
    DELAY_AFTER_NORMALIZATION = 1.5  # задержка после нормализации перед проверкой
    
    def __init__(self, client: ApiClient):
        self.client = client
    
    def build_operations_list(self, discrepancies: List[Product], 
                              reasons: dict, actuals_before: dict) -> List[OperationResult]:
        """
        Формирует список операций для верификации.
        
        Args:
            discrepancies: товары с расхождениями (после нормализации)
            reasons: словарь {product_id: reason}
            actuals_before: словарь {product_id: old_stock} до нормализации
        
        Returns:
            Список OperationResult для верификации
        """
        operations = []
        for product in discrepancies:
            if product.actual is None or product.actual == product.stock:
                continue
            
            delta = product.actual - product.stock
            old_stock = actuals_before.get(product.id, product.stock)
            operation_type = "DISPOSAL" if delta < 0 else "ADD"
            
            op = OperationResult(
                product_id=product.id,
                product_title=product.title,
                operation_type=operation_type,
                delta=delta,
                expected_stock=product.actual,
                old_stock=old_stock,
                reason=reasons.get(product.id, ""),
            )
            operations.append(op)
        
        return operations
    
    def verify(self, operations: List[OperationResult], 
               progress_callback: Optional[Callable] = None) -> VerificationResult:
        """
        Проверяет что все операции применились.
        
        Args:
            operations: список операций для проверки
            progress_callback: callback(current, total, message) для UI
        
        Returns:
            VerificationResult с результатами
        """
        result = VerificationResult(
            operations=operations,
            max_attempts=self.MAX_ATTEMPTS,
        )
        
        if not operations:
            return result
        
        # Даём SmartShell время обработать операции
        if progress_callback:
            progress_callback(0, len(operations), "⏳ Ожидание обработки SmartShell...")
        time.sleep(self.DELAY_AFTER_NORMALIZATION)
        
        # Получаем свежие данные
        if progress_callback:
            progress_callback(0, len(operations), "🔄 Загрузка актуальных остатков...")
        
        try:
            raw_goods = self.client.fetch_goods("")
            goods_map = {g.get("id"): g for g in raw_goods} if raw_goods else {}
        except Exception as e:
            print(f"[Verifier] ✗ Ошибка загрузки товаров: {e}")
            # Помечаем все как непроверенные с ошибкой
            for op in operations:
                op.last_error = f"Ошибка загрузки: {e}"
            return result
        
        # Проверяем каждую операцию
        for i, op in enumerate(operations):
            if progress_callback:
                progress_callback(i + 1, len(operations), 
                                 f"Проверка: {op.product_title}")
            
            remote_data = goods_map.get(op.product_id)
            if not remote_data:
                op.last_error = "Товар не найден в SmartShell"
                op.is_verified = False
                op.attempts = 1
                continue
            
            actual_stock = remote_data.get("amount", 0)
            op.actual_stock = actual_stock
            op.attempts = 1
            
            # Сравниваем
            if actual_stock == op.expected_stock:
                op.is_verified = True
                op.last_error = None
                print(f"[Verifier] ✓ {op.product_title}: {op.old_stock} → {actual_stock} "
                      f"(ожидалось {op.expected_stock})")
            else:
                op.is_verified = False
                op.last_error = (f"Ожидалось {op.expected_stock}, "
                                f"получено {actual_stock}")
                print(f"[Verifier] ✗ {op.product_title}: {op.last_error}")
        
        result.attempts_count = 1
        return result
    
    def retry_failed(self, result: VerificationResult,
                    progress_callback: Optional[Callable] = None) -> VerificationResult:
        """
        Повторяет обработку проблемных операций.
        
        Args:
            result: предыдущий результат верификации
            progress_callback: callback для UI
        
        Returns:
            Обновлённый VerificationResult
        """
        failed = result.failed_operations
        if not failed:
            return result
        
        if progress_callback:
            progress_callback(0, len(failed), 
                             f"🔁 Повторная обработка ({len(failed)} товаров)...")
        
        # Повторяем операции через сервер
        for i, op in enumerate(failed):
            if progress_callback:
                progress_callback(i, len(failed), 
                                 f"Повтор #{op.attempts + 1}: {op.product_title}")
            
            try:
                # Отправляем операцию заново
                response = self.client.normalize_single(
                    product_id=op.product_id,
                    product_title=op.product_title,
                    delta=op.delta,
                    reason=op.reason,
                    operation_type=op.operation_type,
                    session_info={},
                    giver="",
                    receiver="",
                    point_name="",
                )
                
                if not response.get("success"):
                    op.last_error = response.get("error", "Неизвестная ошибка")
                    print(f"[Verifier] ✗ Повтор не удался: {op.product_title} — {op.last_error}")
            except Exception as e:
                op.last_error = str(e)
                print(f"[Verifier] ✗ Ошибка повтора: {op.product_title} — {e}")
        
        # Ждём и снова проверяем
        if progress_callback:
            progress_callback(len(failed), len(failed), "⏳ Ожидание обработки...")
        time.sleep(self.DELAY_AFTER_NORMALIZATION)
        
        # Загружаем свежие данные
        if progress_callback:
            progress_callback(0, len(failed), "🔄 Проверка результатов...")
        
        try:
            raw_goods = self.client.fetch_goods("")
            goods_map = {g.get("id"): g for g in raw_goods} if raw_goods else {}
        except Exception as e:
            print(f"[Verifier] ✗ Ошибка загрузки: {e}")
            return result
        
        # Проверяем только проблемные
        for i, op in enumerate(failed):
            if progress_callback:
                progress_callback(i + 1, len(failed), 
                                 f"Проверка: {op.product_title}")
            
            remote_data = goods_map.get(op.product_id)
            if not remote_data:
                continue
            
            actual_stock = remote_data.get("amount", 0)
            op.actual_stock = actual_stock
            op.attempts += 1
            
            if actual_stock == op.expected_stock:
                op.is_verified = True
                op.last_error = None
                print(f"[Verifier] ✓ {op.product_title}: подтверждено с {op.attempts} попытки")
            else:
                op.is_verified = False
                op.last_error = (f"Ожидалось {op.expected_stock}, "
                                f"получено {actual_stock}")
                print(f"[Verifier] ✗ {op.product_title}: {op.last_error} (попытка {op.attempts})")
        
        result.attempts_count += 1
        return result
    
    def auto_verify_with_retries(self, operations: List[OperationResult],
                                progress_callback: Optional[Callable] = None) -> VerificationResult:
        """
        Автоматическая верификация с повторами до успеха или максимума попыток.
        
        Returns:
            Финальный VerificationResult
        """
        result = self.verify(operations, progress_callback)
        
        while not result.all_ok and result.can_retry:
            print(f"[Verifier] 🔁 Автоповтор (попытка {result.attempts_count + 1})...")
            time.sleep(self.DELAY_BETWEEN_ATTEMPTS)
            result = self.retry_failed(result, progress_callback)
        
        return result