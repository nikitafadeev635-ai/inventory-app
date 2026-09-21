"""
Виджет авторизации сотрудника.

Использует ЛОКАЛЬНУЮ фильтрацию из кешированного списка сотрудников
(полученного при открытии HandoverDialog), чтобы не делать запросы
к серверу на каждый введённый символ.

Поток работы:
1. HandoverDialog получает всех сотрудников (один запрос)
2. Передаёт список в LoginWidget через set_employees_cache()
3. LoginWidget фильтрует локально при вводе (без запросов!)
4. После выбора сотрудника запрашивается пароль
5. Пароль проверяется через verify_password (реальный запрос)
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QGroupBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

from core.api_client import ApiClient
from gui.styles import SmartShellColors


class LoginWidget(QWidget):
    """
    Виджет ввода ФИО и пароля сотрудника.
    
    Signals:
        verified(str, bool): (faname, is_verified) — эмитится после проверки пароля
    """
    verified = pyqtSignal(str, bool)

    def __init__(self, client: ApiClient, title: str = "Сотрудник", parent=None):
        super().__init__(parent)
        self.client = client
        self.title = title
        
        self._employees_cache = []  # ← Кеш всех сотрудников
        self._is_verified = False
        self._selected_faname = None
        
        # Debounce таймер для фильтрации (локальной)
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(100)  # 100мс для плавности
        self._filter_timer.timeout.connect(self._perform_local_filter)
        
        self._build_ui()

    def _build_ui(self):
        p = SmartShellColors
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)  # Убрали отступы
        
        # Заголовок БЕЗ рамки QGroupBox
        title_label = QLabel(self.title)
        title_label.setFont(QFont("Inter", 14, QFont.Weight.DemiBold))
        title_label.setStyleSheet(f"color: {p.accent_blue}; margin-bottom: 4px;")
        layout.addWidget(title_label)

        # Поле поиска ФИО
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Начните вводить ФИО...")
        self.search_input.setFont(QFont("Inter", 13))
        self.search_input.setMinimumHeight(44)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {p.bg_item_primary};
                color: {p.text_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            QLineEdit:focus {{
                border: 2px solid {p.accent_blue};
            }}
        """)
        layout.addWidget(self.search_input)

        # Список автодополнения
        self.employee_list = QListWidget()
        self.employee_list.setMaximumHeight(160)
        self.employee_list.setVisible(False)
        self.employee_list.itemClicked.connect(self._on_employee_selected)
        self.employee_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {p.bg_item_primary};
                color: {p.text_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background-color: {p.accent_blue}20;
            }}
            QListWidget::item:selected {{
                background-color: {p.accent_blue};
                color: white;
            }}
        """)
        layout.addWidget(self.employee_list)

        # Поле пароля (изначально отключено)
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("🔒 Введите пароль...")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setFont(QFont("Inter", 13))
        self.password_input.setMinimumHeight(44)
        self.password_input.setEnabled(False)
        self.password_input.returnPressed.connect(self._verify)
        self.password_input.textChanged.connect(self._on_password_changed)
        self.password_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {p.bg_item_primary};
                color: {p.text_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            QLineEdit:focus {{
                border: 2px solid {p.accent_blue};
            }}
            QLineEdit:disabled {{
                background-color: {p.bg_item_primary}80;
                color: {p.text_secondary};
            }}
        """)
        layout.addWidget(self.password_input)

        # Статус-строка
        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Inter", 11))
        self.status_label.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(self.status_label)

    # ============================================================
    #  КЕШИРОВАНИЕ
    # ============================================================
    def set_employees_cache(self, employees: list):
        """
        Устанавливает кеш всех сотрудников.
        Вызывается HandoverDialog при открытии (один запрос на весь диалог).
        
        Args:
            employees: список ФИО сотрудников
        """
        self._employees_cache = employees or []
        print(f"[LoginWidget] {self.title}: кеш загружен, "
              f"{len(self._employees_cache)} сотрудников")

    # ============================================================
    #  ОБРАБОТЧИКИ
    # ============================================================
    def _on_search_changed(self, text):
        """При изменении текста поиска — перезапускаем таймер."""
        self._is_verified = False
        self._selected_faname = None
        self.password_input.setEnabled(False)
        self.password_input.clear()
        self.verified.emit("", False)
        
        if not text or len(text.strip()) < 1:
            self.employee_list.setVisible(False)
            self.employee_list.clear()
            self._filter_timer.stop()
            return
        
        # Запускаем таймер для локальной фильтрации
        self._filter_timer.start()

    def _perform_local_filter(self):
        """Фильтрует кеш локально (БЕЗ запросов к серверу!)."""
        query = self.search_input.text().strip().lower()
        if not query or not self._employees_cache:
            self.employee_list.setVisible(False)
            return
        
        # Локальная фильтрация по кешированному списку
        matches = [
            emp for emp in self._employees_cache 
            if query in emp.lower()
        ][:10]  # Показываем максимум 10 результатов
        
        self.employee_list.clear()
        if matches:
            for emp in matches:
                self.employee_list.addItem(QListWidgetItem(emp))
            self.employee_list.setVisible(True)
        else:
            self.employee_list.setVisible(False)

    def _on_employee_selected(self, item):
        """При выборе сотрудника из списка."""
        faname = item.text()
        self._selected_faname = faname
        
        # Заполняем поле поиска выбранным ФИО
        self.search_input.blockSignals(True)
        self.search_input.setText(faname)
        self.search_input.blockSignals(False)
        
        # Скрываем список
        self.employee_list.setVisible(False)
        
        # Активируем поле пароля
        self.password_input.setEnabled(True)
        self.password_input.setFocus()
        
        self._set_status(f"✓ Выбран: {faname}. Введите пароль.", "#2C87FD")

    def _on_password_changed(self, text):
        """При изменении пароля — сбрасываем верификацию."""
        self._is_verified = False
        self.verified.emit(self._selected_faname or "", False)

    # ============================================================
    #  ВЕРИФИКАЦИЯ
    # ============================================================
    def _verify(self):
        """Проверяет пароль через сервер (реальный запрос)."""
        if not self._selected_faname:
            self._set_status("⚠ Сначала выберите сотрудника", "#fbbf24")
            return
        
        password = self.password_input.text()
        if not password:
            self._set_status("⚠ Введите пароль", "#fbbf24")
            return
        
        self._set_status("⏳ Проверка пароля...", "#2C87FD")
        self.password_input.setEnabled(False)
        
        try:
            result = self.client.verify_password(self._selected_faname, password)
            
            if result.get("verified"):
                self._is_verified = True
                self._set_status(f"✓ {self._selected_faname} верифицирован", "#10b981")
                self.verified.emit(self._selected_faname, True)
                
                # Делаем поля read-only после успешной верификации
                self.search_input.setEnabled(False)
                self.password_input.setEnabled(False)
            else:
                error = result.get("error", "Неверный пароль")
                self._set_status(f"✗ {error}", "#ef4444")
                self.verified.emit(self._selected_faname, False)
                self.password_input.setEnabled(True)
                self.password_input.clear()
                self.password_input.setFocus()
        
        except Exception as e:
            self._set_status(f"✗ Ошибка: {e}", "#ef4444")
            self.password_input.setEnabled(True)

    # ============================================================
    #  ПУБЛИЧНЫЕ МЕТОДЫ
    # ============================================================
    def _set_status(self, text: str, color: str):
        """Обновляет статус-строку."""
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")

    def get_faname(self) -> str:
        """Возвращает ФИО верифицированного сотрудника."""
        return self._selected_faname or ""

    def get_password(self) -> str:
        """Возвращает введённый пароль."""
        return self.password_input.text()

    def is_verified(self) -> bool:
        """Возвращает статус верификации."""
        return self._is_verified