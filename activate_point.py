"""
Скрипт активации точки на ПК.

Запускается ОДИН РАЗ администратором точки для привязки:
    python activate_point.py

Или в виде .exe:
    pyinstaller --onefile activate_point.py
"""
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QComboBox, QMessageBox,
                              QLineEdit, QGroupBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from config import SMARTSHELL_WAREHOUSE_IDS
from core.point_lock import (save_locked_point, get_locked_point, 
                              unlock_point, get_hardware_id, is_point_locked)


class ActivateDialog(QDialog):
    """Диалог первичной активации точки."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🔒 Активация точки")
        self.setFixedSize(500, 400)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Заголовок
        title = QLabel("🔒 Активация точки на ПК")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Информация о ПК
        hw_id = get_hardware_id()
        info = QLabel(
            f"<b>Идентификатор ПК:</b><br>"
            f"<code>{hw_id[:16]}...{hw_id[-8:]}</code><br><br>"
            f"Выберите точку для привязки к этому компьютеру.<br>"
            f"После привязки изменить точку сможет только администратор "
            f"с мастер-паролем."
        )
        info.setWordWrap(True)
        info.setFont(QFont("Segoe UI", 10))
        layout.addWidget(info)
        
        # Выбор точки
        group = QGroupBox("Точка продаж")
        group_layout = QVBoxLayout(group)
        
        self.point_combo = QComboBox()
        self.point_combo.setFont(QFont("Segoe UI", 12))
        for point_name in SMARTSHELL_WAREHOUSE_IDS.keys():
            self.point_combo.addItem(point_name)
        group_layout.addWidget(self.point_combo)
        
        layout.addWidget(group)
        
        # Разблокировка (если точка уже привязана)
        if is_point_locked():
            current = get_locked_point()
            unlock_group = QGroupBox(f"⚠ Текущая точка: {current or 'не определена'}")
            unlock_layout = QVBoxLayout(unlock_group)
            
            unlock_layout.addWidget(QLabel("Для смены точки введите мастер-пароль:"))
            self.master_pwd = QLineEdit()
            self.master_pwd.setEchoMode(QLineEdit.EchoMode.Password)
            self.master_pwd.setPlaceholderText("Мастер-пароль")
            unlock_layout.addWidget(self.master_pwd)
            
            self.unlock_btn = QPushButton("🔓 Снять привязку")
            self.unlock_btn.clicked.connect(self._on_unlock)
            unlock_layout.addWidget(self.unlock_btn)
            
            layout.addWidget(unlock_group)
        
        # Кнопки
        buttons = QHBoxLayout()
        
        self.activate_btn = QPushButton("✓  Привязать точку")
        self.activate_btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Medium))
        self.activate_btn.setMinimumHeight(44)
        self.activate_btn.clicked.connect(self._on_activate)
        buttons.addWidget(self.activate_btn)
        
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setMinimumHeight(44)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)
        
        layout.addLayout(buttons)
    
    def _on_activate(self):
        """Привязка выбранной точки."""
        point_name = self.point_combo.currentText()
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Привязать точку '{point_name}' к этому ПК?\n\n"
            f"После привязки сменить точку сможет только администратор.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success, message = save_locked_point(point_name)
            if success:
                QMessageBox.information(self, "Успех", message)
                self.accept()
            else:
                QMessageBox.critical(self, "Ошибка", message)
    
    def _on_unlock(self):
        """Снятие привязки по мастер-паролю."""
        if not hasattr(self, 'master_pwd'):
            return
        
        password = self.master_pwd.text()
        success, message = unlock_point(password)
        
        if success:
            QMessageBox.information(self, "Успех", message)
            # После снятия привязки можно закрыть диалог
            self.accept()
        else:
            QMessageBox.critical(self, "Ошибка", message)
            self.master_pwd.clear()


def main():
    app = QApplication(sys.argv)
    dialog = ActivateDialog()
    dialog.exec()


if __name__ == "__main__":
    main()