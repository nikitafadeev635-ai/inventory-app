"""
Унифицированные функции для работы с аппаратным обеспечением.
ЕДИНСТВЕННЫЙ источник get_hardware_id() для всех модулей.
"""
import hashlib
import platform
import subprocess

_CACHED_HWID = None


def get_hardware_id() -> str:
    """
    Получает уникальный идентификатор ПК.
    
    ⚠️ Эта функция используется в:
    - core/integrity_checker.py (для inventory_app.exe)
    - core/point_lock.py (для activate_point.exe)
    - core/api_client.py (для X-Client-HWID заголовка)
    
    Returns:
        SHA-256 хеш от комбинации компонентов (32 hex символа)
    """
    global _CACHED_HWID
    
    if _CACHED_HWID is not None:
        return _CACHED_HWID
    
    components = []
    
    # Единый список заглушек для всех модулей
    INVALID_MB_SERIALS = {
        "To be filled by O.E.M.",
        "Default string",
        "None",
        "Base Board Serial Number",
        "System Serial Number",
        "0000000000000",
        "1234567890",
    }
    
    INVALID_CPU_IDS = {
        "ProcessorId",
        "0000000000000000",
        "",
    }
    
    if platform.system() == "Windows":
        # Motherboard Serial
        try:
            result = subprocess.run(
                ['wmic', 'baseboard', 'get', 'serialnumber'],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            if len(lines) > 1 and lines[1] not in INVALID_MB_SERIALS:
                components.append(f"MB:{lines[1]}")
        except Exception:
            pass
        
        # CPU ID
        try:
            result = subprocess.run(
                ['wmic', 'cpu', 'get', 'processorid'],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            if len(lines) > 1 and lines[1] not in INVALID_CPU_IDS:
                components.append(f"CPU:{lines[1]}")
        except Exception:
            pass
    
    elif platform.system() == "Linux":
        try:
            with open('/etc/machine-id', 'r') as f:
                machine_id = f.read().strip()
                if machine_id:
                    components.append(f"MACHINE:{machine_id}")
        except Exception:
            pass
    
    elif platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split('\n'):
                if 'IOPlatformUUID' in line:
                    uuid_val = line.split('"')[-2]
                    if uuid_val:
                        components.append(f"UUID:{uuid_val}")
                    break
        except Exception:
            pass
    
    # Fallback: MAC-адрес
    if not components:
        import uuid
        mac = uuid.getnode()
        if mac:
            mac_str = ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
            components.append(f"MAC:{mac_str}")
    
    if components:
        combined = "|".join(sorted(components))
        _CACHED_HWID = hashlib.sha256(combined.encode()).hexdigest()[:32]
    else:
        _CACHED_HWID = ""
    
    return _CACHED_HWID