"""
Inline-редактор оформления рабочей области инвентаризации.
Открывается прямо из окна пересчёта, изменения применяются мгновенно.
"""
import os
from pathlib import Path

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTabWidget, QWidget, QFrame,
                             QColorDialog, QFileDialog, QSpinBox, QMessageBox,
                             QInputDialog, QScrollArea, QGridLayout, QGroupBox,
                             QApplication)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from gui.themes import theme_manager, Theme, ColorPalette


class ColorPickerButton(QPushButton):
    """Кнопка-пикер цвета с превью."""

    def __init__(self, label: str, initial_color: str, on_change, parent=None):
        super().__init__(parent)
        self._label = label
        self._current_color = initial_color
        self._on_change = on_change

        self.setFixedHeight(36)
        self.setMinimumWidth(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_appearance()
        self.clicked.connect(self._pick_color)

    def _update_appearance(self):
        self.setText(f"  {self._label}")
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._current_color};
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 6px;
                padding: 6px 12px;
                text-align: left;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: #2C87FD;
            }}
        """)

    def _pick_color(self):
        # QColorDialog не всегда корректно парсит rgba(), конвертируем
        initial = self._to_qcolor(self._current_color)
        color = QColorDialog.getColor(initial, self, f"Выберите цвет: {self._label}",
                                       QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            # Формируем rgba строку с альфой 0-255
            if color.alpha() == 255:
                new_color = color.name()
            else:
                new_color = f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
            self._current_color = new_color
            self._update_appearance()
            if self._on_change:
                self._on_change(new_color)

    def get_color(self) -> str:
        return self._current_color

    def set_color(self, color: str):
        self._current_color = color
        self._update_appearance()

    @staticmethod
    def _to_qcolor(color_str: str) -> QColor:
        import re
        s = color_str.strip()
        rgba_match = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)', s)
        if rgba_match:
            r, g, b = int(rgba_match.group(1)), int(rgba_match.group(2)), int(rgba_match.group(3))
            a_str = rgba_match.group(4)
            a = 255 if a_str is None else int(float(a_str) * 255 if float(a_str) <= 1.0 else float(a_str))
            return QColor(r, g, b, a)
        return QColor(s)


class InventoryCustomizerDialog(QDialog):
    """Диалог inline-настройки оформления."""

    def __init__(self, inventory_window, parent=None):
        super().__init__(parent)
        self.inventory_window = inventory_window
        self.setWindowTitle("⚙️ Настройка оформления")
        self.setMinimumSize(680, 640)
        self.resize(720, 680)

        # Работаем с копией палитры, чтобы можно было откатить
        self._palette = ColorPalette(**{
            k: getattr(theme_manager.current_theme.palette, k)
            for k in ColorPalette.__dataclass_fields__
        })
        self._pickers = {}  # {field_name: ColorPickerButton}

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        title = QLabel("⚙️ Настройка оформления рабочей области")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            f"Текущая тема: <b>{theme_manager.current_theme.display_name}</b>. "
            "Изменения применяются мгновенно."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.6);")
        layout.addWidget(subtitle)

        # Вкладки
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                background: rgba(22, 28, 35, 180);
            }
            QTabBar::tab {
                background: rgba(22, 28, 35, 220);
                color: rgba(255, 255, 255, 0.7);
                padding: 10px 18px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background: rgba(44, 135, 253, 0.2);
                color: #2C87FD;
            }
            QTabBar::tab:hover {
                background: rgba(44, 135, 253, 0.1);
            }
        """)

        tabs.addTab(self._build_top_bar_tab(), "🕐 Верхняя панель")
        tabs.addTab(self._build_header_card_tab(), "👤 Карточка хедера")
        tabs.addTab(self._build_table_rows_tab(), "📊 Строки таблицы")
        tabs.addTab(self._build_background_tab(), "🖼 Фон")

        layout.addWidget(tabs)

        # Нижние кнопки
        bottom = QHBoxLayout()

        reset_btn = QPushButton("↺  Сбросить")
        reset_btn.setProperty("variant", "secondary")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_to_preset)
        bottom.addWidget(reset_btn)

        save_as_btn = QPushButton("💾  Сохранить как новую тему...")
        save_as_btn.setProperty("variant", "secondary")
        save_as_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_as_btn.clicked.connect(self._save_as_new_theme)
        bottom.addWidget(save_as_btn)

        # Показываем кнопку "Перезаписать" только для пользовательских тем
        if not theme_manager.current_theme.is_builtin:
            overwrite_btn = QPushButton("💾  Перезаписать текущую")
            overwrite_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            overwrite_btn.clicked.connect(self._overwrite_current_theme)
            bottom.addWidget(overwrite_btn)

        bottom.addStretch()

        close_btn = QPushButton("Закрыть")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)

        layout.addLayout(bottom)

    # ============================================================
    #  ВКЛАДКА 1: Верхняя панель (СМЕНА / ТАЙМЕР / НАСТРОЕНИЕ)
    # ============================================================
    def _build_top_bar_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(self._section_label("Фон и рамка панели"))
        self._add_picker(layout, "top_bar_bg", "Фон панели")
        self._add_picker(layout, "top_bar_border", "Рамка панели")

        layout.addWidget(self._section_label("Текст"))
        self._add_picker(layout, "top_bar_label", "Подписи (СМЕНА, ВРЕМЯ...)")
        self._add_picker(layout, "top_bar_value", "Значения")
        self._add_picker(layout, "timer_color", "Цвет таймера")

        layout.addStretch()
        return widget

    # ============================================================
    #  ВКЛАДКА 2: Карточка хедера
    # ============================================================
    def _build_header_card_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(self._section_label("Фон и рамка карточки"))
        self._add_picker(layout, "header_card_bg", "Фон карточки")
        self._add_picker(layout, "header_card_border", "Рамка карточки")
        self._add_picker(layout, "header_divider", "Вертикальные разделители")

        layout.addWidget(self._section_label("Текст"))
        self._add_picker(layout, "header_label", "Подписи (ОТДАЮЩИЙ...)")
        self._add_picker(layout, "header_value", "Значения (имена, точка)")

        layout.addStretch()
        return widget

    # ============================================================
    #  ВКЛАДКА 3: Строки таблицы
    # ============================================================
    def _build_table_rows_tab(self) -> QWidget:
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        # Избыток
        layout.addWidget(self._section_label("🔵 Избыток (факт > учёт)"))
        self._add_picker(layout, "table_row_more_bg", "Фон строки")
        self._add_picker(layout, "table_row_more_fg", "Текст строки")
        self._add_picker(layout, "status_badge_more_bg", "Фон бейджа 'Избыток'")
        self._add_picker(layout, "status_badge_more_fg", "Текст бейджа")

        # Недостача
        layout.addWidget(self._section_label("🔴 Недостача (факт < учёт)"))
        self._add_picker(layout, "table_row_less_bg", "Фон строки")
        self._add_picker(layout, "table_row_less_fg", "Текст строки")
        self._add_picker(layout, "status_badge_less_bg", "Фон бейджа 'Недостача'")
        self._add_picker(layout, "status_badge_less_fg", "Текст бейджа")

        # Сходится
        layout.addWidget(self._section_label("🟢 Сходится (факт = учёт)"))
        self._add_picker(layout, "table_row_equal_bg", "Фон строки")
        self._add_picker(layout, "table_row_equal_fg", "Текст строки")
        self._add_picker(layout, "status_badge_equal_bg", "Фон бейджа 'Сходится'")
        self._add_picker(layout, "status_badge_equal_fg", "Текст бейджа")

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ============================================================
    #  ВКЛАДКА 4: Фон
    # ============================================================
    def _build_background_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(self._section_label("Файл фона (гифка или картинка)"))

        # Текущий путь
        path_row = QHBoxLayout()
        self._bg_path_label = QLabel(self._palette.background_path or "Без фона")
        self._bg_path_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); padding: 8px; background: rgba(255, 255, 255, 0.05); border-radius: 6px;")
        self._bg_path_label.setWordWrap(True)
        path_row.addWidget(self._bg_path_label, 3)

        choose_btn = QPushButton("📁 Выбрать...")
        choose_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_btn.clicked.connect(self._choose_bg)
        path_row.addWidget(choose_btn)

        clear_btn = QPushButton("✕ Убрать")
        clear_btn.setProperty("variant", "secondary")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_bg)
        path_row.addWidget(clear_btn)

        layout.addLayout(path_row)

        # Прозрачность затемнения
        layout.addWidget(self._section_label("Затемнение поверх фона"))
        alpha_row = QHBoxLayout()
        alpha_row.addWidget(QLabel("Прозрачность оверлея (0 = нет затемнения, 255 = полностью чёрный):"))

        self._alpha_spin = QSpinBox()
        self._alpha_spin.setRange(0, 255)
        self._alpha_spin.setValue(self._palette.background_overlay_alpha)
        self._alpha_spin.setFixedWidth(80)
        self._alpha_spin.valueChanged.connect(self._on_alpha_changed)
        alpha_row.addWidget(self._alpha_spin)
        alpha_row.addStretch()
        layout.addLayout(alpha_row)

        layout.addStretch()
        return widget

    # ============================================================
    #  Вспомогательные
    # ============================================================
    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Inter", 11, QFont.Weight.DemiBold))
        lbl.setStyleSheet("color: rgba(255, 255, 255, 0.5); letter-spacing: 1px; margin-top: 6px;")
        return lbl

    def _add_picker(self, layout, field_name: str, label: str):
        """Добавляет строку: label + color picker button."""
        row = QHBoxLayout()
        row_label = QLabel(label)
        row_label.setMinimumWidth(200)
        row.addWidget(row_label)

        initial = getattr(self._palette, field_name)
        picker = ColorPickerButton(label, initial,
                                   on_change=lambda c, f=field_name: self._on_color_changed(f, c))
        row.addWidget(picker, 1)
        row.addStretch()

        self._pickers[field_name] = picker
        layout.addLayout(row)

    def _on_color_changed(self, field_name: str, color: str):
        """Вызывается при изменении любого цвета — применяет к текущей теме и окну."""
        setattr(self._palette, field_name, color)
        self._apply_to_current_theme()

    def _on_alpha_changed(self, value: int):
        self._palette.background_overlay_alpha = value
        self._apply_to_current_theme()

    def _choose_bg(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите фон", "",
            "Изображения (*.gif *.png *.jpg *.jpeg *.webp);;Все файлы (*)"
        )
        if not file_path:
            return
        try:
            project_root = Path(__file__).parent.parent
            rel_path = os.path.relpath(file_path, project_root)
            if rel_path.startswith(".."):
                rel_path = file_path
        except ValueError:
            rel_path = file_path

        self._palette.background_path = rel_path
        self._bg_path_label.setText(rel_path)
        self._apply_to_current_theme()

    def _clear_bg(self):
        self._palette.background_path = ""
        self._bg_path_label.setText("Без фона")
        self._apply_to_current_theme()

    def _apply_to_current_theme(self):
        """Копирует текущие значения палитры в активную тему и применяет."""
        from PyQt6.QtWidgets import QApplication
        current = theme_manager.current_theme
        # Копируем все поля палитры
        for field_name in ColorPalette.__dataclass_fields__:
            setattr(current.palette, field_name, getattr(self._palette, field_name))

        app = QApplication.instance()
        theme_manager.apply_theme(current, app)

        # Перекрашиваем текущее окно инвентаризации
        if hasattr(self.inventory_window, 'refresh_theme_colors'):
            self.inventory_window.refresh_theme_colors()

    def _reset_to_preset(self):
        """Сбрасывает все изменения к исходному пресету."""
        reply = QMessageBox.question(
            self, "Сбросить изменения",
            "Вернуть все цвета к исходным значениям текущей темы?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Находим оригинальный пресет по имени
        original = None
        for t in theme_manager.get_builtin_themes():
            if t.name == theme_manager.current_theme.name:
                original = t
                break

        if original is None:
            QMessageBox.warning(self, "Ошибка", "Исходный пресет не найден.")
            return

        # Копируем оригинальную палитру
        for field_name in ColorPalette.__dataclass_fields__:
            new_val = getattr(original.palette, field_name)
            setattr(self._palette, field_name, new_val)
            if field_name in self._pickers:
                self._pickers[field_name].set_color(new_val)

        self._alpha_spin.blockSignals(True)
        self._alpha_spin.setValue(self._palette.background_overlay_alpha)
        self._alpha_spin.blockSignals(False)
        self._bg_path_label.setText(self._palette.background_path or "Без фона")

        self._apply_to_current_theme()

    def _save_as_new_theme(self):
        """Сохраняет текущие настройки как новую пользовательскую тему."""
        name, ok = QInputDialog.getText(
            self, "Сохранить как новую тему",
            "Внутреннее имя (латиницей):", text="my_custom_theme"
        )
        if not ok or not name:
            return
        name = name.strip().replace(" ", "_").lower()

        display_name, ok = QInputDialog.getText(
            self, "Сохранить как новую тему",
            "Отображаемое название:", text="Моя тема"
        )
        if not ok or not display_name:
            return

        for t in theme_manager.get_all_themes():
            if t.name == name:
                QMessageBox.warning(self, "Ошибка", f"Тема '{name}' уже существует.")
                return

        new_theme = Theme(
            name=name,
            display_name=display_name.strip(),
            description=f"Создана из {theme_manager.current_theme.display_name}",
            is_builtin=False,
            palette=ColorPalette(**{
                k: getattr(self._palette, k) for k in ColorPalette.__dataclass_fields__
            }),
        )
        theme_manager.save_user_theme(new_theme)
        theme_manager.apply_theme(new_theme, QApplication.instance())

        QMessageBox.information(
            self, "Готово",
            f"Тема '{display_name}' сохранена и активирована.\n\n"
            f"Файл: user_themes/{name}.json"
        )

    def _overwrite_current_theme(self):
        """Перезаписывает текущую пользовательскую тему."""
        current = theme_manager.current_theme
        if current.is_builtin:
            QMessageBox.warning(
                self, "Нельзя",
                "Встроенные темы перезаписывать нельзя.\nИспользуйте 'Сохранить как новую тему'."
            )
            return

        reply = QMessageBox.question(
            self, "Перезаписать тему",
            f"Сохранить изменения в тему '{current.display_name}'?\n"
            "Предыдущие настройки будут утеряны.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Обновляем палитру и сохраняем
        for field_name in ColorPalette.__dataclass_fields__:
            setattr(current.palette, field_name, getattr(self._palette, field_name))

        theme_manager.save_user_theme(current)
        QMessageBox.information(self, "Готово", f"Тема '{current.display_name}' обновлена.")