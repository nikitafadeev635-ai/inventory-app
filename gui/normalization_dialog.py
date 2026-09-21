"""
Диалог подтверждения плана нормализации.
Только формирует и показывает план для подтверждения.
Реальное применение происходит позже, в _close_inventory.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QProgressBar, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from core.normalization import NormalizationService
from gui.styles import SmartShellColors


class PlanWorker(QThread):
    """Фоновый поток для формирования плана нормализации."""
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, service: NormalizationService, items: list):
        super().__init__()
        self.service = service
        self.items = items

    def run(self):
        try:
            total = len(self.items)
            self.progress.emit(0, total)

            actuals_before = {}
            for item in self.items:
                actuals_before[item.product_id] = item.stock
            self.progress.emit(total // 4, total)

            plan = self.service.prepare_normalization_plan(self.items)

            self.progress.emit(total, total)
            self.finished.emit(plan)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class NormalizationDialog(QDialog):
    """Диалог подтверждения плана нормализации."""

    def __init__(self, service: NormalizationService, discrepancies: list, parent=None):
        super().__init__(parent)
        self.service = service
        self.discrepancies = discrepancies
        self._worker = None
        self._result = {}

        self.setWindowTitle("План нормализации товаров")
        self.setMinimumSize(900, 600)
        self.resize(960, 650)

        self._build_ui()

    def _build_ui(self):
        p = SmartShellColors
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("План нормализации после пересменки")
        title.setFont(QFont("Inter", 20, QFont.Weight.Bold))
        layout.addWidget(title)

        less_count = sum(1 for d in self.discrepancies if d.status == "less")
        more_count = sum(1 for d in self.discrepancies if d.status == "more")

        info = QLabel(
            f"Обнаружено расхождений: <b>{len(self.discrepancies)}</b> &nbsp;|&nbsp; "
            f"🔴 Недостача: <b>{less_count}</b> &nbsp;|&nbsp; "
            f"🔵 Избыток: <b>{more_count}</b>"
        )
        info.setFont(QFont("Inter", 13))
        info.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(info)

        hint = QLabel(
            "Подтвердите план. Причины расхождений и применение в SmartShell "
            "будут обработаны на следующих шагах."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {p.text_disable}; font-size: 12px;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Товар", "Учёт", "Факт", "Δ", "Тип"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 120)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self._fill_table()
        layout.addWidget(self.table)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {p.bg_item_primary};
                border: 1px solid {p.border_gray_20};
                border-radius: 6px;
                height: 24px;
                text-align: center;
                color: {p.text_primary};
            }}
            QProgressBar::chunk {{
                background: {p.accent_blue};
                border-radius: 5px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Inter", 12))
        layout.addWidget(self.status_label)

        bottom = QHBoxLayout()

        self.execute_btn = QPushButton("✓  Подтвердить план")
        self.execute_btn.setFont(QFont("Inter", 14, QFont.Weight.Medium))
        self.execute_btn.setMinimumHeight(48)
        self.execute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.execute_btn.clicked.connect(self._execute)
        bottom.addWidget(self.execute_btn)

        bottom.addStretch()

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setProperty("variant", "secondary")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(self.cancel_btn)

        layout.addLayout(bottom)

    def _fill_table(self):
        p = SmartShellColors
        self.table.setRowCount(len(self.discrepancies))

        for row, item in enumerate(self.discrepancies):
            title_item = QTableWidgetItem(item.title)
            title_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

            stock_item = QTableWidgetItem(str(item.stock))
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            actual_item = QTableWidgetItem(str(item.actual))
            actual_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            delta_item = QTableWidgetItem(str(item.delta))
            delta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            if item.status == "less":
                type_item = QTableWidgetItem("🔴 Списание")
                bg = QColor(p.accent_red)
                bg.setAlpha(40)
                fg = QColor("#FCA5A5")
            else:
                type_item = QTableWidgetItem("🔵 Внесение")
                bg = QColor(p.accent_blue)
                bg.setAlpha(40)
                fg = QColor("#93C5FD")

            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            for it in (title_item, stock_item, actual_item, delta_item, type_item):
                it.setBackground(bg)
                it.setForeground(fg)

            self.table.setItem(row, 0, title_item)
            self.table.setItem(row, 1, stock_item)
            self.table.setItem(row, 2, actual_item)
            self.table.setItem(row, 3, delta_item)
            self.table.setItem(row, 4, type_item)

    def _execute(self):
        """Подтверждает план."""
        less_count = sum(1 for d in self.discrepancies if d.status == "less")
        more_count = sum(1 for d in self.discrepancies if d.status == "more")

        reply = QMessageBox.question(
            self, "Подтверждение плана",
            f"Будет запланировано {len(self.discrepancies)} операций:\n"
            f"• Списаний: {less_count}\n"
            f"• Внесений: {more_count}\n\n"
            f"Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.execute_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.status_label.setText("Формирование плана...")

        self._worker = PlanWorker(self.service, self.discrepancies)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current, total):
        if total > 0:
            percent = int(current * 100 / total)
        else:
            percent = 100
        self.progress_bar.setValue(percent)
        self.status_label.setText("Формирование плана...")

    def _on_finished(self, plan):
        self.progress_bar.setValue(100)
        self.status_label.setText("")

        QMessageBox.information(
            self, "План сформирован",
            f"План нормализации сформирован:\n\n"
            f"Всего операций: {plan['total']}\n"
            f"• Списаний: {plan['disposals']}\n"
            f"• Внесений: {plan['additions']}\n\n"
            f"Следующий шаг — указание причин расхождений."
        )

        self._result = plan
        self.accept()

    def _on_error(self, message):
        self.execute_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Ошибка", f"Ошибка формирования плана:\n{message}")

    def get_result(self) -> dict:
        return self._result