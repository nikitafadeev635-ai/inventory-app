"""
Окно инвентаризации с группировкой товаров по брендам.
v3.2 — Прогресс-диалог + адаптация факта + иконки-стрелки + CompletionDialog
"""
from datetime import datetime
import re
import math
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QCheckBox, QLabel, QHeaderView,
                             QApplication, QColorDialog, QToolTip,
                             QDialog, QMessageBox, QTreeWidgetItem, QTreeWidget,
                             QStyledItemDelegate, QAbstractItemView,
                             QStyle, QProgressDialog)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QEvent, QRect
from PyQt6.QtGui import QColor, QIntValidator, QFont, QCursor
from items.product import Product
from core.session import current_session
from core.goods_cache import goods_cache
from core.product_group import ProductGroup
from config import BACKGROUND_GIF_PATH, BACKGROUND_OVERLAY_ALPHA
from gui.styles import SmartShellColors
from gui.gif_background import GifBackgroundWidget
from gui.themes import theme_manager

THEME_PATH_MAP = {
    "Верхняя панель › Фон › Фон панели":               ("top_bar_bg",     "Верхняя панель", "Фон",   "Фон верхней информационной панели"),
    "Верхняя панель › Текст › Подписи":                ("top_bar_label",  "Верхняя панель", "Текст", "Мелкие подписи"),
    "Верхняя панель › Текст › Значение смены":         ("top_bar_value",  "Верхняя панель", "Текст", "Строка с данными текущей смены"),
    "Верхняя панель › Текст › Цвет таймера":           ("timer_color",    "Верхняя панель", "Текст", "Цифры таймера пересчёта"),
    "Карточка хедера › Фон › Фон блока":               ("header_card_bg", "Карточка хедера", "Фон",   "Фон блока с отдающим/принимающим"),
    "Карточка хедера › Текст › Подписи":               ("header_label",   "Карточка хедера", "Текст", "Подписи"),
    "Карточка хедера › Текст › Значения":              ("header_value",   "Карточка хедера", "Текст", "Имена сотрудников и название точки"),
    "Строки таблицы › Избыток › Фон строки":           ("table_row_more_bg",       "Строки таблицы", "Избыток",    "Фон строки где факт > учёт"),
    "Строки таблицы › Избыток › Текст строки":         ("table_row_more_fg",       "Строки таблицы", "Избыток",    "Текст строки с избытком"),
    "Строки таблицы › Избыток › Бейдж":                ("status_badge_more_bg",    "Строки таблицы", "Избыток",    "Фон бейджа 'Избыток'"),
    "Строки таблицы › Избыток › Текст бейджа":         ("status_badge_more_fg",    "Строки таблицы", "Избыток",    "Текст бейджа 'Избыток'"),
    "Строки таблицы › Недостача › Фон строки":         ("table_row_less_bg",       "Строки таблицы", "Недостача",  "Фон строки где факт < учёт"),
    "Строки таблицы › Недостача › Текст строки":       ("table_row_less_fg",       "Строки таблицы", "Недостача",  "Текст строки с недостачей"),
    "Строки таблицы › Недостача › Бейдж":              ("status_badge_less_bg",    "Строки таблицы", "Недостача",  "Фон бейджа 'Недостача'"),
    "Строки таблицы › Недостача › Текст бейджа":       ("status_badge_less_fg",    "Строки таблицы", "Недостача",  "Текст бейджа 'Недостача'"),
    "Строки таблицы › Сходится › Фон строки":          ("table_row_equal_bg",      "Строки таблицы", "Сходится",   "Фон строки где факт = учёт"),
    "Строки таблицы › Сходится › Текст строки":        ("table_row_equal_fg",      "Строки таблицы", "Сходится",   "Текст строки где всё сходится"),
    "Строки таблицы › Сходится › Бейдж":               ("status_badge_equal_bg",   "Строки таблицы", "Сходится",   "Фон бейджа 'Сходится'"),
    "Строки таблицы › Сходится › Текст бейджа":        ("status_badge_equal_fg",   "Строки таблицы", "Сходится",   "Текст бейджа 'Сходится'"),
}

def _parse_color(color_str: str) -> QColor:
    if not color_str: return QColor("transparent")
    s = color_str.strip()
    rgba_match = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)', s)
    if rgba_match:
        r, g, b = int(rgba_match.group(1)), int(rgba_match.group(2)), int(rgba_match.group(3))
        a_str = rgba_match.group(4)
        if a_str is None: a = 255
        else:
            a_f = float(a_str)
            a = int(a_f * 255) if a_f <= 1.0 else int(a_f)
        return QColor(r, g, b, a)
    return QColor(s)

class IntDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() != 2: return None
        editor = QLineEdit(parent)
        editor.setValidator(QIntValidator(0, 99999))
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setPlaceholderText("число")
        return editor
    def setEditorData(self, editor, index): editor.setText(index.data() or "")
    def setModelData(self, editor, model, index): model.setData(index, editor.text())
    def updateEditorGeometry(self, editor, option, index): editor.setGeometry(option.rect)

class FetchWorker(QThread):
    finished = pyqtSignal(int, list)
    error = pyqtSignal(int, str)
    def __init__(self, client, request_id):
        super().__init__()
        self.client = client
        self.request_id = request_id
    def run(self):
        try:
            import time
            t0 = time.time()
            items = self.client.fetch_goods("")
            print(f"[UI] Загрузка #{self.request_id} — {len(items)} товаров за {time.time()-t0:.2f}с")
            self.finished.emit(self.request_id, items)
        except Exception as e:
            self.error.emit(self.request_id, str(e))

class InventoryWindow(QMainWindow):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle(f"Пересчёт — {current_session.point_name}")
        self.resize(1100, 760)
        self._inspector_enabled = False
        self._last_hovered_path = None
        self._updating = False
        self._sync_dialog = None
        self._normalization_in_progress = False
        self._closing_from_inside = False
        self._normalization_progress = {}

        p = SmartShellColors
        bg_path = p.background_path if p.background_path else BACKGROUND_GIF_PATH
        bg_alpha = getattr(p, 'background_overlay_alpha', BACKGROUND_OVERLAY_ALPHA)
        central = GifBackgroundWidget(bg_path, bg_alpha, parent=self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        central.setStyleSheet("QWidget { background: transparent; }")

        top_bar = QWidget()
        top_bar.setProperty("theme_path", "Верхняя панель › Фон › Фон панели")
        top_bar.setStyleSheet(f"QWidget {{ background-color: {p.top_bar_bg}; }}")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(24, 14, 24, 14)
        top_layout.setSpacing(16)
        left_side = QVBoxLayout(); left_side.setSpacing(4)
        shift_title = QLabel("СМЕНА")
        shift_title.setFont(QFont("Inter", 10, QFont.Weight.DemiBold))
        shift_title.setStyleSheet(f"color: {p.top_bar_label}; letter-spacing: 1.5px; background: transparent;")
        shift_title.setProperty("theme_path", "Верхняя панель › Текст › Подписи")
        left_side.addWidget(shift_title)
        self.shift_info_label = QLabel(current_session.shift_label or "—")
        self.shift_info_label.setFont(QFont("Inter", 14, QFont.Weight.Medium))
        self.shift_info_label.setStyleSheet(f"color: {p.top_bar_value}; background: transparent;")
        self.shift_info_label.setProperty("theme_path", "Верхняя панель › Текст › Значение смены")
        left_side.addWidget(self.shift_info_label)
        top_layout.addLayout(left_side, 5)

        center_side = QVBoxLayout(); center_side.setSpacing(4); center_side.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_title = QLabel("ВРЕМЯ ПЕРЕСЧЁТА")
        timer_title.setFont(QFont("Inter", 10, QFont.Weight.DemiBold))
        timer_title.setStyleSheet(f"color: {p.top_bar_label}; letter-spacing: 1.5px; background: transparent;")
        timer_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_title.setProperty("theme_path", "Верхняя панель › Текст › Подписи")
        center_side.addWidget(timer_title)
        self.timer_display = QLabel("00:00")
        self.timer_display.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.timer_display.setStyleSheet(f"color: {p.timer_color}; background: transparent;")
        self.timer_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_display.setProperty("theme_path", "Верхняя панель › Текст › Цвет таймера")
        center_side.addWidget(self.timer_display)
        top_layout.addLayout(center_side, 2)

        right_side = QVBoxLayout(); right_side.setSpacing(4); right_side.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mood_title = QLabel("НАСТРОЕНИЕ")
        mood_title.setFont(QFont("Inter", 10, QFont.Weight.DemiBold))
        mood_title.setStyleSheet(f"color: {p.top_bar_label}; letter-spacing: 1.5px; background: transparent;")
        mood_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mood_title.setProperty("theme_path", "Верхняя панель › Текст › Подписи")
        right_side.addWidget(mood_title)
        self.mood_emoji = QLabel("😊")
        self.mood_emoji.setFont(QFont("Segoe UI Emoji", 36))
        self.mood_emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mood_emoji.setToolTip("0-1 недостач"); self.mood_emoji.setStyleSheet("background: transparent;")
        right_side.addWidget(self.mood_emoji)
        top_layout.addLayout(right_side, 1)
        layout.addWidget(top_bar)

        header_card = QWidget()
        header_card.setProperty("theme_path", "Карточка хедера › Фон › Фон блока")
        header_card.setStyleSheet(f"QWidget {{ background-color: {p.header_card_bg}; }}")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(24, 14, 24, 14)
        header_layout.setSpacing(32)
        self.header_giver = self._make_header_item("ОТДАЮЩИЙ", current_session.giver)
        self.header_receiver = self._make_header_item("ПРИНИМАЮЩИЙ", current_session.receiver)
        self.header_point = self._make_header_item("ТОЧКА", current_session.point_name)
        header_layout.addWidget(self.header_giver)
        header_layout.addWidget(self.header_receiver)
        header_layout.addWidget(self.header_point)
        layout.addWidget(header_card)

        top = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Поиск по бренду или названию товара...")
        self.search_input.setFont(QFont("Inter", 13))
        top.addWidget(self.search_input, 3)
        self.refresh_btn = QPushButton("🔄  Обновить учёт")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._refresh_stock)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        filters = QHBoxLayout()
        filters_label = QLabel("ФИЛЬТРЫ")
        filters_label.setFont(QFont("Inter", 11, QFont.Weight.DemiBold))
        filters_label.setStyleSheet(f"color: {p.text_secondary}; letter-spacing: 1px;")
        filters.addWidget(filters_label)
        self.filter_more = QCheckBox("Избыток"); self.filter_less = QCheckBox("Недостача")
        self.filter_equal = QCheckBox("Сходится"); self.filter_none = QCheckBox("Не считано")
        for cb in (self.filter_more, self.filter_less, self.filter_equal, self.filter_none):
            cb.stateChanged.connect(self._apply_filters); filters.addWidget(cb)
        self.reset_filters_btn = QPushButton("Сбросить")
        self.reset_filters_btn.setProperty("variant", "secondary")
        self.reset_filters_btn.setFixedWidth(100)
        self.reset_filters_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_filters_btn.clicked.connect(self._reset_filters)
        filters.addWidget(self.reset_filters_btn)
        filters.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {p.text_secondary};")
        self.status_label.setFont(QFont("Inter", 12))
        filters.addWidget(self.status_label)

        self.inspector_btn = QPushButton("🔍  Визуализатор")
        self.inspector_btn.setCheckable(True)
        self.inspector_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.inspector_btn.clicked.connect(self._toggle_inspector_mode)
        filters.addWidget(self.inspector_btn)
        self.customize_btn = QPushButton("⚙️  Настроить")
        self.customize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.customize_btn.clicked.connect(self._open_customizer)
        filters.addWidget(self.customize_btn)

        self.sync_btn = QPushButton("📱  Телефон")
        self.sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_btn.setStyleSheet("""
            QPushButton { background-color: rgba(16, 185, 129, 0.15); color: #10b981;
                         border: 1px solid #10b981; border-radius: 8px;
                         padding: 10px 20px; font-size: 14px; font-weight: 500; }
            QPushButton:hover { background-color: rgba(16, 185, 129, 0.25); }
        """)
        self.sync_btn.clicked.connect(self._open_sync_dialog)
        filters.addWidget(self.sync_btn)

        self.close_btn = QPushButton("✕  Закрыть пересчёт")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton { background-color: #475569; color: #ffffff; border: none;
                         border-radius: 8px; padding: 10px 20px; font-size: 14px;
                         font-weight: 500; min-height: 20px; }
            QPushButton:hover { background-color: #64748b; }
            QPushButton:pressed { background-color: #334155; }
        """)
        self.close_btn.clicked.connect(self._close_inventory)
        filters.addWidget(self.close_btn)
        layout.addLayout(filters)

        self.table = QTreeWidget()
        self.table.setColumnCount(5)
        self.table.setHeaderLabels(["Название", "Учёт", "Факт", "Δ", "Статус"])
        self.table.header().setStretchLastSection(False)
        self.table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5): self.table.header().setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 80); self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 60); self.table.setColumnWidth(4, 110)
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setIndentation(20)
        self.table.header().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed |
            QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.table.setItemDelegateForColumn(2, IntDelegate(self.table))
        self.table.setStyleSheet(f"""
            QTreeWidget {{ background-color: {p.header_card_bg};
                          alternate-background-color: {p.bg_item_secondary};
                          border: none; font-size: 13px; }}
            QTreeWidget::item {{ padding: 4px; background-color: transparent; }}
            QTreeWidget::item:hover {{ background-color: rgba(255, 255, 255, 0.05); }}
            QHeaderView::section {{ background-color: {p.bg_primary};
                                   color: {p.text_secondary}; border: none;
                                   border-bottom: 1px solid {p.border_gray_20};
                                   padding: 6px; }}
        """)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemExpanded.connect(self._on_item_expanded)
        self.table.itemCollapsed.connect(self._on_item_collapsed)
        self.table.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.table)

        self._visible_groups = []
        self._request_id = 0
        self._active_request_id = 0
        self._active_worker = None
        self._timer = QTimer()
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_timer)
        self._timer.start()
        self._update_timer()
        goods_cache.subscribe(self._on_cache_updated)
        self.search_input.textChanged.connect(self._filter_local)
        self.installEventFilter(self)
        self._enable_mouse_tracking_recursive(central)
        self._initial_load()

    # ============================================================
    #  ЗАГРУЗКА ДАННЫХ
    # ============================================================
    def _initial_load(self):
        if goods_cache.is_loaded() and goods_cache.is_fresh():
            self._filter_local(self.search_input.text())
            self._status(f"Из кеша: {goods_cache.count_in_stock()} в наличии из {goods_cache.count()}")
            return
        self._status("⏳ Загрузка товаров...")
        self._start_fetch()

    def _start_fetch(self):
        self._request_id += 1
        self._active_request_id = self._request_id
        if self._active_worker and self._active_worker.isRunning():
            try: self._active_worker.finished.disconnect(); self._active_worker.error.disconnect()
            except (TypeError, RuntimeError): pass
        self._active_worker = FetchWorker(self.client, self._request_id)
        self._active_worker.finished.connect(self._on_fetched)
        self._active_worker.error.connect(self._on_error)
        self._active_worker.start()

    def _on_fetched(self, request_id, items):
        """
        Обрабатывает полученные товары из SmartShell.
        🆕 Адаптирует actuals_cache при изменении stock (продажа/внесение).
        """
        if request_id != self._active_request_id:
            return
        
        all_products = [Product.from_api(i) for i in items]
        
        # 🆕 АДАПТАЦИЯ: запоминаем старые stock ДО обновления
        old_stocks = {}
        if goods_cache.is_loaded():
            for p in goods_cache.get_all_products():
                old_stocks[p.id] = p.stock
        
        # Применяем actuals_cache к новым товарам
        for p in all_products:
            if p.id in current_session.actuals_cache:
                p.actual = current_session.actuals_cache[p.id]
        
        from config import SMARTSHELL_WAREHOUSE_IDS
        warehouse_id = SMARTSHELL_WAREHOUSE_IDS.get(current_session.point_name)
        goods_cache.load(all_products, warehouse_id)
        
        # 🆕 АДАПТАЦИЯ actuals_cache при изменении stock (продажа/внесение)
        adapted_count = 0
        for p in all_products:
            if p.id in old_stocks and p.id in current_session.actuals_cache:
                old_stock = old_stocks[p.id]
                new_stock = p.stock
                if old_stock != new_stock:
                    stock_delta = new_stock - old_stock
                    current_session.actuals_cache[p.id] += stock_delta
                    p.actual = current_session.actuals_cache[p.id]
                    adapted_count += 1
        
        if adapted_count > 0:
            print(f"[Sync] 🔄 Адаптировано фактов на ПК: {adapted_count}")
        
        from core.sync_server import sync_server
        if sync_server._session_id is not None:
            self._update_sync_server_data()
            
    def _collect_sync_data(self) -> tuple:
        groups_data = []
        singles_data = []
        for group in goods_cache.get_groups():
            visible = [p for p in group.products if p.stock > 0]
            if not visible: continue
            if len(visible) >= 2:
                total_stock = sum(p.stock for p in visible)
                products = [{"id": p.id, "title": p.title, "stock": p.stock} for p in visible]
                groups_data.append({"name": group.name, "total_stock": total_stock, "products": products})
            else:
                p = visible[0]
                singles_data.append({"id": p.id, "title": p.title, "stock": p.stock})
        return groups_data, singles_data

    def _update_sync_server_data(self):
        from core.sync_server import sync_server
        groups_data, singles_data = self._collect_sync_data()
        sync_server.update_data(groups_data, singles_data)
        print(f"[Sync] ✓ Обновлены данные: {len(groups_data)} групп, {len(singles_data)} одиночных")

    def _on_cache_updated(self):
        self._filter_local(self.search_input.text())
        self._status(f"✅ Загружено: {goods_cache.count_in_stock()} в наличии из {goods_cache.count()}")

    def _on_error(self, request_id, message):
        if request_id != self._active_request_id: return
        self._status(f"❌ Ошибка загрузки: {message}")
        self.refresh_btn.setEnabled(True)

    # ============================================================
    #  ФИЛЬТРАЦИЯ И ОТОБРАЖЕНИЕ
    # ============================================================
    def _filter_local(self, query: str = ""):
        self._visible_groups = goods_cache.filter_local(query or "")
        self._apply_filters()

    def _get_active_filters(self):
        active = set()
        if self.filter_more.isChecked(): active.add("more")
        if self.filter_less.isChecked(): active.add("less")
        if self.filter_equal.isChecked(): active.add("equal")
        if self.filter_none.isChecked(): active.add("unknown")
        return active

    def _apply_filters(self):
        if self._updating: return
        self._updating = True
        try:
            self.table.blockSignals(True); self.table.clear()
            self.table.setHeaderLabels(["Название", "Учёт", "Факт", "Δ", "Статус"])
            active_filters = self._get_active_filters()
            total_groups = total_singles = total_products = counted_products = 0
            total_stock = total_actual = 0
            multi_groups = []; single_groups = []
            for group in self._visible_groups:
                visible_products = [p for p in group.products if p.status in active_filters] if active_filters else group.products
                if not visible_products: continue
                if len(visible_products) >= 2: multi_groups.append((group, visible_products))
                else: single_groups.append((group, visible_products))
            
            # === ГРУППЫ (2+ товара) ===
            for group, visible_products in multi_groups:
                total_groups += 1; total_products += len(visible_products)
                counted_products += sum(1 for p in visible_products if p.actual is not None)
                total_stock += sum(p.stock for p in visible_products)
                group_item = self._create_group_item(group, visible_products)
                self.table.addTopLevelItem(group_item)
                for product in visible_products:
                    child = self._create_product_item(product)
                    group_item.addChild(child)
                if group.expanded: group_item.setExpanded(True)
                if group.total_actual is not None: total_actual += group.total_actual
            
            # === 🆕 ОДИНОЧНЫЕ ТОВАРЫ (с правильным выравниванием) ===
            if single_groups:
                # Separator с правильным выравниванием
                separator = QTreeWidgetItem(["─── Отдельные товары ───", "", "", "", ""])
                separator.setData(0, Qt.ItemDataRole.UserRole, {"type": "separator"})
                for col in range(5):
                    separator.setBackground(col, QColor(40, 45, 60))
                    separator.setForeground(col, QColor(150, 150, 150))
                    font = separator.font(col); font.setItalic(True); separator.setFont(col, font)
                    # 🆕 Явное выравнивание для separator
                    if col == 0:
                        separator.setTextAlignment(col, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    else:
                        separator.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
                separator.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.addTopLevelItem(separator)
                
                # Одиночные товары
                for group, visible_products in single_groups:
                    total_singles += 1; total_products += 1
                    product = visible_products[0]
                    if product.actual is not None:
                        counted_products += 1; total_actual += product.actual
                    total_stock += product.stock
                    
                    # 🆕 Создаём элемент с правильным выравниванием
                    item = self._create_product_item(product)
                    
                    # 🆕 Убираем отступ для одиночных товаров (они top-level, но без иконки)
                    # Используем setFirstColumnSpanned(False) чтобы избежать визуального смещения
                    item.setFirstColumnSpanned(False)
                    
                    self.table.addTopLevelItem(item)
            
            delta_total = total_actual - total_stock if total_actual else None
            delta_str = f"Δ: {delta_total:+d}" if delta_total is not None else ""
            parts = []
            if total_groups > 0: parts.append(f"{total_groups} групп")
            if total_singles > 0: parts.append(f"{total_singles} одиночных")
            groups_info = " + ".join(parts) if parts else "пусто"
            if active_filters:
                names = {"more": "Избыток", "less": "Недостача", "equal": "Сходится", "unknown": "Не считано"}
                filters_text = " + ".join(names[s] for s in active_filters)
                self._status(f"Фильтр: {filters_text} → {total_products} товаров ({groups_info}) | Считано: {counted_products} {delta_str}")
            else:
                self._status(f"Показано: {total_products} товаров ({groups_info}) | Считано: {counted_products} {delta_str}")
            self._update_mood()
        finally:
            self.table.blockSignals(False); self._updating = False

    def _create_group_item(self, group: ProductGroup, visible_products: list) -> QTreeWidgetItem:
        temp_group = ProductGroup(name=group.name)
        temp_group.products = visible_products
        
        # 🆕 Чистое название БЕЗ стрелки в тексте
        item = QTreeWidgetItem([
            group.name,  # ← просто имя, без "▼" или "▶"
            str(temp_group.total_stock),
            str(temp_group.total_actual) if temp_group.total_actual is not None else "",
            str(temp_group.delta) if temp_group.delta is not None else "",
            self._status_text(temp_group.status),
        ])
        
        # 🆕 Иконка-стрелка через setIcon (не смещает колонки)
        if group.expanded:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        else:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        item.setIcon(0, icon)
        
        item.setData(0, Qt.ItemDataRole.UserRole, {"type": "group", "group_name": group.name})
        
        # 🆕 Явное выравнивание: колонка 0 — по левому краю, 1-4 — по центру
        item.setTextAlignment(0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col in range(1, 5):
            item.setTextAlignment(col, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        status_color, fg_color = self._get_status_colors(temp_group.status)
        if status_color:
            for col in range(5):
                item.setBackground(col, status_color)
                item.setForeground(col, fg_color)
        
        font = item.font(0)
        font.setBold(True)
        font.setPointSize(13)
        for col in range(5):
            item.setFont(col, font)
        
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled |
            Qt.ItemFlag.ItemIsSelectable |
            Qt.ItemFlag.ItemIsEditable
        )
        return item

    def _create_product_item(self, product: Product) -> QTreeWidgetItem:
        item = QTreeWidgetItem([
            product.title, str(product.stock),
            str(product.actual) if product.actual is not None else "",
            str(product.actual - product.stock) if product.actual is not None else "",
            self._status_text(product.status),
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, {"type": "product", "product_id": product.id})
        
        # 🆕 Устанавливаем выравнивание
        item.setTextAlignment(0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col in range(1, 5): item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
        
        status_color, fg_color = self._get_status_colors(product.status)
        if status_color:
            for col in range(5): item.setBackground(col, status_color); item.setForeground(col, fg_color)
        
        # 🆕 Для одиночных товаров (top-level) добавляем пустую иконку для выравнивания
        parent = item.parent()
        if parent is None:  # Это top-level элемент (одиночный товар)
            # Создаём прозрачную иконку 16x16 для выравнивания с группами
            from PyQt6.QtGui import QPixmap, QIcon
            transparent_pixmap = QPixmap(16, 16)
            transparent_pixmap.fill(Qt.GlobalColor.transparent)
            item.setIcon(0, QIcon(transparent_pixmap))
        
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
        return item
    
    def _status_text(self, status: str) -> str:
        return {"more": "Избыток", "less": "Недостача", "equal": "Сходится", "unknown": "—"}[status]

    def _get_status_colors(self, status: str):
        p = SmartShellColors
        if status == "more": return _parse_color(p.table_row_more_bg), _parse_color(p.table_row_more_fg)
        elif status == "less": return _parse_color(p.table_row_less_bg), _parse_color(p.table_row_less_fg)
        elif status == "equal": return _parse_color(p.table_row_equal_bg), _parse_color(p.table_row_equal_fg)
        return None, None

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        if column != 0: return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "group": return
        item.setExpanded(not item.isExpanded())

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 2 or self._updating: return
        self._updating = True
        try:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data: return
            text = item.text(2).strip()
            if data["type"] == "product":
                product = goods_cache.get_by_id(data["product_id"])
                if not product: return
                if not text: product.actual = None
                else:
                    try: product.actual = int(float(text))
                    except ValueError:
                        previous = str(product.actual) if product.actual is not None else ""
                        self.table.blockSignals(True); item.setText(2, previous); self.table.blockSignals(False); return
                self._save_to_cache(product); self._update_product_item_display(item, product); self._update_parent_group(item)
            elif data["type"] == "group":
                group_name = data["group_name"]
                group = self._find_group_by_name(group_name)
                if not group: return
                if not text:
                    for p in group.products:
                        p.actual = None
                        if p.id in current_session.actuals_cache: del current_session.actuals_cache[p.id]
                else:
                    try:
                        group_actual = int(float(text))
                        group.distribute_actual(group_actual)
                        for p in group.products: self._save_to_cache(p)
                    except ValueError:
                        previous = str(group.total_actual) if group.total_actual is not None else ""
                        self.table.blockSignals(True); item.setText(2, previous); self.table.blockSignals(False); return
                self._refresh_group_children(item, group); self._update_group_item_display(item, group)
            self._update_status_stats(); self._update_mood()
        finally: self._updating = False

    def _update_product_item_display(self, item: QTreeWidgetItem, product: Product):
        item.setText(3, str(product.actual - product.stock) if product.actual is not None else "")
        item.setText(4, self._status_text(product.status))
        status_color, fg_color = self._get_status_colors(product.status)
        if status_color:
            for col in range(5): item.setBackground(col, status_color); item.setForeground(col, fg_color)

    def _update_group_item_display(self, item: QTreeWidgetItem, group: ProductGroup):
        item.setText(1, str(group.total_stock))
        item.setText(2, str(group.total_actual) if group.total_actual is not None else "")
        item.setText(3, str(group.delta) if group.delta is not None else "")
        item.setText(4, self._status_text(group.status))
        status_color, fg_color = self._get_status_colors(group.status)
        if status_color:
            for col in range(5): item.setBackground(col, status_color); item.setForeground(col, fg_color)

    def _update_parent_group(self, item: QTreeWidgetItem):
        parent = item.parent()
        if not parent: return
        data = parent.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "group": return
        group = self._find_group_by_name(data["group_name"])
        if group: self._update_group_item_display(parent, group)

    def _refresh_group_children(self, group_item: QTreeWidgetItem, group: ProductGroup):
        self.table.blockSignals(True)
        try:
            for i in range(group_item.childCount()):
                child = group_item.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data["type"] == "product":
                    product = goods_cache.get_by_id(data["product_id"])
                    if product:
                        child.setText(2, str(product.actual) if product.actual is not None else "")
                        self._update_product_item_display(child, product)
        finally: self.table.blockSignals(False)

    def _update_status_stats(self):
        all_in_cache = goods_cache.get_all_products() if goods_cache.is_loaded() else []
        counted = sum(1 for p in all_in_cache if p.actual is not None)
        total = len(all_in_cache)
        active_filters = self._get_active_filters()
        if active_filters:
            names = {"more": "Избыток", "less": "Недостача", "equal": "Сходится", "unknown": "Не считано"}
            filters_text = " + ".join(names[s] for s in active_filters)
            self._status(f"Фильтр: {filters_text} | Считано: {counted} / {total}")
        else: self._status(f"Считано: {counted} / {total}")

    def _find_group_by_name(self, name: str):
        for g in goods_cache.get_groups():
            if g.name == name: return g
        return None

    def _on_item_expanded(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "group":
            group = self._find_group_by_name(data["group_name"])
            if group:
                group.expanded = True
            # 🆕 Меняем иконку, а не текст
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))

    def _on_item_collapsed(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "group":
            group = self._find_group_by_name(data["group_name"])
            if group:
                group.expanded = False
            # 🆕 Меняем иконку, а не текст
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))

    def _toggle_inspector_mode(self):
        self._inspector_enabled = self.inspector_btn.isChecked()
        self._last_hovered_path = None
        if self._inspector_enabled:
            self.inspector_btn.setText("🔍  Визуализатор [ВКЛ]")
            self.inspector_btn.setStyleSheet("""
                QPushButton { background-color: rgba(44, 135, 253, 0.3) !important;
                             color: #ffffff !important; border: 1px solid #2C87FD !important;
                             border-radius: 8px; padding: 10px 20px; }
            """)
            QToolTip.showText(QCursor.pos(),
                "<b>Режим визуализатора включён</b><br>Наведите на элемент и кликните для смены цвета.",
                self, QRect(), 3000)
        else:
            self.inspector_btn.setText("🔍  Визуализатор")
            self.inspector_btn.setStyleSheet(""); QToolTip.hideText()

    def _enable_mouse_tracking_recursive(self, widget):
        widget.setMouseTracking(True)
        for child in widget.findChildren(QWidget): child.setMouseTracking(True)

    def eventFilter(self, obj, event):
        if not self._inspector_enabled: return super().eventFilter(obj, event)
        if event.type() == QEvent.Type.MouseMove:
            widget = QApplication.widgetAt(QCursor.pos())
            theme_path = self._find_theme_path(widget)
            if theme_path and theme_path in THEME_PATH_MAP:
                if theme_path != self._last_hovered_path:
                    self._last_hovered_path = theme_path
                    field_name, category, subcategory, description = THEME_PATH_MAP[theme_path]
                    current_value = getattr(SmartShellColors, field_name, "?")
                    tooltip_html = (
                        f"<div style='max-width: 320px;'>"
                        f"<div style='font-size: 13px; font-weight: bold; color: #2C87FD;'>{theme_path}</div>"
                        f"<div style='font-size: 11px; color: rgba(255,255,255,0.7);'><b>{category}</b> › <b>{subcategory}</b></div>"
                        f"<div style='font-size: 11px; color: rgba(255,255,255,0.6);'>{description}</div>"
                        f"<div style='font-size: 10px; font-family: Consolas;'>{field_name} = {current_value}</div>"
                        f"<div style='font-size: 11px; color: #2C87FD;'>🖱 Клик — изменить</div>"
                        f"</div>"
                    )
                    QToolTip.showText(QCursor.pos(), tooltip_html)
            else:
                if self._last_hovered_path is not None:
                    self._last_hovered_path = None; QToolTip.hideText()
            return False
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            widget = QApplication.widgetAt(QCursor.pos())
            theme_path = self._find_theme_path(widget)
            if theme_path and theme_path in THEME_PATH_MAP:
                self._pick_color_for_field(THEME_PATH_MAP[theme_path][0], theme_path); return True
            return False
        return super().eventFilter(obj, event)

    def _find_theme_path(self, widget):
        while widget is not None:
            try:
                path = widget.property("theme_path")
                if path: return path
                widget = widget.parent()
            except RuntimeError: return None
        return None

    def _pick_color_for_field(self, field_name: str, theme_path: str):
        current_value = getattr(SmartShellColors, field_name, "#000000")
        initial_color = _parse_color(current_value)
        color = QColorDialog.getColor(initial_color, self, f"Цвет: {theme_path}",
                                       QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not color.isValid(): return
        new_color = color.name() if color.alpha() == 255 else f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
        current = theme_manager.current_theme
        setattr(current.palette, field_name, new_color)
        app = QApplication.instance()
        theme_manager.apply_theme(current, app)
        self.refresh_theme_colors()
        QToolTip.showText(QCursor.pos(), f"<b>✓ Применено</b><br>{field_name} = {new_color}", self, QRect(), 1500)

    def _make_header_item(self, label: str, value: str) -> QWidget:
        p = SmartShellColors
        widget = QWidget(); widget.setStyleSheet("background: transparent;")
        v = QVBoxLayout(widget); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        lbl = QLabel(label); lbl.setFont(QFont("Inter", 10, QFont.Weight.DemiBold))
        lbl.setStyleSheet(f"color: {p.header_label}; letter-spacing: 1.5px;")
        lbl.setProperty("theme_path", "Карточка хедера › Текст › Подписи"); v.addWidget(lbl)
        val = QLabel(value or "—"); val.setFont(QFont("Inter", 15, QFont.Weight.Medium))
        val.setStyleSheet(f"color: {p.header_value};")
        val.setProperty("theme_path", "Карточка хедера › Текст › Значения"); v.addWidget(val)
        return widget

    def _open_customizer(self):
        from gui.inventory_customizer import InventoryCustomizerDialog
        InventoryCustomizerDialog(self, parent=self).exec()

    def refresh_theme_colors(self):
        p = SmartShellColors
        bg_path = p.background_path if p.background_path else BACKGROUND_GIF_PATH
        bg_alpha = getattr(p, 'background_overlay_alpha', BACKGROUND_OVERLAY_ALPHA)
        central = self.centralWidget()
        if hasattr(central, '_movie') or hasattr(central, '_current_pixmap'):
            if getattr(central, '_current_path', None) != bg_path or \
               getattr(central, '_current_alpha', None) != bg_alpha:
                new_bg = GifBackgroundWidget(bg_path, bg_alpha, parent=self)
                old_layout = central.layout()
                self.setCentralWidget(new_bg)
                if old_layout: new_bg.setLayout(old_layout)
                new_bg.setStyleSheet("QWidget { background: transparent; }"); central = new_bg
        top_bar = self._find_widget_by_layout_index(central.layout(), 0)
        if top_bar: top_bar.setStyleSheet(f"QWidget {{ background-color: {p.top_bar_bg}; }}")
        header_card = self._find_widget_by_layout_index(central.layout(), 1)
        if header_card: header_card.setStyleSheet(f"QWidget {{ background-color: {p.header_card_bg}; }}")
        self.table.setStyleSheet(f"""
            QTreeWidget {{ background-color: {p.header_card_bg};
                          alternate-background-color: {p.bg_item_secondary};
                          border: none; font-size: 13px; }}
            QHeaderView::section {{ background-color: {p.bg_primary};
                                   color: {p.text_secondary}; border: none;
                                   border-bottom: 1px solid {p.border_gray_20};
                                   padding: 6px; }}
        """)
        self._refresh_inline_styles(); self._apply_filters()

    def _refresh_inline_styles(self):
        p = SmartShellColors
        if hasattr(self, 'timer_display'):
            self.timer_display.setStyleSheet(f"color: {p.timer_color}; background: transparent;")
        if hasattr(self, 'shift_info_label'):
            self.shift_info_label.setStyleSheet(f"color: {p.top_bar_value}; background: transparent;")
        for widget in self.findChildren(QLabel):
            try: path = widget.property("theme_path")
            except RuntimeError: continue
            if path == "Верхняя панель › Текст › Подписи":
                widget.setStyleSheet(f"color: {p.top_bar_label}; letter-spacing: 1.5px; background: transparent;")
            elif path == "Карточка хедера › Текст › Подписи":
                widget.setStyleSheet(f"color: {p.header_label}; letter-spacing: 1.5px;")
            elif path == "Карточка хедера › Текст › Значения":
                widget.setStyleSheet(f"color: {p.header_value};")

    def _find_widget_by_layout_index(self, layout, index: int):
        if layout is None: return None
        item = layout.itemAt(index)
        return item.widget() if item else None

    def _update_timer(self): self.timer_display.setText(current_session.elapsed_str)

    def _get_mood_emoji(self, less_count: int) -> tuple:
        if less_count <= 1: return "😊", f"{less_count} недостач" if less_count == 1 else "Всё идеально"
        elif less_count <= 3: return "🤔", f"{less_count} недостачи — задумался"
        elif less_count <= 7: return "🤦", f"{less_count} недостач — чешет голову"
        elif less_count <= 10: return "💸", f"{less_count} недостач — машет деньгами"
        else: return "💀", f"{less_count} недостач — полный провал"

    def _update_mood(self):
        all_products = goods_cache.get_all_products() if goods_cache.is_loaded() else []
        less_count = sum(1 for p in all_products if p.status == "less")
        emoji, tooltip = self._get_mood_emoji(less_count)
        self.mood_emoji.setText(emoji); self.mood_emoji.setToolTip(tooltip)

    def _save_to_cache(self, product):
        if product.actual is not None: current_session.actuals_cache[product.id] = product.actual
        elif product.id in current_session.actuals_cache: del current_session.actuals_cache[product.id]

    def _status(self, text): self.status_label.setText(text)

    def _reset_filters(self):
        self.table.blockSignals(True)
        try:
            self.filter_more.setChecked(False); self.filter_less.setChecked(False)
            self.filter_equal.setChecked(False); self.filter_none.setChecked(False)
        finally: self.table.blockSignals(False)
        self._apply_filters()

    def _refresh_stock(self):
        self._status("🔄 Обновление данных из SmartShell...")
        self.refresh_btn.setEnabled(False); goods_cache.invalidate(); self._start_fetch()
        def on_done(req_id, items): self.refresh_btn.setEnabled(True)
        def on_err(req_id, msg): self.refresh_btn.setEnabled(True)
        if self._active_worker:
            try: self._active_worker.finished.connect(on_done); self._active_worker.error.connect(on_err)
            except (TypeError, RuntimeError): pass

    def _open_sync_dialog(self):
        from gui.sync_qr_dialog import SyncQRDialog
        from core.sync_server import sync_server
        if self._sync_dialog is not None:
            if self._sync_dialog.isVisible():
                self._sync_dialog.hide(); self._status("📱 Диалог синхронизации скрыт (сессия активна)")
            else:
                self._sync_dialog.show(); self._sync_dialog.raise_()
                self._sync_dialog.activateWindow(); self._status("📱 Диалог синхронизации показан")
            return
        sync_server.start()
        groups_data, singles_data = self._collect_sync_data()
        if not groups_data and not singles_data:
            QMessageBox.warning(self, "Нет товаров",
                "Нет товаров для синхронизации.\nСначала загрузите товары (кнопка 🔄 Обновить учёт)"); return
        self._sync_dialog = SyncQRDialog(groups_data, singles_data, parent=None)
        self._sync_dialog.updates_received.connect(self._apply_sync_updates)
        self._sync_dialog.finished.connect(self._on_sync_dialog_finished)
        self._sync_dialog.show(); self._sync_dialog.raise_(); self._sync_dialog.activateWindow()
        self._status(f"📱 Синхронизация: {len(groups_data)} групп, {len(singles_data)} одиночных")

    def _on_sync_dialog_finished(self):
        if self._sync_dialog is not None:
            self._sync_dialog.deleteLater(); self._sync_dialog = None
            self._status("📱 Диалог синхронизации закрыт")

    def _apply_sync_updates(self, updates: dict):
        group_updates = updates.get("group_updates", {})
        item_updates = updates.get("item_updates", {})
        single_updates = updates.get("single_updates", {})
        applied_manual = applied_singles = applied_algo = 0
        int_item_updates = {}
        for pid_raw, actual in item_updates.items():
            try: int_item_updates[int(pid_raw)] = int(actual)
            except (ValueError, TypeError): pass
        groups_with_manual = set()
        for pid in int_item_updates:
            for g in goods_cache.get_groups():
                if any(p.id == pid for p in g.products): groups_with_manual.add(g.name); break
        for group_name in groups_with_manual:
            group = self._find_group_by_name(group_name)
            if not group: continue
            group_manuals = {p.id: int_item_updates[p.id] for p in group.products if p.id in int_item_updates}
            if group_manuals:
                if hasattr(group, 'apply_exact_actuals'):
                    count = group.apply_exact_actuals(group_manuals)
                else:
                    count = 0
                    for p in group.products:
                        if p.id in group_manuals: p.actual = int(group_manuals[p.id]); count += 1
                applied_manual += count
                for p in group.products:
                    if p.actual is not None: self._save_to_cache(p)
        for group_name, total_actual in group_updates.items():
            if group_name in groups_with_manual: continue
            group = self._find_group_by_name(group_name)
            if not group: continue
            try:
                group.distribute_actual(int(total_actual))
                for p in group.products:
                    if p.actual is not None: self._save_to_cache(p)
                applied_algo += 1
            except Exception as e: print(f"[Sync] Ошибка группы {group_name}: {e}")
        for pid_raw, actual in single_updates.items():
            try: pid = int(pid_raw)
            except (ValueError, TypeError): continue
            product = goods_cache.get_by_id(pid)
            if not product: continue
            try:
                product.actual = int(actual); self._save_to_cache(product); applied_singles += 1
            except Exception as e: print(f"[Sync] Ошибка товара {pid}: {e}")
        self._apply_filters()
        self._status(f"📱 Применено: {applied_manual} точных + {applied_singles} одиночных + {applied_algo} групп (алгоритм)")

    # ============================================================
    #  🔒 БЕЗОПАСНОЕ ЗАКРЫТИЕ ПЕРЕСЧЁТА
    # ============================================================
    def _close_inventory(self):
        self._sync_actuals_from_table()
        
        # ============================================================
        #  💰 РАСЧЁТ ФИНАНСОВОЙ ОТВЕТСТВЕННОСТИ (ГРУППЫ + ОДИНОЧНЫЕ)
        # ============================================================
        financial_summary = {
            "groups": [],
            "total_liability_value": 0.0,
            "total_liability_items": 0,
            "total_all_disposals_value": 0.0,
            "compensation_groups": [],
            "all_groups_with_delta": [],
            "net_total_disposal_value": 0.0,
            "net_total_disposal_items": 0,
            "single_items_with_delta": [],  # 🆕 одиночные товары
        }
        
        if goods_cache.is_loaded():
            for group in goods_cache.get_groups():
                visible_products = [p for p in group.products if p.stock > 0]
                if not visible_products:
                    continue
                
                # === ГРУППЫ с 2+ товарами ===
                if len(visible_products) >= 2:
                    liability = group.get_financial_liability()
                    has_any_delta = any(
                        p.actual is not None and p.actual != p.stock
                        for p in visible_products
                    )
                    if has_any_delta:
                        financial_summary["all_groups_with_delta"].append(liability)
                        financial_summary["net_total_disposal_value"] += liability["liability_value"]
                        financial_summary["net_total_disposal_items"] += liability["liability_items"]
                    if liability["liability_value"] > 0:
                        financial_summary["groups"].append(liability)
                        financial_summary["compensation_groups"].append(liability)
                        financial_summary["total_liability_value"] += liability["liability_value"]
                        financial_summary["total_liability_items"] += liability["liability_items"]
                        financial_summary["total_all_disposals_value"] += liability["all_disposals_value"]
                
                # === 🆕 ОДИНОЧНЫЕ товары (группа = 1 товар) ===
                else:
                    p = visible_products[0]
                    if p.actual is not None and p.actual != p.stock:
                        delta = p.actual - p.stock
                        cost = getattr(p, 'cost', 0) or 0
                        
                        single_liability = {
                            "group_name": group.name,
                            "net_delta": delta,
                            "liability_value": abs(delta) * cost if delta < 0 else 0,
                            "liability_items": abs(delta) if delta < 0 else 0,
                            "all_disposals_value": abs(delta) * cost if delta < 0 else 0,
                            "compensation_applied": False,
                            "minus_products": [p] if delta < 0 else [],
                            "plus_products": [p] if delta > 0 else [],
                            "is_single": True,  # 🆕 маркер одиночного товара
                        }
                        
                        financial_summary["single_items_with_delta"].append(single_liability)
                        financial_summary["all_groups_with_delta"].append(single_liability)
                        
                        if delta < 0:  # только недостача → в compensation_groups
                            financial_summary["net_total_disposal_value"] += single_liability["liability_value"]
                            financial_summary["net_total_disposal_items"] += single_liability["liability_items"]
                            financial_summary["compensation_groups"].append(single_liability)
                            financial_summary["total_liability_value"] += single_liability["liability_value"]
                            financial_summary["total_liability_items"] += single_liability["liability_items"]
                            financial_summary["total_all_disposals_value"] += single_liability["all_disposals_value"]
        
        # Логирование
        if financial_summary["compensation_groups"]:
            singles_count = sum(1 for g in financial_summary["compensation_groups"] if g.get("is_single"))
            groups_count = len(financial_summary["compensation_groups"]) - singles_count
            print(f"\n[Inventory] 💰 Позиции к списанию: {len(financial_summary['compensation_groups'])}")
            print(f"    Групп с пересортицей: {groups_count}")
            print(f"    Одиночных товаров: {singles_count}")
            for g in financial_summary["compensation_groups"]:
                single_marker = " [одиночный]" if g.get("is_single") else ""
                comp_marker = " (пересорт)" if g.get("compensation_applied") else " (чистый минус)"
                print(f"  • {g['group_name']}{single_marker}{comp_marker}: "
                    f"чистая Δ={g['net_delta']:+d}, "
                    f"списать {g['liability_items']} шт на {g['liability_value']:.2f}₽")
            print(f"  ИТОГО: списать {financial_summary['total_liability_items']} шт "
                f"на {financial_summary['total_liability_value']:.2f}₽")
        
        if financial_summary["all_groups_with_delta"]:
            print(f"[Inventory] 📊 Всего позиций с расхождениями: {len(financial_summary['all_groups_with_delta'])}")

        from core.normalization import NormalizationService
        from gui.normalization_dialog import NormalizationDialog
        from gui.trouble_dialog import TroubleDialog
        from core.report_generator import generate_normalization_report
        from core.inventory_repository import InventoryRepository

        all_products = goods_cache.get_all_products() if goods_cache.is_loaded() else []
        service = NormalizationService(self.client)
        discrepancies = service.get_discrepancies(all_products)
        plan = None; trouble_result = None

        if discrepancies:
            # ШАГ 1: План нормализации
            dialog = NormalizationDialog(service, discrepancies, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                plan = dialog.get_result()
            else:
                reply = QMessageBox.question(self, "Отмена нормализации",
                    "Нормализация отменена. Расхождения НЕ будут обработаны.\nЗакрыть пересчёт без обработки?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes: return
                current_session.is_open = False
                goods_cache.unsubscribe(self._on_cache_updated)
                if hasattr(self, '_timer'): self._timer.stop()
                self.close(); return

            # ШАГ 2: TroubleDialog
            if financial_summary.get("compensation_groups"):
                all_items_for_trouble = []
                for p in all_products:
                    if p.actual is not None and p.actual != p.stock:
                        all_items_for_trouble.append({
                            "product_id": p.id, "title": p.title, "stock": p.stock,
                            "actual": p.actual, "delta": p.actual - p.stock,
                            "cost": getattr(p, 'cost', 0) or 0,
                        })
                print(f"\n[Inventory] Причины расхождений: {len(financial_summary['compensation_groups'])} позиций")
                trouble_dialog = TroubleDialog(
                    all_items=all_items_for_trouble,
                    compensation_groups=financial_summary["compensation_groups"],
                    total_cost=financial_summary.get("total_liability_value", 0.0),
                    parent=self,
                )
                if trouble_dialog.exec() == QDialog.DialogCode.Accepted:
                    trouble_result = trouble_dialog.get_result()
                    print(f"[Inventory] ✓ Причины указаны: к оплате={trouble_result['costTrouble']:.2f}, "
                        f"на проверке={trouble_result['costDisTrouble']:.2f}")
                else: print("[Inventory] ⚠ Указание причин пропущено")

            # ШАГ 3: БЛОКИРОВКА + ПРОГРЕСС-ДИАЛОГ
            self._close_locked = True
            self.close_btn.setEnabled(False); self.close_btn.setText("⏳ Финальная обработка...")
            QApplication.processEvents()

            progress_dialog = QProgressDialog("Обработка смены...", None, 0, 100, self)
            progress_dialog.setWindowTitle("Обработка смены")
            progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress_dialog.setCancelButton(None); progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0); progress_dialog.setLabelText("🔒 Подготовка...")
            progress_dialog.show(); QApplication.processEvents()

            print("\n" + "="*60 + "\n  🔒 ЗАКРЫТИЕ ПРОГРАММЫ ЗАБЛОКИРОВАНО\n" + "="*60)

            try:
                # ШАГ 4: ЗАПИСЬ В БД
                end_time = datetime.now()
                progress_dialog.setLabelText("💾 Сохранение операций в БД...")
                progress_dialog.setValue(10); QApplication.processEvents()
                try:
                    repo = InventoryRepository(self.client)
                    operations_to_save = []
                    for op_data in plan.get("operations", []):
                        pid = op_data.get("product_id")
                        if pid is None: continue
                        product = goods_cache.get_by_id(pid)
                        product_cost = getattr(product, 'cost', 0) or 0.0 if product else 0.0
                        operations_to_save.append({
                            "product_id": pid, "product_title": op_data.get("product_title", ""),
                            "quantity": op_data.get("quantity", abs(op_data.get("delta", 0))),
                            "cost": product_cost, "operation_type": op_data.get("type", ""), "reason": "",
                        })
                    if operations_to_save:
                        r = repo.save_operations(operations=operations_to_save,
                            point_name=current_session.point_name, administrator=current_session.giver,
                            session_label=current_session.shift_label or "", operation_date=end_time)
                        if r["success"]: print(f"[DB] ✓ {r['inserted']} операций в inventory_operation")

                    progress_dialog.setLabelText("💾 Сохранение итога смены...")
                    progress_dialog.setValue(25); QApplication.processEvents()

                    all_item = [{"product_id": p.id, "title": p.title, "stock": p.stock,
                                "actual": p.actual, "delta": p.actual - p.stock,
                                "cost": getattr(p, 'cost', 0) or 0}
                                for p in all_products if p.actual is not None and p.actual != p.stock]
                    all_item_dis = []
                    for g in financial_summary.get("compensation_groups", []):
                        group = next((gg for gg in goods_cache.get_groups() if gg.name == g["group_name"]), None)
                        if not group: continue
                        for p in group.products:
                            if p.stock > 0:
                                delta = (p.actual or 0) - p.stock
                                all_item_dis.append({
                                    "product_id": p.id, "title": p.title, "group": group.name,
                                    "stock": p.stock, "actual": p.actual or 0, "delta": delta,
                                    "net_group_delta": g["net_delta"], "liability_value": g["liability_value"],
                                    "cost": getattr(p, 'cost', 0) or 0,
                                })
                    total_liability = financial_summary.get("total_liability_value", 0.0)
                    if total_liability > 0 or all_item:
                        r = repo.save_session_dispol(point_name=current_session.point_name,
                            administrator=current_session.giver, cost=total_liability,
                            all_item=all_item, all_item_dis=all_item_dis,
                            session_label=current_session.shift_label or "", reason="Пересчёт смены")
                        if r["success"]: print(f"[DB] ✓ session_dispol (id={r['id']})")

                    progress_dialog.setLabelText("💾 Сохранение причин расхождений...")
                    progress_dialog.setValue(40); QApplication.processEvents()

                    if trouble_result and trouble_result.get("trouble_operations"):
                        r = repo.save_trouble_operations(operations=trouble_result["trouble_operations"],
                            point_name=current_session.point_name, administrator=current_session.giver,
                            session_label=current_session.shift_label or "", operation_date=end_time)
                        if r["success"]: print(f"[DB] ✓ {r['inserted']} trouble-операций")
                        r = repo.save_correct_trouble(point_name=current_session.point_name,
                            administrator=current_session.giver, cost=trouble_result["cost"],
                            allitemTrouble=trouble_result["allitemTrouble"],
                            allitemDis=trouble_result["allitemDis"],
                            costTrouble=trouble_result["costTrouble"],
                            costDisTrouble=trouble_result["costDisTrouble"],
                            allRef=trouble_result["allRef"],
                            session_label=current_session.shift_label or "")
                        if r["success"]: print(f"[DB] ✓ correctTrouble (id={r['id']})")
                except Exception as e:
                    print(f"[DB] ✗ Ошибка при записи в БД: {e}")
                    import traceback; traceback.print_exc()

                # ШАГ 5: PDF ОТЧЁТ
                progress_dialog.setLabelText("📄 Формирование PDF отчёта...")
                progress_dialog.setValue(55); QApplication.processEvents()
                try:
                    pdf_path = generate_normalization_report(discrepancies, plan,
                        verification_result=None, financial_summary=financial_summary,
                        trouble_result=trouble_result)
                    print(f"[Report] ✓ PDF отчёт сохранён: {pdf_path}")
                except Exception as e:
                    print(f"[Report] ✗ Ошибка генерации PDF: {e}")
                    import traceback; traceback.print_exc()

                try: service.sync_products_to_db(all_products)
                except Exception as e: print(f"[DB] ✗ Ошибка синхронизации товаров: {e}")

                # ШАГ 6: ПРИМЕНЕНИЕ В SMARTSHELL
                progress_dialog.hide(); QApplication.processEvents()
                if plan and plan.get("operations"):
                    self.close_btn.setText("🚀 Применение в SmartShell..."); QApplication.processEvents()
                    session_info = {
                        "start_time": current_session.start_time.isoformat() if current_session.start_time else None,
                        "shift_type": current_session.shift_type,
                        "duration": current_session.elapsed_str,
                        "shift_label": current_session.shift_label,
                    }
                    ss_result = service.apply_normalization_plan(plan, session_info)
                    ss_failed = ss_result.get("failed", 0); ss_success = ss_result.get("success", 0)
                    if ss_failed > 0 and ss_success == 0:
                        errors_text = "\n".join(ss_result.get("errors", [])[:5])
                        QMessageBox.critical(self, "Ошибка SmartShell",
                            f"⚠️ Не удалось применить изменения в SmartShell!\n\n"
                            f"Успешно: {ss_success}\nОшибок: {ss_failed}\n\nОшибки:\n{errors_text}\n\n"
                            f"Данные уже сохранены в БД и отчёт сформирован.")
                    elif ss_failed > 0:
                        QMessageBox.warning(self, "Частичная ошибка SmartShell",
                            f"⚠️ Не все операции применены в SmartShell:\n\n"
                            f"Успешно: {ss_success}\nОшибок: {ss_failed}\n\n"
                            f"Данные уже сохранены в БД.")

                    # ШАГ 7: АВТОМАТИЧЕСКАЯ ПОСТ-ВЕРИФИКАЦИЯ
                    self.close_btn.setText("🔍 Проверка применения..."); QApplication.processEvents()
                    verify_result = service.verify_application(plan)
                    if not verify_result.get("all_ok", True) and verify_result.get("failed", 0) > 0:
                        failed_items = verify_result.get("failed_items", [])
                        items_text = "\n".join(
                            f"  • {it['product_title']}: ожидалось {it['expected']}, "
                            f"в системе {it['actual_stock']}" for it in failed_items[:10])
                        QMessageBox.warning(self, "Расхождение после применения",
                            f"⚠️ Фактическое состояние в SmartShell отличается от ожидаемого:\n\n"
                            f"Успешно применено: {verify_result.get('verified', 0)}\n"
                            f"Расхождений: {verify_result.get('failed', 0)}\n\n"
                            f"Детали:\n{items_text}\n\n"
                            f"Данные уже сохранены в БД и отчёт сформирован.")
            except Exception as e:
                print(f"[Inventory] ✗ Критическая ошибка: {e}")
                import traceback; traceback.print_exc()
                QMessageBox.critical(self, "Критическая ошибка",
                    f"⚠ Ошибка во время финальной обработки:\n\n{e}\n\n"
                    f"Данные уже сохранены в БД.")
            finally:
                # ШАГ 8: РАЗБЛОКИРОВКА
                try:
                    if 'progress_dialog' in locals() and progress_dialog is not None:
                        progress_dialog.close()
                except Exception: pass
                self._close_locked = False
                self.close_btn.setEnabled(True); self.close_btn.setText("✕  Закрыть пересчёт")
                QApplication.processEvents()
                print("\n" + "="*60 + "\n  🔓 ЗАКРЫТИЕ ПРОГРАММЫ РАЗБЛОКИРОВАНО\n" + "="*60)
        else:
            print("[Inventory] ✓ Все товары сошлись. Нормализация не требуется.")

        current_session.is_open = False
        
        # 📋 ИТОГИ В КОНСОЛЬ
        total = len(all_products)
        counted = sum(1 for p in all_products if p.actual is not None)
        more = sum(1 for p in all_products if p.status == "more")
        less = sum(1 for p in all_products if p.status == "less")
        equal = sum(1 for p in all_products if p.status == "equal")
        unknown = sum(1 for p in all_products if p.status == "unknown")
        end_time = datetime.now()
        duration = current_session.elapsed_str
        emoji, mood_desc = self._get_mood_emoji(less)
        print(f"\n{'='*60}\n  📋 ИТОГИ ПЕРЕСМЕНКИ\n{'='*60}")
        print(f"  Смена: {current_session.shift_label} | Тип: {current_session.shift_type}")
        print(f"  Длительность: {duration} | Отдающий: {current_session.giver} | Принимающий: {current_session.receiver}")
        print(f"{'─'*60}")
        print(f"  Всего: {total} | Посчитано: {counted} | Сходится: {equal}")
        print(f"  Недостача: {less} {emoji} | Избыток: {more}")
        print(f"  Настроение: {emoji} {mood_desc}")
        print(f"{'─'*60}")
        if plan: print(f"  📋 Запланировано: {plan.get('total', 0)} операций")
        if trouble_result:
            print(f"  💰 ИТОГИ РАСХОЖДЕНИЙ:")
            print(f"     💳 К оплате:   {trouble_result['costTrouble']:.2f}₽")
            print(f"     🔍 На проверке: {trouble_result['costDisTrouble']:.2f}₽")
        print(f"{'='*60}\n")

        goods_cache.unsubscribe(self._on_cache_updated)
        if hasattr(self, '_timer'): self._timer.stop()

        # 🆕 ШАГ 9: ФИНАЛЬНЫЙ ДИАЛОГ УСПЕШНОГО ЗАВЕРШЕНИЯ
        try:
            from gui.completion_dialog import CompletionDialog
            stages = [
                ("План нормализации", plan is not None),
                ("Запись операций в БД", True),
                ("Указание причин расхождений",
                trouble_result is not None or not financial_summary["compensation_groups"]),
                ("Сохранение итогов в БД", True),
                ("PDF-отчёт", True),
                ("Применение в SmartShell", True),
            ]
            summary = {
                "shift_label": current_session.shift_label or "—",
                "point_name": current_session.point_name or "—",
                "giver": current_session.giver or "—",
                "receiver": current_session.receiver or "—",
                "has_discrepancies": bool(discrepancies),
                "total_liability_value": financial_summary.get("total_liability_value", 0.0),
                "costTrouble": trouble_result.get("costTrouble", 0.0) if trouble_result else 0.0,
                "costDisTrouble": trouble_result.get("costDisTrouble", 0.0) if trouble_result else 0.0,
                "total_operations": len(plan.get("operations", [])) if plan else 0,
                "mood_emoji": emoji,
                "mood_desc": mood_desc,
            }
            dialog = CompletionDialog(stages, summary, parent=self)
            dialog.exec()
        except Exception as e:
            print(f"[Completion] ⚠ Не удалось показать финальный диалог: {e}")
            import traceback; traceback.print_exc()

        self.close()

    def _sync_actuals_from_table(self):
        def sync_item(item):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "product":
                product = goods_cache.get_by_id(data["product_id"])
                if product:
                    text = item.text(2).strip()
                    try:
                        product.actual = int(float(text)) if text else None
                        self._save_to_cache(product)
                    except ValueError: pass
        for i in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(i); sync_item(item)
            for j in range(item.childCount()): sync_item(item.child(j))

    def closeEvent(self, event):
        """
        Перехват закрытия окна.
        Блокирует закрытие во время финальной обработки (БД + SmartShell).
        """
        # 🔒 Защита от закрытия во время финальной обработки
        if self._close_locked:
            QMessageBox.warning(
                self, "Нельзя закрыть",
                "⚠️ Идёт запись данных в БД и применение в SmartShell!\n\n"
                "Закрытие программы сейчас приведёт к потере данных.\n"
                "Дождитесь завершения всех операций (обычно 10-30 секунд)."
            )
            event.ignore()
            return
        
        # Закрываем диалог синхронизации если он открыт
        # 🆕 Защита от NoneType: сохраняем ссылку ДО операций
        if self._sync_dialog is not None:
            from core.sync_server import sync_server
            dialog = self._sync_dialog  # Сохраняем ссылку
            self._sync_dialog = None   # Сбрасываем ДО stop_session
            try:
                sync_server.stop_session()
            except Exception as e:
                print(f"[Sync] Ошибка stop_session: {e}")
            try:
                dialog.close()
                dialog.deleteLater()
            except Exception as e:
                print(f"[Sync] Ошибка закрытия диалога: {e}")
        
        # Подтверждение если смена ещё открыта
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
        
        goods_cache.unsubscribe(self._on_cache_updated)
        if hasattr(self, '_timer'):
            self._timer.stop()
        if self._active_worker and self._active_worker.isRunning():
            self._active_worker.quit()
            self._active_worker.wait(1000)
        super().closeEvent(event)