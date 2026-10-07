"""
Проверка целостности приложения и валидация запуска.

Использование:
1. При старте приложения: validate_launch() — проверка хеша и HWID на сервере
2. В каждом API-запросе: get_exe_hash() + get_hardware_id() — заголовки X-Client-Hash/X-Client-HWID
3. Для отладки: get_client_info() — полная информация о клиенте

Результаты кэшируются при первом вызове — последующие вызовы мгновенные.
"""
import sys
import hashlib
import platform
import subprocess
from pathlib import Path
from typing import Optional, Dict
from functools import lru_cache
from core.hardware import get_hardware_id
import httpx


# ============================================================
#  КЭШИРОВАНИЕ РЕЗУЛЬТАТОВ
# ============================================================
_CACHED_EXE_HASH: Optional[str] = None
_CACHED_HWID: Optional[str] = None


# ============================================================
#  РЕЖИМ ЗАПУСКА
# ============================================================
def is_frozen() -> bool:
    """Проверяет, запущено ли приложение как .exe (собрано через PyInstaller)"""
    return getattr(sys, 'frozen', False)


def is_dev_mode() -> bool:
    """Возвращает True если приложение запущено в режиме разработки (через python main.py)"""
    return not is_frozen()


# ============================================================
#  ВЫЧИСЛЕНИЕ ХЕША .EXE
# ============================================================
def get_exe_hash() -> str:
    """
    Вычисляет SHA-256 хеш текущего исполняемого файла.
    
    Результаты кэшируются — повторные вызовы мгновенные.
    
    Returns:
        str: SHA-256 хеш (64 hex символа) или пустая строка при ошибке/dev-режиме
        
    Note:
        В dev-режиме возвращает пустую строку, чтобы middleware на сервере
        не блокировало запросы (обратная совместимость с "Legacy client").
        Для тестирования middleware в dev-режиме используйте get_dev_hash().
    """
    global _CACHED_EXE_HASH
    
    # Возвращаем кэш если есть
    if _CACHED_EXE_HASH is not None:
        return _CACHED_EXE_HASH
    
    # В режиме разработки — пустая строка (middleware пропустит как Legacy client)
    if not is_frozen():
        _CACHED_EXE_HASH = ""
        print("[Integrity] ℹ️ Dev-режим: хеш не вычисляется (middleware пропустит как Legacy client)")
        return _CACHED_EXE_HASH
    
    # В production-режиме — вычисляем реальный хеш
    try:
        exe_path = Path(sys.executable)
        sha256 = hashlib.sha256()
        
        # Читаем файл блоками по 64KB для оптимальной производительности
        with open(exe_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256.update(chunk)
        
        _CACHED_EXE_HASH = sha256.hexdigest()
        print(f"[Integrity] ✓ Хеш .exe: {_CACHED_EXE_HASH[:16]}...")
        return _CACHED_EXE_HASH
        
    except FileNotFoundError:
        print(f"[Integrity] ❌ Файл не найден: {sys.executable}")
        _CACHED_EXE_HASH = ""
        return _CACHED_EXE_HASH
    except PermissionError:
        print(f"[Integrity] ❌ Нет прав на чтение: {sys.executable}")
        _CACHED_EXE_HASH = ""
        return _CACHED_EXE_HASH
    except Exception as e:
        print(f"[Integrity] ❌ Ошибка вычисления хеша: {type(e).__name__}: {e}")
        _CACHED_EXE_HASH = ""
        return _CACHED_EXE_HASH


def get_dev_hash() -> str:
    """
    Вычисляет хеш от main.py для dev-режима (для тестирования middleware).
    
    Используйте эту функцию если нужно протестировать middleware в dev-режиме.
    Не забудьте зарегистрировать этот хеш на сервере через register_build.bat.
    
    Returns:
        str: SHA-256 хеш от main.py
    """
    try:
        main_py = Path(__file__).parent.parent / "main.py"
        if not main_py.exists():
            print(f"[Integrity] ⚠ main.py не найден: {main_py}")
            return ""
        
        sha256 = hashlib.sha256()
        with open(main_py, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256.update(chunk)
        
        dev_hash = sha256.hexdigest()
        print(f"[Integrity] ℹ️ Dev-хеш (main.py): {dev_hash[:16]}...")
        return dev_hash
        
    except Exception as e:
        print(f"[Integrity] ❌ Ошибка вычисления dev-хеша: {e}")
        return ""

# ============================================================
#  ВАЛИДАЦИЯ ЗАПУСКА (вызывается один раз при старте)
# ============================================================
def validate_launch(server_url: str, api_key: str,
                    point_name: str, signature: str,
                    timeout: float = 10.0) -> Dict:
    """
    Валидирует запуск приложения на сервере.
    Вызывается ОДИН РАЗ при старте приложения.
    
    ⚠️ Использует ТОЛЬКО API_SECRET_KEY (не MASTER_API_KEY!).
    
    Args:
        server_url: URL сервера (https://78.17.47.74:8443)
        api_key: API_SECRET_KEY для аутентификации
        point_name: Название точки из point.lock
        signature: Подпись из point.lock
        timeout: Таймаут запроса в секундах
    
    Returns:
        Dict с ключами:
        - allowed: bool — разрешён ли запуск
        - reason: str — причина отказа (если есть)
        - version: str — версия билда (если разрешено)
        - offline_mode: bool — работает ли в offline режиме
    """
    exe_hash = get_exe_hash()
    hwid = get_hardware_id()
    
    # Если не удалось вычислить хеш — работаем в offline режиме
    if not exe_hash:
        print("[Integrity] ⚠ Не удалось вычислить хеш приложения — offline режим")
        return {
            "allowed": True,
            "reason": "Hash computation failed — offline mode",
            "version": "offline",
            "offline_mode": True
        }
    
    # Если не удалось получить HWID — offline режим
    if not hwid:
        print("[Integrity] ⚠ Не удалось получить HWID — offline режим")
        return {
            "allowed": True,
            "reason": "HWID computation failed — offline mode",
            "version": "offline",
            "offline_mode": True
        }
    
    print(f"[Integrity] 🔍 Валидация запуска:")
    print(f"  Хеш: {exe_hash[:16]}...")
    print(f"  HWID: {hwid[:16]}...")
    print(f"  Точка: {point_name}")
    
    try:
        with httpx.Client(verify=False, timeout=timeout) as client:
            response = client.post(
                f"{server_url}/api/validate-launch",
                headers={
                    "X-API-Key": api_key,
                    "Content-Type": "application/json"
                },
                json={
                    "exe_hash": exe_hash,
                    "hwid": hwid,
                    "point_name": point_name,
                    "signature": signature,
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("allowed"):
                    version = data.get('version', '?')
                    print(f"[Integrity] ✓ Запуск разрешён (версия: {version})")
                else:
                    reason = data.get('reason', 'неизвестно')
                    print(f"[Integrity] ❌ Запуск запрещён: {reason}")
                
                return {
                    "allowed": data.get("allowed", False),
                    "reason": data.get("reason", ""),
                    "version": data.get("version", ""),
                    "offline_mode": False
                }
            else:
                print(f"[Integrity] ⚠️ Сервер вернул HTTP {response.status_code} — offline режим")
                return {
                    "allowed": True,
                    "reason": f"Offline mode (HTTP {response.status_code})",
                    "version": "offline",
                    "offline_mode": True
                }
                
    except httpx.TimeoutException:
        print("[Integrity] ⚠️ Таймаут подключения к серверу — offline режим")
        return {
            "allowed": True,
            "reason": "Offline mode (timeout)",
            "version": "offline",
            "offline_mode": True
        }
    except httpx.ConnectError:
        print("[Integrity] ⚠️ Нет подключения к серверу — offline режим")
        return {
            "allowed": True,
            "reason": "Offline mode (no connection)",
            "version": "offline",
            "offline_mode": True
        }
    except Exception as e:
        print(f"[Integrity] ⚠️ Ошибка подключения: {type(e).__name__}: {e} — offline режим")
        return {
            "allowed": True,
            "reason": f"Offline mode ({type(e).__name__})",
            "version": "offline",
            "offline_mode": True
        }


# ============================================================
#  ОТЛАДОЧНАЯ ИНФОРМАЦИЯ
# ============================================================
def get_client_info() -> Dict:
    """
    Возвращает полную информацию о текущем клиенте (для отладки и логирования).
    
    Returns:
        Dict с ключами:
        - frozen: bool — запущено ли как .exe
        - exe_hash: str — хеш приложения
        - hwid: str — идентификатор ПК
        - platform: str — операционная система
        - python_version: str — версия Python
        - executable: str — путь к исполняемому файлу
    """
    return {
        "frozen": is_frozen(),
        "dev_mode": is_dev_mode(),
        "exe_hash": get_exe_hash(),
        "exe_hash_short": get_exe_hash()[:16] + "..." if get_exe_hash() else "",
        "hwid": get_hardware_id(),
        "hwid_short": get_hardware_id()[:16] + "..." if get_hardware_id() else "",
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": sys.version.split()[0],
        "executable": str(sys.executable),
    }


def print_client_info():
    """Выводит информацию о клиенте в консоль (для отладки)"""
    info = get_client_info()
    print("=" * 60)
    print("🔍 Информация о клиенте")
    print("=" * 60)
    print(f"  Режим запуска:    {'📦 Сборка (.exe)' if info['frozen'] else '🐍 Разработка (python)'}")
    print(f"  Платформа:        {info['platform']} {info['platform_version']}")
    print(f"  Python:           {info['python_version']}")
    print(f"  Исполняемый файл: {info['executable']}")
    print(f"  Хеш .exe:         {info['exe_hash_short'] or '—'}")
    print(f"  HWID:             {info['hwid_short'] or '—'}")
    print("=" * 60)


# ============================================================
#  СБРОС КЭША (для тестирования)
# ============================================================
def reset_cache():
    """Сбрасывает кэш хеша и HWID. Используйте только для тестирования!"""
    global _CACHED_EXE_HASH, _CACHED_HWID
    _CACHED_EXE_HASH = None
    _CACHED_HWID = None
    print("[Integrity] ♻️ Кэш сброшен")


# ============================================================
#  ТЕСТОВЫЙ ЗАПУСК
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🔍 Тест integrity_checker.py")
    print("=" * 60)
    
    print_client_info()
    
    # Дополнительная проверка
    print("\n📋 Детальная информация:")
    print(f"  is_frozen():   {is_frozen()}")
    print(f"  is_dev_mode(): {is_dev_mode()}")
    
    if is_dev_mode():
        print("\n💡 Dev-режим активен:")
        print("  - get_exe_hash() возвращает пустую строку")
        print("  - Middleware на сервере пропустит как Legacy client")
        print("  - Для тестирования middleware используйте get_dev_hash():")
        dev_hash = get_dev_hash()
        if dev_hash:
            print(f"    Dev-хеш: {dev_hash}")
    
    print("=" * 60)