"""
Модуль привязки точки продаж к конкретному ПК.

Использует:
1. Hardware ID (motherboard serial + CPU ID)
2. Подпись от сервера (BINDING_SECRET на VPS)
3. Хранение в point.lock рядом с .exe

v2.0 — Интеграция с серверной системой валидации:
- point.lock содержит подпись созданную сервером
- При запуске проверяется через /api/validate-launch
"""
import os
import sys
import json
import hashlib
import subprocess
import platform
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime


# ============================================================
#  ПУТЬ К ФАЙЛУ ПРИВЯЗКИ
# ============================================================
def _get_lock_file_path() -> Path:
    """
    Возвращает путь к файлу point.lock.
    
    Приоритет:
    1. Рядом с .exe (если запущено как .exe)
    2. В корне проекта (для разработки)
    """
    if getattr(sys, 'frozen', False):
        # Запущено как .exe
        return Path(sys.executable).parent / "point.lock"
    else:
        # Разработка — в корне проекта
        return Path(__file__).parent.parent / "point.lock"


# ============================================================
#  HARDWARE ID
# ============================================================
def get_hardware_id() -> str:
    """
    Получает уникальный идентификатор ПК на основе:
    - Motherboard Serial Number
    - CPU ID
    
    Возвращает SHA-256 хеш от комбинации (32 hex символа).
    """
    components = []
    
    if platform.system() == "Windows":
        # Motherboard Serial
        try:
            result = subprocess.run(
                ['wmic', 'baseboard', 'get', 'serialnumber'],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            if len(lines) > 1 and lines[1] not in (
                "To be filled by O.E.M.", 
                "Default string", 
                "None",
                "Base Board Serial Number"
            ):
                components.append(f"MB:{lines[1]}")
        except Exception:
            pass
        
        # CPU ID
        try:
            result = subprocess.run(
                ['wmic', 'cpu', 'get', 'processorid'],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            if len(lines) > 1 and lines[1] != "ProcessorId":
                components.append(f"CPU:{lines[1]}")
        except Exception:
            pass
    else:
        # Linux/macOS fallback
        try:
            with open('/etc/machine-id', 'r') as f:
                components.append(f"MACHINE:{f.read().strip()}")
        except Exception:
            pass
    
    # Fallback: MAC-адрес если ничего не нашли
    if not components:
        import uuid
        mac = uuid.getnode()
        components.append(f"MAC:{mac}")
    
    # Хеш от всех компонентов (сортируем для стабильности)
    combined = "|".join(sorted(components))
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


# ============================================================
#  🆕 ЧТЕНИЕ ДАННЫХ ИЗ POINT.LOCK
# ============================================================
def get_lock_data() -> dict:
    """
    Читает данные из point.lock.
    
    Поддерживает два формата:
    1. Новый (серверный): {point_name, hwid, signature, bound_at}
    2. Старый (локальный): {point_name, hardware_id, signature}
    
    Returns:
        dict с данными или пустой dict если файл не найден
    """
    lock_path = _get_lock_file_path()
    
    if not lock_path.exists():
        print(f"[PointLock] ℹ️ Файл не найден: {lock_path}")
        return {}
    
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not isinstance(data, dict):
            print(f"[PointLock] ⚠ Файл повреждён (не JSON объект)")
            return {}
        
        # Нормализуем ключи (поддержка обоих форматов)
        result = {
            "point_name": data.get("point_name"),
            "hwid": data.get("hwid") or data.get("hardware_id"),
            "signature": data.get("signature"),
            "bound_at": data.get("bound_at") or data.get("created_at"),
        }
        
        # Проверяем HWID (должен совпадать с текущим ПК)
        if result["hwid"]:
            current_hwid = get_hardware_id()
            if result["hwid"] != current_hwid:
                print(f"[PointLock] ⚠ HWID не совпадает!")
                print(f"  В файле:  {result['hwid'][:16]}...")
                print(f"  Текущий:  {current_hwid[:16]}...")
                print(f"  ⚠️ Файл point.lock скопирован с другого ПК")
                return {}
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"[PointLock] ⚠ Файл повреждён (невалидный JSON): {e}")
        return {}
    except Exception as e:
        print(f"[PointLock] ⚠ Ошибка чтения: {e}")
        return {}


# ============================================================
#  🆕 СОХРАНЕНИЕ ОТ СЕРВЕРА (новый формат)
# ============================================================
def save_point_lock_from_server(point_name: str, hwid: str, signature: str, bound_at: str = None) -> Tuple[bool, str]:
    """
    Сохраняет point.lock с данными от сервера.
    Используется активатором (activate_point.py).
    
    Args:
        point_name: Название точки
        hwid: Hardware ID (уже проверен на совпадение)
        signature: Подпись от сервера
        bound_at: Дата привязки
    
    Returns:
        (success: bool, message: str)
    """
    try:
        data = {
            "point_name": point_name,
            "hwid": hwid,
            "signature": signature,
            "bound_at": bound_at or datetime.now().isoformat(),
            "format_version": 2,  # 🆕 Новая версия формата
        }
        
        lock_path = _get_lock_file_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Если был старый read-only — снимаем
        if lock_path.exists():
            try:
                os.chmod(lock_path, 0o666)
            except Exception:
                pass
        
        with open(lock_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Устанавливаем read-only для защиты от модификации
        try:
            if platform.system() == "Windows":
                os.chmod(lock_path, 0o444)
        except Exception:
            pass
        
        print(f"[PointLock] ✓ point.lock сохранён: {lock_path}")
        print(f"[PointLock]   Точка: {point_name}")
        print(f"[PointLock]   HWID: {hwid[:16]}...")
        return True, f"Точка '{point_name}' успешно привязана"
    
    except Exception as e:
        return False, f"Ошибка сохранения: {e}"


# ============================================================
#  СОВМЕСТИМОСТЬ: СТАРЫЕ ФУНКЦИИ
# ============================================================
def is_point_locked() -> bool:
    """Проверяет, привязана ли точка к этому ПК."""
    data = get_lock_data()
    return bool(data.get("point_name") and data.get("signature"))


def get_locked_point() -> Optional[str]:
    """
    Возвращает название привязанной точки или None.
    Проверяет подпись через серверную валидацию (в main.py).
    """
    data = get_lock_data()
    return data.get("point_name") if data else None


def save_locked_point(point_name: str) -> Tuple[bool, str]:
    """
    [УСТАРЕВШЕЕ] Локальная привязка точки.
    Используйте save_point_lock_from_server() для новой системы.
    """
    print("[PointLock] ⚠ save_locked_point() устарела. Используйте activate_point.exe")
    return False, "Используйте новую систему привязки через activate_point.exe"


def unlock_point(master_password: str = None) -> Tuple[bool, str]:
    """
    Снимает привязку точки (требует мастер-пароль).
    
    ⚠️ В новой системе разблокировка делается через сервер
    или удалением point.lock вручную.
    """
    # Мастер-пароль (для обратной совместимости)
    MASTER_HASH = "ae949f938254963d2e188948ea8026c011308495b8373173d815e2467b6f7e72"
    
    if master_password is None:
        return False, "Не указан мастер-пароль"
    
    password_hash = hashlib.sha256(master_password.encode()).hexdigest()
    if password_hash != MASTER_HASH:
        return False, "Неверный мастер-пароль"
    
    try:
        lock_path = _get_lock_file_path()
        if lock_path.exists():
            # Снимаем read-only если был
            try:
                os.chmod(lock_path, 0o666)
            except Exception:
                pass
            lock_path.unlink()
        
        print(f"[PointLock] ✓ Привязка снята")
        return True, "Привязка точки успешно снята"
    
    except Exception as e:
        return False, f"Ошибка снятия привязки: {e}"


# ============================================================
#  ДИАГНОСТИКА
# ============================================================
def print_lock_info():
    """Выводит информацию о текущей привязке (для отладки)"""
    print("=" * 60)
    print("🔐 Информация о привязке точки")
    print("=" * 60)
    print(f"  Путь: {_get_lock_file_path()}")
    print(f"  HWID: {get_hardware_id()[:16]}...")
    
    data = get_lock_data()
    if data:
        print(f"  Точка: {data.get('point_name')}")
        print(f"  HWID в файле: {data.get('hwid', '')[:16]}...")
        print(f"  Подпись: {data.get('signature', '')[:16]}...")
        print(f"  Привязана: {data.get('bound_at')}")
    else:
        print(f"  ⚠ Точка не привязана")
    print("=" * 60)


if __name__ == "__main__":
    print_lock_info()