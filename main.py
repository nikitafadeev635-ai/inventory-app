import sys
import os
from pathlib import Path

# 🆕 КРИТИЧЕСКИ ВАЖНО для работы после сборки в .exe
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 🆕 Создание необходимых папок при запуске
if getattr(sys, 'frozen', False):
    # В режиме .exe создаём папки рядом с .exe
    base_dir = Path(sys.executable).parent
    
    # Папки которые должны существовать
    required_dirs = [
        "image",           # Картинки фона
        "assets",          # Ресурсы
        "reports",         # Отчёты
        "user_themes",     # Темы
        "mapping",         # Маппинг
        "cache",           # Кеш
        "logs",            # Логи
    ]
    
    for dir_name in required_dirs:
        dir_path = base_dir / dir_name
        if not dir_path.exists():
            dir_path.mkdir(exist_ok=True)
            print(f"[Startup] ✓ Создана папка: {dir_path}")

# === ДИАГНОСТИКА ПУТЕЙ ===
from core.paths import print_paths_info
print_paths_info()

import httpx

# ============================================================
# 🚫 ОТКЛЮЧЕНИЕ СИСТЕМНОГО ПРОКСИ (Playnow и других VPN)
# ============================================================
# 1. Очищаем переменные окружения с прокси
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

# 2. Глобально патчим httpx, чтобы он игнорировал системный прокси
_OriginalAsyncClient = httpx.AsyncClient


class _NoProxyAsyncClient(_OriginalAsyncClient):
    def __init__(self, *args, **kwargs):
        kwargs["trust_env"] = False
        kwargs.setdefault("proxy", None)
        super().__init__(*args, **kwargs)


httpx.AsyncClient = _NoProxyAsyncClient

_OriginalClient = httpx.Client


class _NoProxyClient(_OriginalClient):
    def __init__(self, *args, **kwargs):
        kwargs["trust_env"] = False
        kwargs.setdefault("proxy", None)
        super().__init__(*args, **kwargs)


httpx.Client = _NoProxyClient
# ============================================================


# ============================================================
# 🆕 ПРОВЕРКА ЦЕЛОСТНОСТИ ПРИЛОЖЕНИЯ
# ============================================================
def _validate_launch():
    """
    Проверяет легитимность запуска приложения.
    
    В dev-режиме (python main.py) проверка пропускается.
    В production (.exe) проверяет:
    1. Наличие point.lock
    2. Валидность хеша на сервере
    3. Совпадение HWID
    4. Валидность подписи
    
    При отказе - закрывает приложение.
    """
    from core.integrity_checker import validate_launch, is_frozen
    
    # В dev-режиме пропускаем проверку
    if not is_frozen():
        print("[Validate] 🔧 Dev-режим: проверка не требуется")
        return
    
    # Импорты только если в production режиме
    from core.point_lock import get_lock_data
    from config import PROXY_SERVER_URL, API_SECRET_KEY
    
    print("=" * 60)
    print("🔐 ПРОВЕРКА ЦЕЛОСТНОСТИ ПРИЛОЖЕНИЯ")
    print("=" * 60)
    
    # Читаем point.lock
    lock_data = get_lock_data()
    if not lock_data:
        print("[Validate] ❌ point.lock не найден")
        print("[Validate] ⚠️  Запустите activate_point.exe для привязки точки")
        print("\nИнструкция:")
        print("  1. Запустите: activate_point.exe \"НазваниеТочки\"")
        print("  2. После создания point.lock удалите activate_point.exe")
        print("  3. Запустите inventory_app.exe снова")
        input("\nНажмите Enter для выхода...")
        sys.exit(1)
    
    point_name = lock_data.get("point_name")
    signature = lock_data.get("signature")
    
    if not point_name or not signature:
        print("[Validate] ❌ point.lock повреждён (нет point_name или signature)")
        print("[Validate] ⚠️  Повторите привязку точки через activate_point.exe")
        input("\nНажмите Enter для выхода...")
        sys.exit(1)
    
    # Валидируем на сервере
    result = validate_launch(
        server_url=PROXY_SERVER_URL,
        api_key=API_SECRET_KEY,
        point_name=point_name,
        signature=signature
    )
    
    if not result.get("allowed"):
        reason = result.get("reason", "Неизвестная причина")
        print(f"\n{'=' * 60}")
        print(f"🚫 ЗАПУСК ЗАПРЕЩЁН")
        print(f"{'=' * 60}")
        print(f"Причина: {reason}")
        print(f"\nВозможные решения:")
        print(f"  - Обновите приложение до актуальной версии")
        print(f"  - Проверьте подключение к интернету")
        print(f"  - Обратитесь к администратору системы")
        print(f"{'=' * 60}")
        input("\nНажмите Enter для выхода...")
        sys.exit(1)
    
    if result.get("offline_mode"):
        print(f"[Validate] ⚠️  Offline режим: {result.get('reason')}")
        print(f"[Validate] ℹ️  Приложение работает без проверки на сервере")
    else:
        version = result.get("version", "?")
        print(f"[Validate] ✓ Версия: {version}")
        print(f"[Validate] ✓ Точка: {point_name}")
    
    print("=" * 60)


# Запускаем проверку целостности
_validate_launch()
# ============================================================


# === ВАШИ ОБЫЧНЫЕ ИМПОРТЫ ===
from PyQt6.QtWidgets import QApplication, QMessageBox
from core.api_client import ApiClient
from gui.main_window import MainWindow
from gui.styles import apply_global_style
from gui.themes import theme_manager, SMARTSHELL_DARK


def main():
    app = QApplication(sys.argv)
    theme_manager.apply_theme(SMARTSHELL_DARK, app)

    client = ApiClient()
    window = MainWindow(client)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()