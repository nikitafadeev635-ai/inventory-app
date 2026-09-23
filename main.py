import sys
import os
import httpx

# # Проверяем что мы меняем только свой процесс
# _original_http_proxy = os.environ.get("HTTP_PROXY")
# _original_https_proxy = os.environ.get("HTTPS_PROXY")

# # Очищаем прокси для нашего процесса
# os.environ.pop("HTTP_PROXY", None)
# os.environ.pop("HTTPS_PROXY", None)
# os.environ["NO_PROXY"] = "*"

# # Патчим httpx
# _OriginalAsyncClient = httpx.AsyncClient
# class _NoProxyAsyncClient(_OriginalAsyncClient):
#     def __init__(self, *args, **kwargs):
#         kwargs["trust_env"] = False
#         kwargs.setdefault("proxy", None)
#         super().__init__(*args, **kwargs)
# httpx.AsyncClient = _NoProxyAsyncClient

# # Логируем для отладки
# print(f"[Proxy] Было: HTTP_PROXY={_original_http_proxy}, HTTPS_PROXY={_original_https_proxy}")
# print(f"[Proxy] Стало: HTTP_PROXY={os.environ.get('HTTP_PROXY')}, HTTPS_PROXY={os.environ.get('HTTPS_PROXY')}")
# print(f"[Proxy] Изменения применены ТОЛЬКО к этому процессу Python")


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