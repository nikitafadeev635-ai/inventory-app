"""
Диалог верификации операций нормализации.

Показывает прогресс проверки и автоматически повторяет проблемные операции.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                             QProgressBar, QFrame)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from core.normalization_verifier import (NormalizationVerifier, VerificationResult,
                                         OperationResult)


class VerificationWorker(QThread):
    """Фоновый поток для верификации."""
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal(object)  # VerificationResult
    
    def __init__(self, verifier: NormalizationVerifier, operations, mode="auto"):
        super().__init__()
        self.verifier = verifier
        self.operations = operations
        self.mode = mode
    
    def run(self):
        try:
            if self.mode == "auto":
                result = self.verifier.auto_verify_with_retries(
                    self.operations, self._progress_callback
                )
            else:
                result = self.verifier.verify(self.operations, self._progress_callback)
            self.finished.emit(result)
        except Exception as e:
            print(f"[VerificationWorker] Ошибка: {e}")
            import traceback
            traceback.print_exc()
            # Возвращаем пустой результат с ошибкой
            from core.normalization_verifier import VerificationResult
            self.finished.emit(VerificationResult(operations=self.operations))
    
    def _progress_callback(self, current, total, message):
        self.progress.emit(current, total, message)


class VerificationDialog(QDialog):
    """Диалог отображения прогресса верификации."""
    
    def __init__(self, verifier: NormalizationVerifier, operations, parent=None):
        super().__init__(parent)
        self.verifier = verifier
        self.operations = operations
        self.result: VerificationResult = None
        self._worker: VerificationWorker = None
        
        self.setWindowTitle("Верификация нормализации")
        self.resize(800, 600)
        self.setModal(True)
        
        self._build_ui()
        self._start_verification()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Заголовок
        title = QLabel("🔍 Верификация операций нормализации")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        subtitle = QLabel(
            f"Проверяем что {len(self.operations)} операций "
            f"применились в SmartShell"
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #8b95a7; font-size: 13px;")
        layout.addWidget(subtitle)
        
        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 6px;
                text-align: center;
                background-color: #1f2937;
                color: #ffffff;
                min-height: 24px;
            }
            QProgressBar::chunk {
                background-color: #2C87FD;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Статус
        self.status_label = QLabel("⏳ Начинаем проверку...")
        self.status_label.setFont(QFont("Inter", 12))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #374151; max-height: 1px;")
        layout.addWidget(line)
        
        # Таблица с результатами
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Товар", "Операция", "Ожидалось", "Факт", "Статус"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Interactive
            )
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #131826;
                alternate-background-color: #1a2133;
                color: #e4e7eb;
                border: 1px solid #374151;
                border-radius: 6px;
                gridline-color: #374151;
            }
            QHeaderView::section {
                background-color: #1f2937;
                color: #9ca3af;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #374151;
            }
        """)
        layout.addWidget(self.table)
        
        # Итоговый статус
        self.summary_label = QLabel("")
        self.summary_label.setFont(QFont("Inter", 13, QFont.Weight.Medium))
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_label.setMinimumHeight(30)
        layout.addWidget(self.summary_label)
        
        # Кнопки
        buttons = QHBoxLayout()
        buttons.addStretch()
        
        self.retry_btn = QPushButton("🔁 Повторить проверку")
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.setEnabled(False)
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self._on_retry_clicked)
        self.retry_btn.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b; color: white;
                border: none; border-radius: 6px;
                padding: 10px 20px; font-weight: 500;
            }
            QPushButton:hover { background-color: #d97706; }
            QPushButton:disabled { background-color: #374151; color: #6b7280; }
        """)
        buttons.addWidget(self.retry_btn)
        
        self.continue_btn = QPushButton("✓ Продолжить")
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_btn.setEnabled(False)
        self.continue_btn.clicked.connect(self.accept)
        self.continue_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981; color: white;
                border: none; border-radius: 6px;
                padding: 10px 24px; font-weight: 600;
                min-width: 150px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #374151; color: #6b7280; }
        """)
        buttons.addWidget(self.continue_btn)
        
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #475569; color: white;
                border: none; border-radius: 6px;
                padding: 10px 20px;
            }
            QPushButton:hover { background-color: #64748b; }
        """)
        buttons.addWidget(self.cancel_btn)
        
        layout.addLayout(buttons)
    
    def _start_verification(self):
        """Запускает автоматическую верификацию."""
        self._worker = VerificationWorker(
            self.verifier, self.operations, mode="auto"
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()
    
    def _on_progress(self, current, total, message):
        if total > 0:
            percent = int(current / total * 100)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"{current}/{total} — {percent}%")
        self.status_label.setText(message)
    
    def _on_finished(self, result: VerificationResult):
        """Обновляет UI после завершения верификации."""
        self.result = result
        self._update_table()
        self._update_summary()
        self._update_buttons()
    
    def _update_table(self):
        """Перерисовывает таблицу с результатами."""
        if not self.result:
            return
        
        self.table.setRowCount(len(self.result.operations))
        
        for row, op in enumerate(self.result.operations):
            # Товар
            title_item = QTableWidgetItem(op.product_title)
            title_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, title_item)
            
            # Операция
            op_text = "Списание" if op.operation_type == "DISPOSAL" else "Внесение"
            op_item = QTableWidgetItem(f"{op_text} ({op.delta:+d})")
            op_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            op_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 1, op_item)
            
            # Ожидалось
            expected_item = QTableWidgetItem(str(op.expected_stock))
            expected_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            expected_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 2, expected_item)
            
            # Факт
            actual_text = str(op.actual_stock) if op.actual_stock is not None else "—"
            actual_item = QTableWidgetItem(actual_text)
            actual_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            actual_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 3, actual_item)
            
            # Статус
            if op.is_verified:
                status_text = "✓ Подтверждено"
                status_color = QColor("#10b981")
                bg_color = QColor("#10b98133")
            elif op.check_attempts > 0:
                status_text = f"✗ Раунд {op.check_attempts}"
                status_color = QColor("#ef4444")
                bg_color = QColor("#ef444433")
            else:
                status_text = "⏳ Ожидание"
                status_color = QColor("#f59e0b")
                bg_color = QColor("#f59e0b33")
            
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(status_color)
            status_item.setBackground(bg_color)
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 4, status_item)
            
            # Если есть ошибка — показываем в tooltip
            if op.last_error:
                for col in range(5):
                    item = self.table.item(row, col)
                    if item:
                        item.setToolTip(op.last_error)
    
    def _update_summary(self):
        if not self.result:
            return
        
        if self.result.all_ok:
            self.summary_label.setText(
                f"✅ Все {self.result.total} операций подтверждены в SmartShell"
            )
            self.summary_label.setStyleSheet("color: #10b981;")
        else:
            self.summary_label.setText(
                f"⚠ {self.result.failed_count} из {self.result.total} операций "
                f"не подтверждены"
            )
            self.summary_label.setStyleSheet("color: #f59e0b;")
    
    def _update_buttons(self):
        if not self.result:
            return
        
        # Кнопка повтора активна только если есть что повторять
        if self.result.failed_count > 0 and self.result.can_recheck:
            self.retry_btn.setVisible(True)
            self.retry_btn.setEnabled(True)
            self.retry_btn.setText(
                f"🔁 Повторить ({self.result.failed_count} проблемных)"
            )
        else:
            self.retry_btn.setVisible(False)
        
        self.continue_btn.setEnabled(True)
        
        if self.result.all_ok:
            self.continue_btn.setText("✓ Формировать отчёт")
        else:
            self.continue_btn.setText("⚠ Продолжить с предупреждением")
            self.continue_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f59e0b; color: white;
                    border: none; border-radius: 6px;
                    padding: 10px 24px; font-weight: 600;
                    min-width: 150px;
                }
                QPushButton:hover { background-color: #d97706; }
            """)
    
    def _on_retry_clicked(self):
        """Пользователь нажал 'Повторить проверку'."""
        self.retry_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        
        self._worker = VerificationWorker(
            self.verifier, self.result.operations, mode="retry"
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_retry_finished)
        self._worker.start()
    
    def _on_retry_finished(self, result: VerificationResult):
        """После ручной повторной проверки."""
        self.result = result
        self._update_table()
        self._update_summary()
        self._update_buttons()
    
    def get_result(self) -> VerificationResult:
        return self.result
    
    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(1000)
        super().closeEvent(event)