"""
Диалог с QR-кодом для подключения телефона к синхронизации.
v6.5 — Немодальный диалог + группы + одиночные + точные факты по вкусам.
"""
import qrcode
from io import BytesIO
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QTableWidget, QTableWidgetItem,
                              QHeaderView, QMessageBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor
from core.sync_server import sync_server
from gui.styles import SmartShellColors


class SyncQRDialog(QDialog):
    """Немодальный диалог синхронизации с телефоном."""
    
    updates_received = pyqtSignal(dict)
    
    def __init__(self, groups_data: list, singles_data: list, parent=None):
        super().__init__(parent)
        
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(False)
        
        self.setWindowTitle("📱 Синхронизация с телефоном")
        self.resize(750, 780)
        
        self._groups_data = groups_data
        self._singles_data = singles_data
        self._build_ui()
        
        import uuid
        session_id = str(uuid.uuid4())[:8].upper()
        sync_server.start_session(session_id, groups_data, singles_data)
        
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._check_pending)
        self._poll_timer.start(2000)
    
    def _build_ui(self):
        p = SmartShellColors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        
        title = QLabel("📱 Синхронизация с телефоном")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        instruction = QLabel(
            "Это окно <b>не блокирует</b> главное приложение.<br>"
            "Точные значения по вкусам сохраняются при синхронизации."
        )
        instruction.setFont(QFont("Inter", 11))
        instruction.setStyleSheet(f"color: {p.text_secondary};")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._generate_qr()
        layout.addWidget(self.qr_label)
        
        url = sync_server.get_qr_url()
        self.url_label = QLabel(f"🔗 {url}")
        self.url_label.setFont(QFont("Consolas", 10))
        self.url_label.setStyleSheet(f"color: {p.accent_blue};")
        self.url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.url_label)
        
        self.status_label = QLabel("Ожидание обновлений с телефона...")
        self.status_label.setFont(QFont("Inter", 12))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(self.status_label)
        
        # Таблица pending обновлений
        self.pending_table = QTableWidget(0, 5)
        self.pending_table.setHorizontalHeaderLabels([
            "Тип", "Название", "Учёт", "Факт", "Δ"
        ])
        self.pending_table.setColumnWidth(0, 90)
        self.pending_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        for col in range(2, 5):
            self.pending_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self.pending_table.setVisible(False)
        self.pending_table.setMaximumHeight(280)
        self.pending_table.verticalHeader().setVisible(False)
        self.pending_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.pending_table)
        
        # 🆕 Детали по товарам внутри групп
        self.details_label = QLabel("")
        self.details_label.setFont(QFont("Consolas", 9))
        self.details_label.setStyleSheet(f"color: {p.text_secondary}; background: #1a1a2e; padding: 8px; border-radius: 4px;")
        self.details_label.setWordWrap(True)
        self.details_label.setVisible(False)
        self.details_label.setMaximumHeight(150)
        layout.addWidget(self.details_label)
        
        action_buttons = QHBoxLayout()
        
        self.accept_btn = QPushButton("✓ Принять")
        self.accept_btn.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        self.accept_btn.setMinimumHeight(44)
        self.accept_btn.setEnabled(False)
        self.accept_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981; color: white;
                border-radius: 8px; padding: 10px 20px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #374151; color: #6b7280; }
        """)
        self.accept_btn.clicked.connect(self._on_accept)
        action_buttons.addWidget(self.accept_btn)
        
        self.reject_btn = QPushButton("✕ Отклонить")
        self.reject_btn.setFont(QFont("Inter", 14))
        self.reject_btn.setMinimumHeight(44)
        self.reject_btn.setEnabled(False)
        self.reject_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444; color: white;
                border-radius: 8px; padding: 10px 20px;
            }
            QPushButton:hover { background-color: #dc2626; }
            QPushButton:disabled { background-color: #374151; color: #6b7280; }
        """)
        self.reject_btn.clicked.connect(self._on_reject)
        action_buttons.addWidget(self.reject_btn)
        
        layout.addLayout(action_buttons)
        
        bottom_buttons = QHBoxLayout()
        
        hide_btn = QPushButton("👁 Скрыть окно")
        hide_btn.setFont(QFont("Inter", 12))
        hide_btn.setMinimumHeight(40)
        hide_btn.setStyleSheet("""
            QPushButton {
                background-color: #475569; color: white;
                border-radius: 8px; padding: 10px 16px;
            }
            QPushButton:hover { background-color: #64748b; }
        """)
        hide_btn.clicked.connect(self._on_hide)
        bottom_buttons.addWidget(hide_btn)
        
        stop_btn = QPushButton("⏹ Остановить сессию")
        stop_btn.setFont(QFont("Inter", 12))
        stop_btn.setMinimumHeight(40)
        stop_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(239, 68, 68, 0.15);
                color: #ef4444;
                border: 1px solid #ef4444;
                border-radius: 8px; padding: 10px 16px;
            }
            QPushButton:hover { background-color: rgba(239, 68, 68, 0.25); }
        """)
        stop_btn.clicked.connect(self._on_stop_session)
        bottom_buttons.addWidget(stop_btn)
        
        layout.addLayout(bottom_buttons)
    
    def _generate_qr(self):
        url = sync_server.get_qr_url()
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="#161C23", back_color="#FFFFFF")
        
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        png_data = buffer.getvalue()
        
        qimage = QImage()
        qimage.loadFromData(png_data)
        
        if qimage.isNull():
            print("[QR] ⚠ Не удалось загрузить изображение")
            self.qr_label.setText(f"QR-код не сгенерирован\n{url}")
            return
        
        pixmap = QPixmap.fromImage(qimage)
        
        size = 220
        scaled = pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        self.qr_label.setFixedSize(size, size)
        self.qr_label.setScaledContents(False)
        self.qr_label.setPixmap(scaled)
        
        print(f"[QR] ✓ Сгенерирован: {url}")
    
    def _check_pending(self):
        """Проверяет наличие pending обновлений."""
        pending = sync_server.get_pending_updates()

        if pending:
            self.status_label.setText(f"📱 Получено {len(pending)} обновлений с телефона!")
            self.status_label.setStyleSheet("color: #f59e0b; font-weight: bold;")

            # Считаем общее количество строк (группы + их товары)
            total_rows = 0
            for update in pending:
                total_rows += 1  # строка группы
                if update["type"] == "group":
                    items = update.get("items", [])
                    for item in items:
                        if item.get("actual") is not None:
                            total_rows += 1  # строка товара с фактом

            self.pending_table.setVisible(True)
            self.pending_table.setRowCount(total_rows)
            self.pending_table.setColumnCount(5)
            self.pending_table.setHorizontalHeaderLabels([
                "Тип", "Название", "Учёт", "Факт", "Δ"
            ])
            self.pending_table.setColumnWidth(0, 80)
            self.pending_table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.Stretch
            )
            for col in range(2, 5):
                self.pending_table.horizontalHeader().setSectionResizeMode(
                    col, QHeaderView.ResizeMode.ResizeToContents
                )

            row = 0
            for update in pending:
                if update["type"] == "group":
                    # Строка группы
                    type_item = QTableWidgetItem("📚 Группа")
                    type_item.setForeground(QColor("#2C87FD"))
                    type_item.setFont(QFont("Inter", 10, QFont.Weight.Bold))
                    type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.pending_table.setItem(row, 0, type_item)

                    name_item = QTableWidgetItem(update["name"])
                    name_item.setFont(QFont("Inter", 11, QFont.Weight.Bold))
                    self.pending_table.setItem(row, 1, name_item)

                    stock_item = QTableWidgetItem(str(update["stock"]))
                    stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.pending_table.setItem(row, 2, stock_item)

                    actual_item = QTableWidgetItem(str(update["actual"]))
                    actual_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    actual_item.setFont(QFont("Inter", 11, QFont.Weight.Bold))
                    self.pending_table.setItem(row, 3, actual_item)

                    delta = update["delta"]
                    delta_item = QTableWidgetItem(f"{delta:+d}")
                    delta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    delta_item.setFont(QFont("Inter", 11, QFont.Weight.Bold))
                    if delta < 0:
                        delta_item.setForeground(QColor("#EF4444"))
                    elif delta > 0:
                        delta_item.setForeground(QColor("#3B82F6"))
                    else:
                        delta_item.setForeground(QColor("#10B981"))
                    self.pending_table.setItem(row, 4, delta_item)
                    row += 1

                    # 🆕 Строки товаров группы с точными фактами
                    items = update.get("items", [])
                    for item in items:
                        if item.get("actual") is not None:
                            t_item = QTableWidgetItem("  ↳ вкус")
                            t_item.setForeground(QColor("#94a3b8"))
                            t_item.setFont(QFont("Inter", 9))
                            self.pending_table.setItem(row, 0, t_item)

                            n_item = QTableWidgetItem(f"    {item['title'][:35]}")
                            n_item.setFont(QFont("Inter", 10))
                            n_item.setForeground(QColor("#d1d5db"))
                            self.pending_table.setItem(row, 1, n_item)

                            s_item = QTableWidgetItem(str(item["stock"]))
                            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                            s_item.setForeground(QColor("#94a3b8"))
                            self.pending_table.setItem(row, 2, s_item)

                            a_item = QTableWidgetItem(str(item["actual"]))
                            a_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                            a_item.setFont(QFont("Inter", 10, QFont.Weight.Bold))
                            a_item.setForeground(QColor("#f59e0b"))
                            self.pending_table.setItem(row, 3, a_item)

                            d = item["actual"] - item["stock"]
                            d_item = QTableWidgetItem(f"{d:+d}")
                            d_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                            if d < 0:
                                d_item.setForeground(QColor("#EF4444"))
                            elif d > 0:
                                d_item.setForeground(QColor("#3B82F6"))
                            else:
                                d_item.setForeground(QColor("#10B981"))
                            self.pending_table.setItem(row, 4, d_item)
                            row += 1

                else:
                    # Одиночный товар
                    type_item = QTableWidgetItem("📄 Товар")
                    type_item.setForeground(QColor("#94a3b8"))
                    type_item.setFont(QFont("Inter", 10))
                    type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.pending_table.setItem(row, 0, type_item)

                    name_item = QTableWidgetItem(update["name"])
                    name_item.setFont(QFont("Inter", 11, QFont.Weight.Bold))
                    self.pending_table.setItem(row, 1, name_item)

                    stock_item = QTableWidgetItem(str(update["stock"]))
                    stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.pending_table.setItem(row, 2, stock_item)

                    actual_item = QTableWidgetItem(str(update["actual"]))
                    actual_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    actual_item.setFont(QFont("Inter", 11, QFont.Weight.Bold))
                    self.pending_table.setItem(row, 3, actual_item)

                    delta = update["delta"]
                    delta_item = QTableWidgetItem(f"{delta:+d}")
                    delta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    delta_item.setFont(QFont("Inter", 11, QFont.Weight.Bold))
                    if delta < 0:
                        delta_item.setForeground(QColor("#EF4444"))
                    elif delta > 0:
                        delta_item.setForeground(QColor("#3B82F6"))
                    else:
                        delta_item.setForeground(QColor("#10B981"))
                    self.pending_table.setItem(row, 4, delta_item)
                    row += 1

            self.pending_table.setMaximumHeight(350)
            self.accept_btn.setEnabled(True)
            self.reject_btn.setEnabled(True)
        else:
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
    
    def _on_accept(self):
        """Подтверждает применение обновлений от телефона."""
        updates = sync_server.apply_pending(None)
        
        groups_count = len(updates.get("group_updates", {}))
        items_count = len(updates.get("item_updates", {}))
        singles_count = len(updates.get("single_updates", {}))
        
        if groups_count + singles_count > 0 or items_count > 0:
            self.updates_received.emit(updates)
            self.status_label.setText(
                f"✓ Применено: {groups_count} групп, "
                f"{items_count} точных фактов, {singles_count} одиночных"
            )
            self.status_label.setStyleSheet("color: #10b981; font-weight: bold;")
            self.pending_table.setVisible(False)
            if hasattr(self, 'details_label'):
                self.details_label.setVisible(False)
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
    
    def _on_reject(self):
        sync_server._group_updates.clear()
        sync_server._item_updates.clear()
        sync_server._single_updates.clear()
        self.status_label.setText("✕ Обновления отклонены")
        self.status_label.setStyleSheet("color: #ef4444;")
        self.pending_table.setVisible(False)
        self.details_label.setVisible(False)
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
    
    def _on_hide(self):
        self._poll_timer.stop()
        self.hide()
        print("[Sync] Диалог скрыт, сессия остаётся активной")
    
    def _on_stop_session(self):
        total_pending = (len(sync_server._group_updates) + 
                        len(sync_server._item_updates) + 
                        len(sync_server._single_updates))
        if total_pending > 0:
            reply = QMessageBox.question(
                self,
                "Остановить сессию?",
                f"Есть {total_pending} несохранённых обновлений.\n"
                "Они будут потеряны.\n\n"
                "Остановить сессию?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        sync_server.stop_session()
        self._poll_timer.stop()
        self.close()
        print("[Sync] Сессия остановлена")
    
    def showEvent(self, event):
        super().showEvent(event)
        if not self._poll_timer.isActive():
            self._poll_timer.start(2000)
    
    def closeEvent(self, event):
        self._poll_timer.stop()
        super().closeEvent(event)