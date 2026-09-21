"""
Диалог Trouble — указание причин расхождений по ГРУППАМ товаров.
Показывает группы с чистой недостачей (с учётом пересортицы).
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget,
                             QComboBox, QLineEdit, QSpinBox,
                             QMessageBox, QFrame)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.normalization import (REASONS_LESS, REASONS_MORE,
                                 ALL_EXCUSABLE_REASONS)
from gui.styles import SmartShellColors


class TroubleBlock:
    """Один блок разбиения (количество + причина + ссылка)."""
    def __init__(self, quantity: int = 1, reason: str = "", reference: str = ""):
        self.quantity = quantity
        self.reason = reason
        self.reference = reference


class TroubleGroup:
    """
    Группа товаров с чистой недостачей.
    """
    def __init__(self, group_name: str, net_delta: int, unit_cost: float,
                 total_stock: int, total_actual: int):
        self.group_name = group_name
        self.net_delta = net_delta
        self.unit_cost = unit_cost
        self.total_stock = total_stock
        self.total_actual = total_actual
        self.status = "less" if net_delta < 0 else "more"
        self.blocks: list = []


class TroubleBlockWidget(QWidget):
    """Виджет одного блока разбиения."""

    def __init__(self, group: TroubleGroup, block: TroubleBlock,
                 on_remove, on_changed, parent=None):
        super().__init__(parent)
        self.group = group
        self.block = block
        self._on_remove = on_remove
        self._on_changed = on_changed
        self._build_ui()

    def _build_ui(self):
        p = SmartShellColors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        qty_label = QLabel("Кол-во:")
        qty_label.setFont(QFont("Inter", 11))
        qty_label.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(qty_label)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, max(1, abs(self.group.net_delta)))
        self.qty_spin.setValue(self.block.quantity)
        self.qty_spin.setFixedWidth(80)
        self.qty_spin.setStyleSheet(f"""
            QSpinBox {{
                background: {p.bg_item_primary};
                color: {p.text_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 4px;
                padding: 4px;
            }}
        """)
        self.qty_spin.valueChanged.connect(self._on_field_changed)
        layout.addWidget(self.qty_spin)

        reason_label = QLabel("Причина:")
        reason_label.setFont(QFont("Inter", 11))
        reason_label.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(reason_label)

        self.reason_combo = QComboBox()
        reasons = REASONS_LESS if self.group.status == "less" else REASONS_MORE
        self.reason_combo.addItems(reasons)
        if self.block.reason in reasons:
            self.reason_combo.setCurrentText(self.block.reason)
        self.reason_combo.setMinimumWidth(280)
        self.reason_combo.setStyleSheet(f"""
            QComboBox {{
                background: {p.bg_item_primary};
                color: {p.text_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.reason_combo.currentTextChanged.connect(self._on_field_changed)
        layout.addWidget(self.reason_combo)

        ref_label = QLabel("Ссылка:")
        ref_label.setFont(QFont("Inter", 11))
        ref_label.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(ref_label)

        self.ref_edit = QLineEdit()
        self.ref_edit.setPlaceholderText("https://t.me/... или описание")
        self.ref_edit.setText(self.block.reference)
        self.ref_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {p.bg_item_primary};
                color: {p.text_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.ref_edit.textChanged.connect(self._on_field_changed)
        layout.addWidget(self.ref_edit, 1)

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedSize(32, 32)
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background: #dc2626; color: white;
                border: none; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background: #b91c1c; }
        """)
        self.remove_btn.clicked.connect(lambda: self._on_remove(self))
        layout.addWidget(self.remove_btn)

    def _on_field_changed(self, *args):
        self.block.quantity = self.qty_spin.value()
        self.block.reason = self.reason_combo.currentText()
        self.block.reference = self.ref_edit.text().strip()
        self._on_changed()

    def is_valid(self) -> tuple:
        if self.block.reason in ALL_EXCUSABLE_REASONS:
            if not self.block.reference:
                return False, f"Для причины '{self.block.reason}' обязательна ссылка"
        return True, ""


class TroubleGroupWidget(QWidget):
    """Виджет группы с блоками разбиения."""

    def __init__(self, group: TroubleGroup, on_changed, parent=None):
        super().__init__(parent)
        self.group = group
        self._on_changed = on_changed
        self._block_widgets: list = []
        self._build_ui()

        if not self.group.blocks:
            self._add_block(TroubleBlock(quantity=abs(self.group.net_delta)))

    def _build_ui(self):
        p = SmartShellColors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.setStyleSheet(f"""
            TroubleGroupWidget {{
                background: {p.bg_item_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 8px;
                margin: 4px 0;
            }}
        """)

        header = QHBoxLayout()

        icon = "🔴" if self.group.status == "less" else "🔵"
        type_text = "Недостача" if self.group.status == "less" else "Избыток"

        title_label = QLabel(
            f"{icon} <b>{self.group.group_name}</b>"
        )
        title_label.setFont(QFont("Inter", 14))
        title_label.setStyleSheet(f"color: {p.text_primary}; background: transparent;")
        header.addWidget(title_label)

        header.addStretch()

        detail_label = QLabel(
            f"Учёт: {self.group.total_stock} → Факт: {self.group.total_actual} | "
            f"Чистая {type_text.lower()}: <b>{abs(self.group.net_delta)} шт</b> × "
            f"{self.group.unit_cost:.0f}₽ = "
            f"<b>{abs(self.group.net_delta) * self.group.unit_cost:.0f}₽</b>"
        )
        detail_label.setFont(QFont("Inter", 11))
        detail_label.setStyleSheet(f"color: {p.text_secondary}; background: transparent;")
        header.addWidget(detail_label)

        layout.addLayout(header)

        self.blocks_container = QVBoxLayout()
        self.blocks_container.setSpacing(4)
        layout.addLayout(self.blocks_container)

        bottom = QHBoxLayout()

        self.remainder_label = QLabel("")
        self.remainder_label.setFont(QFont("Inter", 11))
        self.remainder_label.setStyleSheet(f"color: {p.text_secondary}; background: transparent;")
        bottom.addWidget(self.remainder_label)

        bottom.addStretch()

        self.add_btn = QPushButton("+ Добавить блок")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: rgba(44, 135, 253, 0.15);
                color: #2C87FD;
                border: 1px solid #2C87FD;
                border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover { background: rgba(44, 135, 253, 0.25); }
        """)
        self.add_btn.clicked.connect(self._on_add_block)
        bottom.addWidget(self.add_btn)

        layout.addLayout(bottom)

    def _add_block(self, block=None):
        if block is None:
            block = TroubleBlock(quantity=1)
        self.group.blocks.append(block)

        widget = TroubleBlockWidget(
            self.group, block,
            on_remove=self._on_remove_block,
            on_changed=self._update_remainder,
        )
        self._block_widgets.append(widget)
        self.blocks_container.addWidget(widget)
        self._update_remainder()

    def _on_add_block(self):
        self._add_block()

    def _on_remove_block(self, widget):
        if len(self._block_widgets) <= 1:
            QMessageBox.warning(self, "Нельзя удалить", "Должен остаться хотя бы один блок.")
            return

        if widget.block in self.group.blocks:
            self.group.blocks.remove(widget.block)

        if widget in self._block_widgets:
            self._block_widgets.remove(widget)
        self.blocks_container.removeWidget(widget)
        widget.deleteLater()

        self._update_remainder()

    def _update_remainder(self):
        total_qty = sum(b.quantity for b in self.group.blocks)
        required = abs(self.group.net_delta)
        remainder = required - total_qty

        if remainder == 0:
            self.remainder_label.setText(f"✓ Разбито полностью: {total_qty}/{required}")
            self.remainder_label.setStyleSheet("color: #10b981; background: transparent; font-weight: bold;")
        elif remainder > 0:
            self.remainder_label.setText(f"⚠ Осталось разбить: {remainder} из {required}")
            self.remainder_label.setStyleSheet("color: #f59e0b; background: transparent; font-weight: bold;")
        else:
            self.remainder_label.setText(f"✗ Превышение: {total_qty}/{required}")
            self.remainder_label.setStyleSheet("color: #ef4444; background: transparent; font-weight: bold;")

        self._on_changed()


class TroubleDialog(QDialog):
    """Диалог указания причин расхождений по ГРУППАМ."""

    def __init__(self, all_items: list, compensation_groups: list,
                 total_cost: float, parent=None):
        super().__init__(parent)
        self.all_items = all_items
        self.compensation_groups = compensation_groups
        self.total_cost = total_cost
        self._group_widgets: list = []
        self._result = {}

        self.setWindowTitle("Причины расхождений")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 800)

        # Формируем TroubleGroup из compensation_groups
        self._trouble_groups: list = []
        for g in compensation_groups:
            net_delta = g.get("net_delta", 0)
            if net_delta == 0:
                continue
            liability_items = g.get("liability_items", abs(net_delta))
            liability_value = g.get("liability_value", 0)
            unit_cost = liability_value / liability_items if liability_items > 0 else 0

            total_stock = sum(
                p.stock for p in g.get("minus_products", []) + g.get("plus_products", [])
            )
            total_actual = sum(
                (p.actual or 0) for p in g.get("minus_products", []) + g.get("plus_products", [])
            )

            self._trouble_groups.append(TroubleGroup(
                group_name=g["group_name"],
                net_delta=net_delta,
                unit_cost=unit_cost,
                total_stock=total_stock,
                total_actual=total_actual,
            ))

        self._build_ui()

    def _build_ui(self):
        p = SmartShellColors
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Указание причин расхождений")
        title.setFont(QFont("Inter", 20, QFont.Weight.Bold))
        layout.addWidget(title)

        info = QLabel(
            f"Групп с чистой недостачей: <b>{len(self._trouble_groups)}</b> &nbsp;|&nbsp; "
            f"💰 Общая сумма: <b>{self.total_cost:.2f} ₽</b>"
        )
        info.setFont(QFont("Inter", 13))
        info.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(info)

        hint = QLabel(
            "Показаны группы с учётом пересортицы (плюсы и минусы внутри бренда компенсируются).\n"
            "Разбейте чистую недостачу на блоки по причинам.\n"
            "Для причин кроме 'не знаю' требуется подтверждающая ссылка.\n"
            "Все случаи с ссылками будут проверены вручную."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {p.text_disable}; font-size: 12px;")
        layout.addWidget(hint)

        # СНАЧАЛА создаём summary (до заполнения групп!)
        summary_frame = QFrame()
        summary_frame.setStyleSheet(f"""
            QFrame {{
                background: {p.bg_item_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        summary_layout = QHBoxLayout(summary_frame)

        self.summary_not_sure = QLabel("💳 К оплате: 0 ₽")
        self.summary_not_sure.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        self.summary_not_sure.setStyleSheet("color: #ef4444; background: transparent;")
        summary_layout.addWidget(self.summary_not_sure)

        summary_layout.addStretch()

        self.summary_excused = QLabel("🔍 На проверке: 0 ₽")
        self.summary_excused.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        self.summary_excused.setStyleSheet("color: #f59e0b; background: transparent;")
        summary_layout.addWidget(self.summary_excused)

        summary_layout.addStretch()

        self.summary_total = QLabel(f"💰 Итого: {self.total_cost:.2f} ₽")
        self.summary_total.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        self.summary_total.setStyleSheet("color: #2C87FD; background: transparent;")
        summary_layout.addWidget(self.summary_total)

        # Скроллируемая область с группами
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        self.groups_layout = QVBoxLayout(scroll_content)
        self.groups_layout.setSpacing(12)
        self.groups_layout.setContentsMargins(4, 4, 4, 4)

        for group in self._trouble_groups:
            widget = TroubleGroupWidget(group, on_changed=self._update_summary)
            self._group_widgets.append(widget)
            self.groups_layout.addWidget(widget)

        self.groups_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        layout.addWidget(summary_frame)

        # Кнопки
        bottom = QHBoxLayout()

        self.confirm_btn = QPushButton("✓  Подтвердить и сохранить")
        self.confirm_btn.setFont(QFont("Inter", 14, QFont.Weight.Medium))
        self.confirm_btn.setMinimumHeight(48)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._on_confirm)
        bottom.addWidget(self.confirm_btn)

        bottom.addStretch()

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setProperty("variant", "secondary")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(self.cancel_btn)

        layout.addLayout(bottom)

        self._update_summary()

    def _update_summary(self):
        not_sure = 0.0
        excused = 0.0

        for widget in self._group_widgets:
            for block in widget.group.blocks:
                value = block.quantity * widget.group.unit_cost
                is_excusable = (
                    block.reason in ALL_EXCUSABLE_REASONS and
                    bool(block.reference.strip())
                )
                if is_excusable:
                    excused += value
                else:
                    not_sure += value

        if hasattr(self, 'summary_not_sure') and self.summary_not_sure is not None:
            self.summary_not_sure.setText(f"💳 К оплате: {not_sure:.2f} ₽")
            self.summary_excused.setText(f"🔍 На проверке: {excused:.2f} ₽")
            self.summary_total.setText(
                f"💰 Итого: {self.total_cost:.2f} ₽ "
                f"(оплата: {not_sure:.2f}, на проверке: {excused:.2f})"
            )

    def _on_confirm(self):
        # 1. Проверка разбиения
        for widget in self._group_widgets:
            total_qty = sum(b.quantity for b in widget.group.blocks)
            required = abs(widget.group.net_delta)
            if total_qty != required:
                QMessageBox.warning(
                    self, "Ошибка разбиения",
                    f"Группа '{widget.group.group_name}' разбита не полностью:\n"
                    f"Нужно: {required}, разбито: {total_qty}"
                )
                return

        # 2. Валидность блоков
        for widget in self._group_widgets:
            for bw in widget._block_widgets:
                valid, msg = bw.is_valid()
                if not valid:
                    QMessageBox.warning(
                        self, "Ошибка блока",
                        f"Группа '{widget.group.group_name}':\n{msg}"
                    )
                    return

        # 3. Формирование результата
        cost_trouble = 0.0
        cost_dis_trouble = 0.0
        trouble_operations = []
        all_ref = []

        for widget in self._group_widgets:
            g = widget.group
            op_type = "DISPOSAL" if g.status == "less" else "ADD"

            for block in g.blocks:
                value = block.quantity * g.unit_cost
                is_excusable = (
                    block.reason in ALL_EXCUSABLE_REASONS and
                    bool(block.reference.strip())
                )

                if is_excusable:
                    cost_dis_trouble += value
                    all_ref.append({
                        "group_name": g.group_name,
                        "quantity": block.quantity,
                        "cost": g.unit_cost,
                        "value": value,
                        "operation_type": op_type,
                        "reason": block.reason,
                        "reference": block.reference,
                    })
                else:
                    cost_trouble += value

                trouble_operations.append({
                    "product_id": 0,
                    "product_title": g.group_name,
                    "quantity": block.quantity,
                    "cost": g.unit_cost,
                    "operation_type": op_type,
                    "reason": block.reason,
                    "reference": block.reference,
                    "is_excusable": is_excusable,
                })

        cost_trouble = round(cost_trouble, 2)
        cost_dis_trouble = round(cost_dis_trouble, 2)

        # Собираем allitemDis из compensation_groups
        allitem_dis = []
        for g in self.compensation_groups:
            for p in g.get("minus_products", []) + g.get("plus_products", []):
                if p.actual is not None and p.actual != p.stock:
                    allitem_dis.append({
                        "product_id": p.id,
                        "title": p.title,
                        "group": g["group_name"],
                        "stock": p.stock,
                        "actual": p.actual,
                        "delta": p.actual - p.stock,
                        "cost": getattr(p, 'cost', 0) or 0,
                        "net_group_delta": g["net_delta"],
                        "liability_value": g["liability_value"],
                    })

        msg = (
            f"Итоговый расчёт:\n\n"
            f"💰 Общая сумма расхождений: {self.total_cost:.2f} ₽\n"
            f"💳 К оплате администратором: {cost_trouble:.2f} ₽\n"
            f"🔍 На ручной проверке: {cost_dis_trouble:.2f} ₽\n\n"
            f"Сохранить и продолжить?"
        )

        reply = QMessageBox.question(
            self, "Подтверждение итогов", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._result = {
            "cost": self.total_cost,
            "costTrouble": cost_trouble,
            "costDisTrouble": cost_dis_trouble,
            "trouble_operations": trouble_operations,
            "allRef": all_ref,
            "allitemTrouble": self.all_items,
            "allitemDis": allitem_dis,
        }
        self.accept()

    def get_result(self) -> dict:
        return self._result