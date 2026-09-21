"""
Диалог пересменки: выбор точки, подписи отдающего и принимающего.
Поиск сотрудников идёт через серверный прокси (ApiClient).
Требует верификации обоих сотрудников через /api/auth/verify_password.

Защита от случайного закрытия:
- Enter в полях ввода НЕ закрывает диалог
- Escape НЕ закрывает диалог
- Крестик (X) НЕ закрывает диалог
- Закрытие возможно ТОЛЬКО через кнопки "Начать пересменку" или "Отмена"
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QFrame, QWidget, QGroupBox, QRadioButton,
                             QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from config import POINTS
from core.api_client import ApiClient
from gui.login_widget import LoginWidget
from gui.styles import SmartShellColors


class HandoverDialog(QDialog):
    """
    Диалог начала пересменки.
    Требует верификации ОБА сотрудников перед accept().
    """
    
    def __init__(self, client: ApiClient, parent=None):
        super().__init__(parent)
        self.client = client
        
        self.setWindowTitle("Начало пересменки")
        self.setMinimumSize(700, 800)
        self.resize(750, 850)
        
        # Состояние верификации
        self._giver_verified = False
        self._receiver_verified = False
        
        # Кэшируем данные после успешной верификации
        self._giver_faname = ""
        self._giver_password = ""
        self._receiver_faname = ""
        
        # Загружаем кеш сотрудников ОДИН РАЗ
        self._employees_cache = self._load_employees_cache()
        
        self._build_ui()
        
        # 🆕 Защита от случайного закрытия
        self._allow_close = False
    
    # ============================================================
    #  🛡️ ЗАЩИТА ОТ СЛУЧАЙНОГО ЗАКРЫТИЯ
    # ============================================================
    def reject(self):
        """Явная отмена — только через кнопку 'Отмена'."""
        self._allow_close = True
        super().reject()

    def accept(self):
        """Явное подтверждение — только через 'Начать пересменку'."""
        self._allow_close = True
        super().accept()

    def closeEvent(self, event):
        """
        Блокирует закрытие диалога если не было явного accept()/reject().
        Защищает от Escape, крестика (X) и программного close().
        """
        if not self._allow_close:
            if self._giver_verified and self._receiver_verified:
                QMessageBox.information(
                    self,
                    "Подтвердите действие",
                    "Оба сотрудника верифицированы!\n\n"
                    "Нажмите '✓ Начать пересменку' чтобы продолжить\n"
                    "или 'Отмена' чтобы выйти."
                )
            else:
                print("[HandoverDialog] 🛡️ Закрытие заблокировано — "
                      "используйте кнопки внизу окна")
            
            event.ignore()
            return
        
        event.accept()
    
    def _load_employees_cache(self) -> list:
        """Загружает список всех сотрудников с сервера (один запрос)."""
        try:
            employees = self.client.search_employees("")
            print(f"[HandoverDialog] ✓ Кеш сотрудников загружен: {len(employees)} чел.")
            return employees
        except Exception as e:
            print(f"[HandoverDialog] ✗ Ошибка загрузки кеша: {e}")
            return []
    
    def _build_ui(self):
        p = SmartShellColors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        title = QLabel("Начало пересменки")
        title.setFont(QFont("Inter", 20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {p.text_primary};")
        layout.addWidget(title)
        
        subtitle = QLabel(
            "Оба сотрудника должны успешно подтвердить свои пароли"
        )
        subtitle.setFont(QFont("Inter", 12))
        subtitle.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(subtitle)
        
        # Виджет отдающего
        self.giver_widget = LoginWidget(self.client, "Отдающий смену")
        self.giver_widget.set_employees_cache(self._employees_cache)
        self.giver_widget.verified.connect(self._on_giver_verified)
        layout.addWidget(self.giver_widget)
        
        # Виджет принимающего
        self.receiver_widget = LoginWidget(self.client, "Принимающий смену")
        self.receiver_widget.set_employees_cache(self._employees_cache)
        self.receiver_widget.verified.connect(self._on_receiver_verified)
        layout.addWidget(self.receiver_widget)
        
        # ============================================================
        #  ВЫБОР ТОЧКИ
        # ============================================================
        from core.point_lock import get_locked_point, is_point_locked
        
        point_group = QGroupBox("Точка")
        point_group.setFont(QFont("Inter", 12, QFont.Weight.DemiBold))
        point_group.setStyleSheet(f"""
            QGroupBox {{
                color: {p.accent_blue};
                border: 1px solid {p.border_gray_20};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        point_layout = QVBoxLayout(point_group)
        point_layout.setSpacing(8)
        
        self.point_buttons = []
        self.selected_point = None
        
        locked_point = get_locked_point()
        
        if locked_point:
            info_label = QLabel(
                f"<b>🔒 Привязанная точка:</b><br>"
                f"<span style='font-size: 18px; color: {p.accent_blue};'>{locked_point}</span>"
            )
            info_label.setStyleSheet(f"color: {p.text_primary}; padding: 8px;")
            point_layout.addWidget(info_label)
            
            hint = QLabel(
                "Точка зафиксирована для этого ПК. "
                "Для смены используйте activate_point.py"
            )
            hint.setFont(QFont("Inter", 10))
            hint.setStyleSheet(f"color: {p.text_secondary};")
            hint.setWordWrap(True)
            point_layout.addWidget(hint)
            
            self.selected_point = locked_point
        
        else:
            warning = QLabel(
                "⚠ <b>Точка не привязана!</b> Запустите activate_point.py "
                "для первичной настройки ПК."
            )
            warning.setStyleSheet(f"color: #fbbf24; padding: 6px;")
            warning.setWordWrap(True)
            point_layout.addWidget(warning)
            
            for point_name in POINTS.keys():
                radio = QRadioButton(point_name)
                radio.setFont(QFont("Inter", 12))
                radio.setStyleSheet(f"color: {p.text_primary};")
                radio.toggled.connect(
                    lambda checked, name=point_name: 
                    self._on_point_selected(name) if checked else None
                )
                point_layout.addWidget(radio)
                self.point_buttons.append(radio)
            
            if self.point_buttons:
                self.point_buttons[0].blockSignals(True)
                self.point_buttons[0].setChecked(True)
                self.point_buttons[0].blockSignals(False)
                self.selected_point = list(POINTS.keys())[0]
        
        layout.addWidget(point_group)
        
        # ============================================================
        #  КНОПКИ
        # ============================================================
        buttons = QHBoxLayout()
        
        self.start_btn = QPushButton("✓  Начать пересменку")
        self.start_btn.setAutoDefault(False)  # 🆕 Enter не активирует
        self.start_btn.setDefault(False)      # 🆕 Не default-кнопка
        self.start_btn.setFont(QFont("Inter", 14, QFont.Weight.Medium))
        self.start_btn.setMinimumHeight(48)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2C87FD;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:pressed { background-color: #1d4ed8; }
            QPushButton:disabled {
                background-color: #374151;
                color: #6b7280;
            }
        """)
        buttons.addWidget(self.start_btn)
        
        buttons.addStretch()
        
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setAutoDefault(False)  # 🆕
        self.cancel_btn.setDefault(False)      # 🆕
        self.cancel_btn.setProperty("variant", "secondary")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)
        
        layout.addLayout(buttons)
        
        # Статус
        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Inter", 12))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        self._update_start_button()
    
    # ============================================================
    #  ОБРАБОТЧИКИ СИГНАЛОВ
    # ============================================================
    def _on_giver_verified(self, faname: str, verified: bool):
        """Сигнал от виджета отдающего."""
        self._giver_verified = verified
        print(f"[HandoverDialog] Отдающий: {faname} — verified={verified}")
        
        if verified:
            self._giver_faname = faname
            try:
                self._giver_password = self.giver_widget.get_password()
                print(f"[HandoverDialog] ✓ Отдающий закэширован: {faname}")
            except Exception as e:
                print(f"[HandoverDialog] ✗ Не удалось получить пароль: {e}")
                self._giver_password = ""
        
        self._update_start_button()
    
    def _on_receiver_verified(self, faname: str, verified: bool):
        """Сигнал от виджета принимающего."""
        self._receiver_verified = verified
        print(f"[HandoverDialog] Принимающий: {faname} — verified={verified}")
        
        if verified:
            self._receiver_faname = faname
            print(f"[HandoverDialog] ✓ Принимающий закэширован: {faname}")
        
        self._update_start_button()
    
    def _on_point_selected(self, point_name: str):
        """При выборе точки."""
        self.selected_point = point_name
        self._update_start_button()
    
    # ============================================================
    #  ОБНОВЛЕНИЕ СОСТОЯНИЯ
    # ============================================================
    def _update_start_button(self):
        """Обновляет состояние кнопки 'Начать пересменку'."""
        can_start = (
            self._giver_verified and 
            self._receiver_verified and 
            self.selected_point is not None
        )
        self.start_btn.setEnabled(can_start)
        
        if can_start:
            self.status_label.setText("✓ Оба сотрудника верифицированы. Готовы к началу.")
            self.status_label.setStyleSheet("color: #10b981;")
        else:
            parts = []
            if not self._giver_verified:
                parts.append("отдающий")
            if not self._receiver_verified:
                parts.append("принимающий")
            if parts:
                self.status_label.setText(f"⏳ Ожидается верификация: {', '.join(parts)}")
                self.status_label.setStyleSheet("color: #fbbf24;")
            else:
                self.status_label.setText("⏳ Выберите точку")
                self.status_label.setStyleSheet("color: #fbbf24;")
    
    # ============================================================
    #  НАЧАЛО ПЕРЕСМЕНКИ
    # ============================================================
    def _on_start_clicked(self):
        """При клике 'Начать пересменку'."""
        print("\n[HandoverDialog] 🔥 НАЧАЛО ПЕРЕСМЕНКИ")
        
        if not self._giver_verified:
            QMessageBox.warning(self, "Ошибка", "Отдающий не верифицирован")
            return
        if not self._receiver_verified:
            QMessageBox.warning(self, "Ошибка", "Принимающий не верифицирован")
            return
        if not self.selected_point:
            QMessageBox.warning(self, "Ошибка", "Не выбрана точка")
            return
        
        giver_faname = self._giver_faname
        giver_password = self._giver_password
        receiver_faname = self._receiver_faname
        
        if not giver_password:
            QMessageBox.critical(
                self, "Ошибка",
                "Не удалось получить пароль отдающего.\n"
                "Попробуйте пройти верификацию ещё раз."
            )
            return
        
        self.status_label.setText("⏳ Создание сессии...")
        self.status_label.setStyleSheet("color: #2C87FD;")
        self.start_btn.setEnabled(False)
        
        try:
            login_result = self.client.login(
                giver_faname, 
                giver_password, 
                self.selected_point
            )
            
            # Проверка результата
            login_failed = False
            error_msg = ""
            
            if login_result is None or login_result is False:
                login_failed = True
                error_msg = f"login() вернул {login_result}"
            elif isinstance(login_result, dict):
                if "error" in login_result or "detail" in login_result:
                    login_failed = True
                    error_msg = login_result.get("error") or login_result.get("detail")
                elif not login_result.get("access_token"):
                    login_failed = True
                    error_msg = "Нет access_token в ответе"
            
            if login_failed:
                QMessageBox.critical(
                    self, "Ошибка авторизации",
                    f"Не удалось создать сессию.\n\n"
                    f"Причина: {error_msg}"
                )
                self.start_btn.setEnabled(True)
                return
            
            # Сохраняем данные сессии
            from core.session import current_session
            current_session.giver = giver_faname
            current_session.receiver = receiver_faname
            current_session.point_name = self.selected_point
            current_session.is_open = True
            
            # Сохраняем токен если есть
            if isinstance(login_result, dict):
                if hasattr(current_session, 'token') and login_result.get("access_token"):
                    current_session.token = login_result["access_token"]
                if hasattr(current_session, 'warehouse_id') and login_result.get("warehouse_id"):
                    current_session.warehouse_id = login_result["warehouse_id"]
            
            print(f"[HandoverDialog] ✓ Сессия создана:")
            print(f"  Отдающий: {giver_faname}")
            print(f"  Принимающий: {receiver_faname}")
            print(f"  Точка: {self.selected_point}")
            
            self.accept()  # ← Только здесь закрываем диалог
        
        except Exception as e:
            print(f"[HandoverDialog] ✗ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self, "Ошибка",
                f"Ошибка создания сессии:\n\n{str(e)}"
            )
            self.start_btn.setEnabled(True)
    
    # ============================================================
    #  ПУБЛИЧНЫЕ МЕТОДЫ
    # ============================================================
    def get_session_data(self) -> dict:
        """Возвращает данные сессии для InventoryWindow."""
        return {
            "giver": self._giver_faname or self.giver_widget.get_faname(),
            "receiver": self._receiver_faname or self.receiver_widget.get_faname(),
            "point_name": self.selected_point,
        }