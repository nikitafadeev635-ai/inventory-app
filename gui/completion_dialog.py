"""
Финальный диалог успешного завершения пересменки.
Показывает чеклист всех выполненных этапов со статусами.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QWidget)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from gui.styles import SmartShellColors


class CompletionDialog(QDialog):
    """Диалог успешного завершения пересменки."""

    def __init__(self, stages: list, summary: dict, parent=None):
        super().__init__(parent)
        self.stages = stages
        self.summary = summary
        self.setWindowTitle("Пересменка закрыта")
        self.setMinimumSize(600, 500)
        self.resize(650, 550)
        self._build_ui()

    def _build_ui(self):
        p = SmartShellColors
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)

        title = QLabel("✓ Пересменка закрыта")
        title.setFont(QFont("Inter", 22, QFont.Weight.Bold))
        title.setStyleSheet("color: #10b981;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            f"{self.summary.get('shift_label', '—')} • "
            f"{self.summary.get('point_name', '—')} • "
            f"{self.summary.get('giver', '—')} → {self.summary.get('receiver', '—')}"
        )
        subtitle.setFont(QFont("Inter", 12))
        subtitle.setStyleSheet(f"color: {p.text_secondary};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        hr = QFrame()
        hr.setFrameShape(QFrame.Shape.HLine)
        hr.setStyleSheet(f"color: {p.border_gray_20};")
        layout.addWidget(hr)

        stages_label = QLabel("Выполненные этапы:")
        stages_label.setFont(QFont("Inter", 13, QFont.Weight.DemiBold))
        stages_label.setStyleSheet(f"color: {p.text_primary};")
        layout.addWidget(stages_label)

        for stage_name, success in self.stages:
            layout.addWidget(self._create_stage_row(stage_name, success))

        layout.addSpacing(8)

        if self.summary.get("has_discrepancies"):
            hr2 = QFrame()
            hr2.setFrameShape(QFrame.Shape.HLine)
            hr2.setStyleSheet(f"color: {p.border_gray_20};")
            layout.addWidget(hr2)

            summary_label = QLabel("Итоги смены:")
            summary_label.setFont(QFont("Inter", 13, QFont.Weight.DemiBold))
            summary_label.setStyleSheet(f"color: {p.text_primary};")
            layout.addWidget(summary_label)

            total_liability = self.summary.get("total_liability_value", 0.0)
            cost_trouble = self.summary.get("costTrouble", 0.0)
            cost_dis_trouble = self.summary.get("costDisTrouble", 0.0)

            summary_frame = QFrame()
            summary_frame.setStyleSheet(f"""
                QFrame {{
                    background: {p.bg_item_primary};
                    border: 1px solid {p.border_gray_20};
                    border-radius: 8px;
                    padding: 12px;
                }}
            """)
            s_layout = QVBoxLayout(summary_frame)
            s_layout.setSpacing(6)

            if total_liability > 0:
                r1 = QLabel(f"💰 Общая сумма расхождений: <b>{total_liability:.2f} ₽</b>")
                r1.setFont(QFont("Inter", 12))
                r1.setStyleSheet("color: #2C87FD; background: transparent;")
                s_layout.addWidget(r1)

            r2 = QLabel(f"💳 К оплате администратором: <b>{cost_trouble:.2f} ₽</b>")
            r2.setFont(QFont("Inter", 12, QFont.Weight.Bold))
            r2.setStyleSheet("color: #ef4444; background: transparent;")
            s_layout.addWidget(r2)

            if cost_dis_trouble > 0:
                r3 = QLabel(f"🔍 На ручной проверке: <b>{cost_dis_trouble:.2f} ₽</b>")
                r3.setFont(QFont("Inter", 12))
                r3.setStyleSheet("color: #f59e0b; background: transparent;")
                s_layout.addWidget(r3)

            total_ops = self.summary.get("total_operations", 0)
            if total_ops > 0:
                r4 = QLabel(f"📋 Нормализовано операций: <b>{total_ops}</b>")
                r4.setFont(QFont("Inter", 11))
                r4.setStyleSheet(f"color: {p.text_secondary}; background: transparent;")
                s_layout.addWidget(r4)

            emoji = self.summary.get("mood_emoji", "😊")
            mood = self.summary.get("mood_desc", "Всё идеально")
            r5 = QLabel(f"{emoji} <b>{mood}</b>")
            r5.setFont(QFont("Inter", 12))
            r5.setStyleSheet(f"color: {p.text_primary}; background: transparent;")
            s_layout.addWidget(r5)

            layout.addWidget(summary_frame)

        layout.addStretch()

        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton("✓  Закрыть")
        close_btn.setFont(QFont("Inter", 14, QFont.Weight.Medium))
        close_btn.setMinimumWidth(200)
        close_btn.setMinimumHeight(48)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981; color: white;
                border: none; border-radius: 8px;
                padding: 12px 32px; font-size: 14px; font-weight: 600;
            }
            QPushButton:hover { background-color: #059669; }
        """)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        bottom.addStretch()
        layout.addLayout(bottom)

    def _create_stage_row(self, name: str, success: bool) -> QWidget:
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)

        icon_text = "✓" if success else "✗"
        icon_color = "#10b981" if success else "#ef4444"

        icon_label = QLabel(icon_text)
        icon_label.setFont(QFont("Inter", 16, QFont.Weight.Bold))
        icon_label.setStyleSheet(f"color: {icon_color};")
        icon_label.setFixedWidth(24)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        name_label = QLabel(name)
        name_label.setFont(QFont("Inter", 12))
        name_label.setStyleSheet(f"color: {SmartShellColors.text_primary};")
        layout.addWidget(name_label, 1)

        status_text = "Выполнено" if success else "Пропущено"
        status_label = QLabel(status_text)
        status_label.setFont(QFont("Inter", 10))
        status_label.setStyleSheet(f"color: {icon_color}; font-weight: 500;")
        layout.addWidget(status_label)
        return widget