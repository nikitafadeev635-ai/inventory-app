"""
Диалог корректировки депозита клиента.

Позволяет найти клиента по телефону, просмотреть его данные
и изменить депозит с указанием причины.

НЕ требует авторизации (пересменки). Оператор не выбирается —
определяется по точке + времени + IP в логах.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QLineEdit, QTextEdit, QGroupBox,
                             QMessageBox, QComboBox, QDoubleSpinBox, QFormLayout)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from config import POINTS
from core.api_client import ApiClient
from gui.styles import SmartShellColors


class DepositDialog(QDialog):
    """Диалог корректировки депозита клиента."""

    def __init__(self, client: ApiClient, parent=None):
        super().__init__(parent)
        self.client = client
        self._client_data = None

        self.setWindowTitle("💰 Корректировка депозита")
        self.setMinimumSize(650, 750)
        self.resize(700, 800)

        self._build_ui()

    def _build_ui(self):
        p = SmartShellColors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # ============================================================
        #  ЗАГОЛОВОК
        # ============================================================
        title = QLabel("💰 Корректировка депозита")
        title.setFont(QFont("Inter", 20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {p.text_primary};")
        layout.addWidget(title)

        subtitle = QLabel("Найдите клиента по номеру телефона и скорректируйте баланс")
        subtitle.setFont(QFont("Inter", 12))
        subtitle.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(subtitle)

        # ============================================================
        #  ВЫБОР ТОЧКИ (из .lock или список)
        # ============================================================
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

        try:
            from core.point_lock import get_locked_point
            locked_point = get_locked_point()
        except ImportError:
            locked_point = None

        if locked_point:
            point_label = QLabel(f"🔒 <b>{locked_point}</b>")
            point_label.setFont(QFont("Inter", 14))
            point_label.setStyleSheet(f"color: {p.accent_blue}; padding: 4px;")
            point_layout.addWidget(point_label)
            self._point_name = locked_point
        else:
            self._point_combo = QComboBox()
            self._point_combo.setFont(QFont("Inter", 12))
            for name in POINTS.keys():
                self._point_combo.addItem(name)
            point_layout.addWidget(self._point_combo)
            self._point_name = None

        layout.addWidget(point_group)

        # ============================================================
        #  ПОИСК КЛИЕНТА
        # ============================================================
        search_group = QGroupBox("Поиск клиента")
        search_group.setFont(QFont("Inter", 12, QFont.Weight.DemiBold))
        search_group.setStyleSheet(f"""
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
        search_layout = QHBoxLayout(search_group)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("📱 Введите номер телефона (например: 79141234567)")
        self.phone_input.setFont(QFont("Inter", 14))
        self.phone_input.setMinimumHeight(44)
        self.phone_input.returnPressed.connect(self._search_client)
        search_layout.addWidget(self.phone_input, 3)

        self.search_btn = QPushButton("🔍 Найти")
        self.search_btn.setFont(QFont("Inter", 13, QFont.Weight.Medium))
        self.search_btn.setMinimumHeight(44)
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_btn.clicked.connect(self._search_client)
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #2C87FD; color: white;
                border: none; border-radius: 6px; padding: 10px 20px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:disabled { background-color: #374151; color: #6b7280; }
        """)
        search_layout.addWidget(self.search_btn)

        layout.addWidget(search_group)

        # ============================================================
        #  ИНФОРМАЦИЯ О КЛИЕНТЕ
        # ============================================================
        self.client_group = QGroupBox("Информация о клиенте")
        self.client_group.setFont(QFont("Inter", 12, QFont.Weight.DemiBold))
        self.client_group.setStyleSheet(f"""
            QGroupBox {{
                color: #10b981;
                border: 1px solid #10b981;
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
        client_layout = QFormLayout(self.client_group)
        client_layout.setSpacing(8)

        label_style = f"color: {p.text_secondary}; font-size: 12px;"
        value_style = f"color: {p.text_primary}; font-size: 14px; font-weight: 600;"

        self.lbl_uuid = QLabel("—")
        self.lbl_uuid.setStyleSheet(value_style)
        self.lbl_uuid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        client_layout.addRow(self._make_label("UUID:", label_style), self.lbl_uuid)

        self.lbl_nickname = QLabel("—")
        self.lbl_nickname.setStyleSheet(value_style)
        client_layout.addRow(self._make_label("Никнейм:", label_style), self.lbl_nickname)

        self.lbl_phone = QLabel("—")
        self.lbl_phone.setStyleSheet(value_style)
        client_layout.addRow(self._make_label("Телефон:", label_style), self.lbl_phone)

        self.lbl_deposit = QLabel("—")
        self.lbl_deposit.setStyleSheet(f"color: #fbbf24; font-size: 18px; font-weight: bold;")
        client_layout.addRow(self._make_label("Депозит:", label_style), self.lbl_deposit)

        self.lbl_bonus = QLabel("—")
        self.lbl_bonus.setStyleSheet(value_style)
        client_layout.addRow(self._make_label("Бонус:", label_style), self.lbl_bonus)

        self.lbl_group = QLabel("—")
        self.lbl_group.setStyleSheet(value_style)
        client_layout.addRow(self._make_label("Группа:", label_style), self.lbl_group)

        self.client_group.setVisible(False)
        layout.addWidget(self.client_group)

        # ============================================================
        #  ФОРМА КОРРЕКТИРОВКИ
        # ============================================================
        self.form_group = QGroupBox("Корректировка")
        self.form_group.setFont(QFont("Inter", 12, QFont.Weight.DemiBold))
        self.form_group.setStyleSheet(f"""
            QGroupBox {{
                color: #f59e0b;
                border: 1px solid #f59e0b;
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
        form_layout = QVBoxLayout(self.form_group)
        form_layout.setSpacing(12)

        balance_row = QHBoxLayout()
        balance_label = QLabel("Новый баланс (₽):")
        balance_label.setFont(QFont("Inter", 13, QFont.Weight.Medium))
        balance_label.setStyleSheet(f"color: {p.text_primary};")
        balance_row.addWidget(balance_label)

        self.balance_input = QDoubleSpinBox()
        self.balance_input.setRange(0, 9999999.99)
        self.balance_input.setDecimals(2)
        self.balance_input.setSuffix(" ₽")
        self.balance_input.setFont(QFont("Inter", 16, QFont.Weight.Bold))
        self.balance_input.setMinimumHeight(44)
        self.balance_input.setMinimumWidth(180)
        self.balance_input.valueChanged.connect(self._on_form_changed)
        balance_row.addWidget(self.balance_input)
        balance_row.addStretch()
        form_layout.addLayout(balance_row)

        reason_label = QLabel("Причина корректировки (5–700 символов):")
        reason_label.setFont(QFont("Inter", 12, QFont.Weight.Medium))
        reason_label.setStyleSheet(f"color: {p.text_primary};")
        form_layout.addWidget(reason_label)

        self.reason_input = QTextEdit()
        self.reason_input.setPlaceholderText("Например: слетел пакет ночь, ошибка кассира...")
        self.reason_input.setFont(QFont("Inter", 12))
        self.reason_input.setMaximumHeight(100)
        self.reason_input.textChanged.connect(self._on_form_changed)
        form_layout.addWidget(self.reason_input)

        self.char_count_label = QLabel("0 / 700")
        self.char_count_label.setFont(QFont("Inter", 10))
        self.char_count_label.setStyleSheet(f"color: {p.text_secondary};")
        self.char_count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.addWidget(self.char_count_label)

        self.form_group.setVisible(False)
        layout.addWidget(self.form_group)

        # ============================================================
        #  КНОПКИ
        # ============================================================
        buttons = QHBoxLayout()

        self.apply_btn = QPushButton("💰  Изменить депозит")
        self.apply_btn.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        self.apply_btn.setMinimumHeight(52)
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        self.apply_btn.setEnabled(False)
        self.apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b; color: white;
                border: none; border-radius: 8px; padding: 14px 24px;
            }
            QPushButton:hover { background-color: #d97706; }
            QPushButton:pressed { background-color: #b45309; }
            QPushButton:disabled { background-color: #374151; color: #6b7280; }
        """)
        buttons.addWidget(self.apply_btn)

        buttons.addStretch()

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setProperty("variant", "secondary")
        self.close_btn.setMinimumHeight(52)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)

        layout.addLayout(buttons)

        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Inter", 11))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

    # ============================================================
    #  ВСПОМОГАТЕЛЬНЫЕ
    # ============================================================
    def _make_label(self, text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    def _get_point_name(self) -> str:
        if self._point_name:
            return self._point_name
        if hasattr(self, '_point_combo'):
            return self._point_combo.currentText()
        return ""

    # ============================================================
    #  ПОИСК КЛИЕНТА
    # ============================================================
    def _search_client(self):
        phone = self.phone_input.text().strip()
        if not phone:
            self._set_status("⚠ Введите номер телефона", "#fbbf24")
            return

        point = self._get_point_name()
        if not point:
            self._set_status("⚠ Выберите точку", "#fbbf24")
            return

        self._set_status("⏳ Поиск клиента...", "#2C87FD")
        self.search_btn.setEnabled(False)

        try:
            result = self.client.search_client_by_phone(phone, point)

            if result.get("found") and result.get("client"):
                self._client_data = result["client"]
                self._show_client_info(self._client_data)
                self._set_status(f"✓ Клиент найден: {self._client_data.get('nickname', '—')}", "#10b981")
            else:
                self._client_data = None
                self.client_group.setVisible(False)
                self.form_group.setVisible(False)
                self.apply_btn.setEnabled(False)
                error = result.get("error", "Клиент не найден")
                self._set_status(f"✗ {error}", "#ef4444")

        except Exception as e:
            self._set_status(f"✗ Ошибка: {e}", "#ef4444")
        finally:
            self.search_btn.setEnabled(True)

    def _show_client_info(self, data: dict):
        self.lbl_uuid.setText(data.get("uuid", "—"))
        self.lbl_nickname.setText(data.get("nickname", "—"))
        self.lbl_phone.setText(data.get("phone", "—"))

        deposit = data.get("deposit", 0) or 0
        self.lbl_deposit.setText(f"{deposit:.2f} ₽")
        self.balance_input.setValue(float(deposit))

        bonus = data.get("bonus", 0) or 0
        self.lbl_bonus.setText(f"{bonus:.2f} ₽")

        group = data.get("group")
        group_name = group.get("title", "—") if group else "—"
        self.lbl_group.setText(group_name)

        self.client_group.setVisible(True)
        self.form_group.setVisible(True)
        self._on_form_changed()

    # ============================================================
    #  ФОРМА КОРРЕКТИРОВКИ
    # ============================================================
    def _on_form_changed(self):
        if not self._client_data:
            self.apply_btn.setEnabled(False)
            return

        reason = self.reason_input.toPlainText().strip()
        reason_len = len(reason)

        if reason_len > 700:
            self.char_count_label.setText(f"{reason_len} / 700 ⚠")
            self.char_count_label.setStyleSheet("color: #ef4444;")
        elif reason_len >= 5:
            self.char_count_label.setText(f"{reason_len} / 700 ✓")
            self.char_count_label.setStyleSheet("color: #10b981;")
        else:
            self.char_count_label.setText(f"{reason_len} / 700")
            self.char_count_label.setStyleSheet("color: #6b7280;")

        can_apply = 5 <= reason_len <= 700
        self.apply_btn.setEnabled(can_apply)

    # ============================================================
    #  ПРИМЕНЕНИЕ
    # ============================================================
    def _on_apply_clicked(self):
        if not self._client_data:
            return

        nickname = self._client_data.get("nickname", "—")
        phone = self._client_data.get("phone", "—")
        client_uuid = self._client_data.get("uuid", "")
        new_deposit = self.balance_input.value()
        reason = self.reason_input.toPlainText().strip()
        old_deposit = self._client_data.get("deposit", 0) or 0

        reply = QMessageBox.question(
            self,
            "⚠ Подтверждение корректировки",
            f"Вы уверены, что хотите откорректировать депозит?\n\n"
            f"Клиент: <b>{nickname}</b> ({phone})\n"
            f"Текущий депозит: <b>{old_deposit:.2f} ₽</b>\n"
            f"Новый депозит: <b>{new_deposit:.2f} ₽</b>\n"
            f"Разница: <b>{new_deposit - old_deposit:+.2f} ₽</b>\n\n"
            f"Причина: {reason}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._set_status("⏳ Применение корректировки...", "#2C87FD")
        self.apply_btn.setEnabled(False)

        try:
            point = self._get_point_name()
            result = self.client.update_client_deposit(
                client_uuid=client_uuid,
                new_deposit=new_deposit,
                reason=reason,
                point_name=point,
                client_nickname=nickname,
                client_phone=phone,
                old_deposit=old_deposit,
            )

            if result.get("success"):
                new_dep = result.get("deposit", new_deposit)
                self._set_status(
                    f"✓ Депозит {nickname} изменён на {new_dep:.2f} ₽",
                    "#10b981"
                )
                QMessageBox.information(
                    self,
                    "Успех",
                    f"Депозит клиента <b>{nickname}</b> успешно изменён.\n\n"
                    f"Новый баланс: <b>{new_dep:.2f} ₽</b>\n\n"
                    f"Уведомление отправлено в Telegram."
                )
                self._client_data["deposit"] = new_dep
                self.lbl_deposit.setText(f"{new_dep:.2f} ₽")
                self.balance_input.setValue(new_dep)
                self.reason_input.clear()
            else:
                error_msg = result.get("message", "Неизвестная ошибка")
                self._set_status(f"✗ {error_msg}", "#ef4444")
                QMessageBox.critical(
                    self,
                    "Ошибка",
                    f"Не удалось изменить депозит:\n{error_msg}"
                )

        except Exception as e:
            self._set_status(f"✗ Ошибка: {e}", "#ef4444")
            QMessageBox.critical(self, "Ошибка", str(e))
        finally:
            self._on_form_changed()

    def _set_status(self, text: str, color: str):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")