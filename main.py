import sys
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