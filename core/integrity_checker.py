"""
Проверка целостности приложения и валидация запуска.
Вычисляет хеш .exe и отправляет на сервер для проверки.

Используется ТОЛЬКО API_SECRET_KEY (не MASTER_API_KEY!).
"""
import sys
import hashlib
import platform
import subprocess
from pathlib import Path
from typing import Optional, Dict
import httpx


def is_frozen() -> bool:
    """Проверяет, запущено ли приложение как .exe"""
    return getattr(sys, 'frozen', False)


def get_exe_hash() -> Optional[str]:
    """
    Вычисляет SHA-256 хеш текущего исполняемого файла.
    
    Returns:
        SHA-256 хеш (64 hex символа) или None в dev-режиме
    """
    if not is_frozen():
        # В режиме разработки возвращаем специальный маркер
        return "dev_mode_" + hashlib.md5(b"dev").hexdigest()[:16]
    
    try:
        exe_path = Path(sys.executable)
        sha256 = hashlib.sha256()
        
        with open(exe_path, 'rb') as f:
            # Читаем файл блоками по 8KB для экономии памяти
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    except Exception as e:
        print(f"[Integrity] ❌ Ошибка вычисления хеша: {e}")
        return None


def get_hardware_id() -> str:
    """
    Получает уникальный идентификатор ПК.
    Использует motherboard serial + CPU ID (Windows).
    
    Returns:
        SHA-256 хеш от комбинации компонентов (32 hex символа)
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
            if len(lines) > 1 and lines[1] not in ("To be filled by O.E.M.", "Default string", "None"):
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
    
    # Хеш от всех компонентов (сортируем для стабильности)
    combined = "|".join(sorted(components))
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


def validate_launch(server_url: str, api_key: str, 
                    point_name: str, signature: str,
                    timeout: float = 10.0) -> Dict:
    """
    Валидирует запуск приложения на сервере.
    
    ⚠️ Использует ТОЛЬКО API_SECRET_KEY (не MASTER_API_KEY!).
    
    Args:
        server_url: URL сервера (https://78.17.47.74:8443)
        api_key: API_SECRET_KEY для аутентификации
        point_name: Название точки из point.lock
        signature: Подпись из point.lock
        timeout: Таймаут запроса в секундах
        
    Returns:
        Dict с ключами:
        - allowed: bool - разрешён ли запуск
        - reason: str - причина отказа (если есть)
        - version: str - версия билда (если разрешено)
        - offline_mode: bool - работает ли в offline режиме
    """
    exe_hash = get_exe_hash()
    hwid = get_hardware_id()
    
    if not exe_hash:
        return {
            "allowed": False,
            "reason": "Не удалось вычислить хеш приложения",
            "offline_mode": False
        }
    
    print(f"[Integrity] 🔍 Валидация запуска:")
    print(f"  Хеш: {exe_hash[:16]}...")
    print(f"  HWID: {hwid[:16]}...")
    print(f"  Точка: {point_name}")
    
    # В dev-режиме разрешаем без проверки
    if exe_hash.startswith("dev_mode_"):
        print("[Integrity] ✓ Dev-режим: запуск разрешён без проверки")
        return {
            "allowed": True,
            "reason": "Development mode",
            "version": "dev",
            "offline_mode": False
        }
    
    try:
        # Отключаем проверку SSL для self-signed сертификатов
        with httpx.Client(verify=False, timeout=timeout) as client:
            response = client.post(
                f"{server_url}/api/validate-launch",
                headers={
                    "X-API-Key": api_key,  # ← ТОЛЬКО API_SECRET_KEY!
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
                    print(f"[Integrity] ✓ Запуск разрешён (версия: {data.get('version', '?')})")
                else:
                    print(f"[Integrity] ❌ Запуск запрещён: {data.get('reason', 'неизвестно')}")
                return {
                    "allowed": data.get("allowed", False),
                    "reason": data.get("reason", ""),
                    "version": data.get("version", ""),
                    "offline_mode": False
                }
            else:
                print(f"[Integrity] ⚠️ Сервер вернул HTTP {response.status_code}")
                # Fallback: разрешаем offline режим
                return {
                    "allowed": True,
                    "reason": f"Offline mode (HTTP {response.status_code})",
                    "version": "offline",
                    "offline_mode": True
                }
                
    except httpx.TimeoutException:
        print("[Integrity] ⚠️ Таймаут подключения к серверу")
        # Fallback: разрешаем offline режим
        return {
            "allowed": True,
            "reason": "Offline mode (timeout)",
            "version": "offline",
            "offline_mode": True
        }
    except httpx.ConnectError:
        print("[Integrity] ⚠️ Нет подключения к серверу")
        # Fallback: разрешаем offline режим
        return {
            "allowed": True,
            "reason": "Offline mode (no connection)",
            "version": "offline",
            "offline_mode": True
        }
    except Exception as e:
        print(f"[Integrity] ⚠️ Ошибка подключения: {e}")
        # Fallback: разрешаем offline режим
        return {
            "allowed": True,
            "reason": f"Offline mode ({type(e).__name__})",
            "version": "offline",
            "offline_mode": True
        }


def get_launch_info() -> Dict:
    """
    Возвращает информацию о текущем запуске (для отладки).
    """
    return {
        "frozen": is_frozen(),
        "exe_hash": get_exe_hash(),
        "hwid": get_hardware_id(),
        "platform": platform.system(),
        "python_version": sys.version,
    }


if __name__ == "__main__":
    # Тестовый запуск
    print("=" * 60)
    print("🔍 Тест integrity_checker.py")
    print("=" * 60)
    info = get_launch_info()
    for key, value in info.items():
        print(f"  {key}: {value}")
    print("=" * 60)