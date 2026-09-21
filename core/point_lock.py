"""
Модуль привязки точки продаж к конкретному ПК.

Использует:
1. Hardware ID (motherboard serial + CPU ID)
2. HMAC-SHA256 подпись для защиты от модификации
3. Обфусцированный ключ в коде

Точка сохраняется в файле point.lock рядом с .exe или в AppData.
"""
import os
import sys
import json
import hmac
import hashlib
import subprocess
import platform
from pathlib import Path
from typing import Optional, Tuple


# ============================================================
#  ПУТЬ К ФАЙЛУ ПРИВЯЗКИ
# ============================================================
def _get_lock_file_path() -> Path:
    """
    Возвращает путь к файлу point.lock.
    
    Приоритет:
    1. Рядом с .exe (если запущено как .exe)
    2. В AppData пользователя (для разработки)
    """
    if getattr(sys, 'frozen', False):
        # Запущено как .exe
        base_path = Path(sys.executable).parent
    else:
        # Запущено как Python-скрипт — используем AppData
        app_data = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        base_path = app_data / 'QFactDeductor'
        base_path.mkdir(exist_ok=True)
    
    return base_path / "point.lock"


# ============================================================
#  HARDWARE ID
# ============================================================
def get_hardware_id() -> str:
    """
    Получает уникальный идентификатор ПК на основе:
    - Motherboard Serial Number
    - CPU ID
    
    Возвращает SHA-256 хеш от комбинации.
    """
    components = []
    
    # Motherboard Serial (Windows)
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ['wmic', 'baseboard', 'get', 'serialnumber'],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            if len(lines) > 1:
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
            if len(lines) > 1:
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
    
    # Хеш от всех компонентов
    combined = "|".join(sorted(components))
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


# ============================================================
#  ОБФУСЦИРОВАННЫЙ СЕКРЕТНЫЙ КЛЮЧ
# ============================================================
def _get_secret_key() -> bytes:
    """
    Возвращает секретный ключ для HMAC.
    
    """
    encoded = [
        0x4A, 0x2F, 0x58, 0x71, 0x3C, 0x6B, 0x19, 0x42,
        0x6D, 0x35, 0x7A, 0x21, 0x59, 0x44, 0x68, 0x32,
        0x47, 0x5E, 0x28, 0x63, 0x49, 0x77, 0x3B, 0x54,
        0x61, 0x2C, 0x4F, 0x7D, 0x38, 0x52, 0x6E, 0x24,
    ]
    mask = 0x5A
    
    key_bytes = bytes([b ^ mask for b in encoded])
    hw_id = get_hardware_id()
    return hmac.new(key_bytes, hw_id.encode(), hashlib.sha256).digest()


def _generate_key() -> None:
    import secrets
    key = secrets.token_bytes(32)
    mask = 0x5A
    encoded = [b ^ mask for b in key]
    print("_get_secret_key):")
    print("encoded = [")
    for i in range(0, 32, 8):
        chunk = ", ".join(f"0x{b:02X}" for b in encoded[i:i+8])
        print(f"    {chunk},")
    print("]")


# ============================================================
#  ПОДПИСЬ И ВЕРИФИКАЦИЯ
# ============================================================
def _sign_data(point_name: str, hw_id: str) -> str:
    """Создаёт HMAC-SHA256 подпись для точки."""
    secret = _get_secret_key()
    message = f"{point_name}|{hw_id}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return signature


def _verify_signature(point_name: str, hw_id: str, signature: str) -> bool:
    """Проверяет подпись точки."""
    expected = _sign_data(point_name, hw_id)
    return hmac.compare_digest(expected, signature)


# ============================================================
#  ПУБЛИЧНЫЕ ФУНКЦИИ
# ============================================================
def is_point_locked() -> bool:
    """Проверяет, привязана ли точка к этому ПК."""
    lock_file = _get_lock_file_path()
    if not lock_file.exists():
        return False
    
    try:
        data = json.loads(lock_file.read_text(encoding='utf-8'))
        return all(k in data for k in ('point_name', 'hardware_id', 'signature'))
    except Exception:
        return False


def get_locked_point() -> Optional[str]:
    """
    Возвращает название привязанной точки или None.
    Проверяет подпись и Hardware ID.
    """
    lock_file = _get_lock_file_path()
    if not lock_file.exists():
        return None
    
    try:
        data = json.loads(lock_file.read_text(encoding='utf-8'))
        point_name = data.get('point_name')
        hw_id = data.get('hardware_id')
        signature = data.get('signature')
        
        if not all([point_name, hw_id, signature]):
            return None
        
        # Проверяем что Hardware ID совпадает с текущим ПК
        current_hw_id = get_hardware_id()
        if hw_id != current_hw_id:
            print(f"[PointLock] ⚠ Hardware ID не совпадает!")
            print(f"  Файл: {hw_id[:16]}...")
            print(f"  Текущий ПК: {current_hw_id[:16]}...")
            return None
        
        # Проверяем подпись
        if not _verify_signature(point_name, hw_id, signature):
            print(f"[PointLock] ✗ Неверная подпись! Файл был изменён.")
            return None
        
        print(f"[PointLock] ✓ Точка привязана: {point_name}")
        return point_name
    
    except Exception as e:
        print(f"[PointLock] ✗ Ошибка чтения файла: {e}")
        return None


def save_locked_point(point_name: str) -> Tuple[bool, str]:
    """
    Привязывает точку к текущему ПК.
    
    Returns:
        (success: bool, message: str)
    """
    try:
        hw_id = get_hardware_id()
        signature = _sign_data(point_name, hw_id)
        
        data = {
            "point_name": point_name,
            "hardware_id": hw_id,
            "signature": signature,
            "format_version": 1,
            "created_at": str(pd_datetime_now()),
        }
        
        lock_file = _get_lock_file_path()
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        
        try:
            if platform.system() == "Windows":
                os.chmod(lock_file, 0o444)  # read-only
        except Exception:
            pass  # на некоторых системах не сработает
        
        print(f"[PointLock] ✓ Точка '{point_name}' привязана к ПК")
        print(f"[PointLock]   Hardware ID: {hw_id[:16]}...")
        print(f"[PointLock]   Файл: {lock_file}")
        return True, f"Точка '{point_name}' успешно привязана"
    
    except Exception as e:
        return False, f"Ошибка привязки: {e}"


def unlock_point(master_password: str = None) -> Tuple[bool, str]:
    """
    Снимает привязку точки (требует мастер-пароль).
    
    Args:
        master_password: мастер-пароль для разблокировки
    
    Returns:
        (success: bool, message: str)
    """
    # Мастер-пароль (можно поменять)
    MASTER_HASH = "ae949f938254963d2e188948ea8026c011308495b8373173d815e2467b6f7e72"
    
    if master_password is None:
        return False, "Не указан мастер-пароль"
    
    password_hash = hashlib.sha256(master_password.encode()).hexdigest()
    if password_hash != MASTER_HASH:
        return False, "Неверный мастер-пароль"
    
    try:
        lock_file = _get_lock_file_path()
        if lock_file.exists():
            # Снимаем read-only если был
            try:
                os.chmod(lock_file, 0o666)
            except Exception:
                pass
            lock_file.unlink()
        
        print(f"[PointLock] ✓ Привязка снята")
        return True, "Привязка точки успешно снята"
    
    except Exception as e:
        return False, f"Ошибка снятия привязки: {e}"


def pd_datetime_now():
    """Возвращает текущее время (без импорта datetime на верхнем уровне)."""
    from datetime import datetime
    return datetime.now()