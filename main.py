import sys
import os

# 🆕 КРИТИЧЕСКИ ВАЖНО для работы после сборки в .exe
# Меняем рабочую директорию на папку где лежит приложение
if getattr(sys, 'frozen', False):
    # Запущен как .exe → cwd = папка с .exe
    os.chdir(os.path.dirname(sys.executable))
else:
    # Запущен как .py → cwd = корень проекта
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# === ДИАГНОСТИКА ПУТЕЙ (опционально, можно удалить после проверки) ===
from core.paths import print_paths_info
print_paths_info()
# ====================================================================

# 🚫 ОТКЛЮЧЕНИЕ СИСТЕМНОГО ПРОКСИ (Playnow и других VPN)
# ... дальше весь существующий код main.py без изменений ...

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
# Это применится ко ВСЕМ вызовам httpx в проекте без изменения других файлов
_OriginalAsyncClient = httpx.AsyncClient


class _NoProxyAsyncClient(_OriginalAsyncClient):
    def __init__(self, *args, **kwargs):
        kwargs["trust_env"] = False
        kwargs.setdefault("proxy", None)  # httpx 0.28+
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