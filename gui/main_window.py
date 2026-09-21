from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QFrame, QSizePolicy, QMessageBox,
                             QDialog, QLineEdit, QInputDialog)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from gui.handover_dialog import HandoverDialog
from gui.inventory_window import InventoryWindow
from gui.theme_dialog import ThemeDialog
from core.session import current_session
from gui.styles import SmartShellColors


class MainWindow(QMainWindow):
    def __init__(self, client, parent=None):
        """
        Args:
            client: ApiClient (серверный прокси) или SmartShellClient (legacy).
        """
        super().__init__(parent)
        self.client = client
        self.inventory_window = None
        self._deposit_dialog = None  # ← Защита от повторного открытия диалога

        self.setWindowTitle("QFACT.Deductor")
        self.setMinimumSize(640, 480)
        self.resize(780, 580)

        self._build_ui()

        # Подписываемся на смену темы
        from gui.themes import theme_manager
        theme_manager.on_change(self._on_theme_changed)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---------- Карточка контента ----------
        card = QWidget()
        card.setObjectName("mainCard")
        card.setStyleSheet(f"""
            QWidget#mainCard {{
                background-color: {SmartShellColors.BG_ITEM_PRIMARY};
                border-radius: 16px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(24)
        card_layout.setContentsMargins(48, 48, 48, 48)

        # Логотип / заголовок
        title = QLabel("QFact.Deductor")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Inter", 42, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {SmartShellColors.TEXT_PRIMARY}; background: transparent;")
        card_layout.addWidget(title)

        subtitle = QLabel("Приложение для работы с системой на расширенном уровне")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setProperty("secondary", True)
        subtitle.setFont(QFont("Inter", 14))
        card_layout.addWidget(subtitle)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(
            f"color: {SmartShellColors.BORDER_GRAY_20}; "
            f"background-color: {SmartShellColors.BORDER_GRAY_20}; "
            f"max-height: 1px;"
        )
        card_layout.addWidget(line)

        # ---------- Кнопки ----------
        buttons = QVBoxLayout()
        buttons.setSpacing(12)
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Основная
        self.btn_handover = QPushButton("🔄  Начать пересменку")
        self.btn_handover.setFont(QFont("Inter", 16, QFont.Weight.Medium))
        self.btn_handover.setMinimumHeight(64)
        self.btn_handover.setMaximumWidth(420)
        self.btn_handover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_handover.clicked.connect(self._start_handover)
        buttons.addWidget(self.btn_handover)

        # Корректировка депозита
        self.btn_deposit = QPushButton("💰  Корректировка депозита")
        self.btn_deposit.setProperty("variant", "secondary")
        self.btn_deposit.setMinimumHeight(48)
        self.btn_deposit.setMaximumWidth(420)
        self.btn_deposit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_deposit.clicked.connect(self._open_deposit_dialog)
        buttons.addWidget(self.btn_deposit)

        # Темы оформления
        self.btn_themes = QPushButton("🎨  Темы оформления")
        self.btn_themes.setProperty("variant", "secondary")
        self.btn_themes.setMinimumHeight(48)
        self.btn_themes.setMaximumWidth(420)
        self.btn_themes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_themes.clicked.connect(self._open_theme_dialog)
        buttons.addWidget(self.btn_themes)

        # Сброс привязки (сервисная кнопка)
        self.btn_reset_point = QPushButton("🔓  Сбросить привязку точки")
        self.btn_reset_point.setProperty("variant", "secondary")
        self.btn_reset_point.setMinimumHeight(48)
        self.btn_reset_point.setMaximumWidth(420)
        self.btn_reset_point.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_point.clicked.connect(self._reset_point_lock)
        buttons.addWidget(self.btn_reset_point)

        card_layout.addLayout(buttons)

        # Футер
        footer = QLabel("© Все права защищены QFact  · CyberMG ")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setProperty("secondary", True)
        footer.setFont(QFont("Inter", 11))
        card_layout.addWidget(footer)

        # Центрируем карточку
        outer = QVBoxLayout()
        outer.addWidget(card)
        outer.setContentsMargins(32, 32, 32, 32)
        layout.addLayout(outer)

    # ============================================================
    #  ОБРАБОТЧИКИ
    # ============================================================
    def _start_handover(self):
        """
        Открывает диалог начала пересменки.
        
        Логика:
        1. HandoverDialog проверяет пароли ОБА сотрудников через verify_password
        2. При успехе делает финальный login и устанавливает current_session
        3. MainWindow просто получает данные и открывает InventoryWindow
        
        Авторизация НЕ дублируется — она уже выполнена в HandoverDialog.
        """
        dialog = HandoverDialog(self.client, parent=self)
        
        if dialog.exec() != QDialog.DialogCode.Accepted:
            # Пользователь нажал "Отмена"
            print("[MainWindow] ⚠ Пересменка отменена")
            return
        
        # Получаем данные сессии из диалога
        session_data = dialog.get_session_data()
        point_name = session_data.get("point_name", "")
        giver = session_data.get("giver", "")
        receiver = session_data.get("receiver", "")
        
        # Проверка что все данные на месте
        if not point_name or not giver or not receiver:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Не удалось получить данные сессии из диалога.\n"
                f"Точка: {point_name or '—'}\n"
                f"Отдающий: {giver or '—'}\n"
                f"Принимающий: {receiver or '—'}"
            )
            return
        
        print(f"[MainWindow] ✓ Начало пересменки:")
        print(f"  Точка: {point_name}")
        print(f"  Отдающий: {giver}")
        print(f"  Принимающий: {receiver}")
        
        # Устанавливаем время начала смены (если метод start существует)
        try:
            current_session.start(point_name, None, giver, receiver)
        except (AttributeError, TypeError):
            # Если метода start нет — просто устанавливаем поля вручную
            current_session.point_name = point_name
            current_session.giver = giver
            current_session.receiver = receiver
            current_session.is_open = True
        
        # Открываем окно инвентаризации
        self.inventory_window = InventoryWindow(self.client, parent=self)
        self.inventory_window.show()

    def _open_theme_dialog(self):
        """Открывает диалог выбора и управления темами."""
        dialog = ThemeDialog(self)
        dialog.exec()

    def _open_deposit_dialog(self):
        """
        Открывает диалог корректировки депозита.
        НЕ требует авторизации (пересменки).
        
        Защита от повторного открытия:
        - Если диалог уже открыт — просто активируем его
        - При закрытии диалога обнуляем ссылку
        """
        # Защита от повторного открытия
        if self._deposit_dialog is not None:
            # Диалог уже открыт — просто активируем его
            self._deposit_dialog.activateWindow()
            self._deposit_dialog.raise_()
            return
        
        from gui.deposit_dialog import DepositDialog
        
        # Создаём диалог
        self._deposit_dialog = DepositDialog(self.client, parent=self)
        self._deposit_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        
        # При закрытии диалога обнуляем ссылку
        self._deposit_dialog.finished.connect(self._on_deposit_dialog_closed)
        
        # Показываем диалог
        self._deposit_dialog.exec()

    def _on_deposit_dialog_closed(self, result):
        """Вызывается при закрытии диалога корректировки депозита."""
        self._deposit_dialog = None

    def _reset_point_lock(self):
        """Снимает привязку точки (требует мастер-пароль)."""
        from core.point_lock import unlock_point, is_point_locked
        
        if not is_point_locked():
            QMessageBox.information(
                self,
                "Привязка отсутствует",
                "Точка не привязана к этому ПК.\n"
                "Запустите activate_point.py для привязки."
            )
            return
        
        password, ok = QInputDialog.getText(
            self,
            "Сброс привязки",
            "Введите мастер-пароль для снятия привязки:",
            QLineEdit.EchoMode.Password,
        )
        
        if not ok or not password:
            return
        
        success, message = unlock_point(password)
        
        if success:
            QMessageBox.information(
                self,
                "Привязка снята",
                f"{message}\n\nТеперь запустите activate_point.py для новой привязки."
            )
        else:
            QMessageBox.critical(self, "Ошибка", message)

    def _on_theme_changed(self, theme):
        """Пересоздаёт UI при смене темы."""
        self._build_ui()

    def closeEvent(self, event):
        if current_session.is_open:
            ans = QMessageBox.question(
                self, "Активная смена",
                "Сейчас идёт активная пересменка. Выйти без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if ans == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()