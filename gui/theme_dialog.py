"""
Диалог выбора темы с возможностью настройки фона.
"""
import os
from pathlib import Path

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame,
                             QLineEdit, QMessageBox, QInputDialog, QFileDialog,
                             QSpinBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from gui.themes import theme_manager, Theme


class ThemePreviewCard(QFrame):
    """Карточка-превью темы."""

    def __init__(self, theme: Theme, is_current: bool, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._is_current = is_current
        self.setFixedHeight(160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        p = theme.palette
        self.setStyleSheet(f"""
            ThemePreviewCard {{
                background-color: {p.bg_item_primary};
                border: 2px solid {'#2C87FD' if is_current else p.border_gray_20};
                border-radius: 12px;
                padding: 0;
            }}
            ThemePreviewCard:hover {{
                border-color: {p.accent_blue};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # Заголовок
        header = QHBoxLayout()
        title = QLabel(theme.display_name)
        title.setFont(QFont("Inter", 14, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {p.text_primary}; background: transparent; border: none;")
        header.addWidget(title)

        if theme.is_builtin:
            badge = QLabel("ВСТРОЕННАЯ")
            badge.setStyleSheet(f"""
                background-color: {p.bg_blue_10};
                color: {p.accent_blue};
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 600;
                border: none;
            """)
            header.addWidget(badge)
        if is_current:
            current_badge = QLabel("✓ АКТИВНА")
            current_badge.setStyleSheet(f"""
                background-color: {p.bg_green_10};
                color: {p.accent_green};
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 600;
                border: none;
            """)
            header.addWidget(current_badge)

        header.addStretch()
        layout.addLayout(header)

        # Описание
        desc = QLabel(theme.description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {p.text_secondary}; background: transparent; border: none; font-size: 12px;")
        layout.addWidget(desc)

        # Превью цветов
        colors_row = QHBoxLayout()
        colors_row.setSpacing(6)
        preview_colors = [
            p.bg_primary, p.bg_item_primary,
            p.accent_blue, p.accent_green,
            p.accent_red, p.accent_orange, p.accent_violet,
        ]
        for color in preview_colors:
            swatch = QLabel()
            swatch.setFixedSize(24, 24)
            bg_color = color if not color.startswith("rgba") else p.bg_item_primary
            swatch.setStyleSheet(f"""
                background-color: {bg_color};
                border: 1px solid {p.border_gray_30};
                border-radius: 4px;
            """)
            colors_row.addWidget(swatch)
        colors_row.addStretch()
        layout.addLayout(colors_row)

        # Инфо о фоне
        if p.background_path:
            bg_info = QLabel(f"🖼 Фон: {Path(p.background_path).name}")
            bg_info.setStyleSheet(f"color: {p.text_secondary}; background: transparent; border: none; font-size: 11px;")
            layout.addWidget(bg_info)

        layout.addStretch()


class ThemeDialog(QDialog):
    """Диалог выбора и управления темами."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка темы")
        self.setMinimumSize(720, 640)
        self.resize(760, 680)

        self._preview_cards = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Заголовок
        title = QLabel("🎨 Темы оформления")
        title.setFont(QFont("Inter", 22, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Выберите стиль приложения. Пользовательские темы сохраняются в папке user_themes/")
        subtitle.setProperty("secondary", True)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Разделитель
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("max-height: 1px; background-color: rgba(255, 255, 255, 0.1);")
        layout.addWidget(sep)

        # ============================================================
        #  СЕКЦИЯ: Настройка фона текущей темы
        # ============================================================
        bg_section = QWidget()
        bg_section.setStyleSheet(f"""
            QWidget {{
                background-color: {theme_manager.current_theme.palette.bg_item_primary};
                border: 1px solid {theme_manager.current_theme.palette.border_gray_20};
                border-radius: 10px;
            }}
        """)
        bg_layout = QVBoxLayout(bg_section)
        bg_layout.setContentsMargins(16, 12, 16, 12)
        bg_layout.setSpacing(10)

        bg_title = QLabel("🖼 Фон рабочей области")
        bg_title.setFont(QFont("Inter", 12, QFont.Weight.DemiBold))
        bg_title.setStyleSheet("background: transparent; border: none;")
        bg_layout.addWidget(bg_title)

        # Путь к фону
        path_row = QHBoxLayout()
        self.bg_path_label = QLabel(
            theme_manager.current_theme.palette.background_path or "Без фона"
        )
        self.bg_path_label.setStyleSheet("background: transparent; border: none; color: rgba(255, 255, 255, 0.5);")
        path_row.addWidget(self.bg_path_label, 3)

        choose_bg_btn = QPushButton("Выбрать файл...")
        choose_bg_btn.setProperty("variant", "secondary")
        choose_bg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_bg_btn.clicked.connect(self._choose_background)
        path_row.addWidget(choose_bg_btn)

        clear_bg_btn = QPushButton("Убрать")
        clear_bg_btn.setProperty("variant", "secondary")
        clear_bg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_bg_btn.clicked.connect(self._clear_background)
        path_row.addWidget(clear_bg_btn)

        bg_layout.addLayout(path_row)

        # Прозрачность затемнения
        alpha_row = QHBoxLayout()
        alpha_label = QLabel("Затемнение:")
        alpha_label.setStyleSheet("background: transparent; border: none;")
        alpha_row.addWidget(alpha_label)

        self.alpha_spin = QSpinBox()
        self.alpha_spin.setRange(0, 255)
        self.alpha_spin.setValue(theme_manager.current_theme.palette.background_overlay_alpha)
        self.alpha_spin.setStyleSheet("background: transparent; border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px; padding: 4px;")
        self.alpha_spin.valueChanged.connect(self._update_alpha)
        alpha_row.addWidget(self.alpha_spin)

        alpha_row.addStretch()
        bg_layout.addLayout(alpha_row)

        layout.addWidget(bg_section)

        # ============================================================
        #  Скроллируемый список тем
        # ============================================================
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(scroll_widget)
        self.cards_layout.setSpacing(10)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)

        self._refresh_cards()

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Нижние кнопки
        bottom = QHBoxLayout()

        self.save_as_btn = QPushButton("💾  Сохранить текущую как...")
        self.save_as_btn.setProperty("variant", "secondary")
        self.save_as_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_as_btn.clicked.connect(self._save_current_as)
        bottom.addWidget(self.save_as_btn)

        self.delete_btn = QPushButton("🗑  Удалить пользовательскую")
        self.delete_btn.setProperty("variant", "secondary")
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.clicked.connect(self._delete_user_theme)
        bottom.addWidget(self.delete_btn)

        bottom.addStretch()

        close_btn = QPushButton("Закрыть")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)

        layout.addLayout(bottom)

    def _refresh_cards(self):
        """Пересоздаёт карточки тем."""
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._preview_cards.clear()
        current_name = theme_manager.current_theme.name

        for theme in theme_manager.get_all_themes():
            card = ThemePreviewCard(theme, theme.name == current_name)
            card.mousePressEvent = lambda e, t=theme: self._select_theme(t)
            self.cards_layout.addWidget(card)
            self._preview_cards.append(card)

        self.cards_layout.addStretch()

    def _select_theme(self, theme: Theme):
        """Применяет выбранную тему."""
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        theme_manager.apply_theme(theme, app)
        self._refresh_cards()
        # Обновляем секцию фона
        self.bg_path_label.setText(theme.palette.background_path or "Без фона")
        self.alpha_spin.blockSignals(True)
        self.alpha_spin.setValue(theme.palette.background_overlay_alpha)
        self.alpha_spin.blockSignals(False)

    def _choose_background(self):
        """Открывает диалог выбора файла фона."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите фон (гифка или картинка)",
            "",
            "Изображения (*.gif *.png *.jpg *.jpeg *.webp);;Все файлы (*)"
        )
        if not file_path:
            return

        # Сохраняем относительный путь от корня проекта
        try:
            project_root = Path(__file__).parent.parent
            rel_path = os.path.relpath(file_path, project_root)
            # Если путь выходит за пределы проекта — сохраняем абсолютный
            if rel_path.startswith(".."):
                rel_path = file_path
        except ValueError:
            rel_path = file_path

        # Обновляем текущую тему
        current = theme_manager.current_theme
        current.palette.background_path = rel_path
        
        # Пересоздаём окно инвентаризации, чтобы фон обновился
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        theme_manager.apply_theme(current, app)
        
        self.bg_path_label.setText(rel_path)
        self._refresh_cards()

    def _clear_background(self):
        """Убирает фон из текущей темы."""
        current = theme_manager.current_theme
        current.palette.background_path = ""
        
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        theme_manager.apply_theme(current, app)
        
        self.bg_path_label.setText("Без фона")
        self._refresh_cards()

    def _update_alpha(self, value: int):
        """Обновляет прозрачность затемнения."""
        current = theme_manager.current_theme
        current.palette.background_overlay_alpha = value
        
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        theme_manager.apply_theme(current, app)

    def _save_current_as(self):
        """Сохраняет текущую тему под новым именем."""
        name, ok = QInputDialog.getText(
            self, "Сохранить тему",
            "Внутреннее имя (латиницей, без пробелов):",
            text="my_theme"
        )
        if not ok or not name:
            return
        name = name.strip().replace(" ", "_").lower()

        display_name, ok = QInputDialog.getText(
            self, "Сохранить тему",
            "Отображаемое название:",
            text="Моя тема"
        )
        if not ok or not display_name:
            return

        for t in theme_manager.get_all_themes():
            if t.name == name:
                QMessageBox.warning(
                    self, "Ошибка",
                    f"Тема с именем '{name}' уже существует."
                )
                return

        new_theme = theme_manager.duplicate_theme(
            theme_manager.current_theme, name, display_name.strip()
        )
        theme_manager.save_user_theme(new_theme)
        self._refresh_cards()
        QMessageBox.information(
            self, "Готово",
            f"Тема '{display_name}' сохранена в папке user_themes/\n\n"
            "Теперь её можно редактировать вручную в JSON-файле."
        )

    def _delete_user_theme(self):
        """Удаляет выбранную пользовательскую тему."""
        user_themes = theme_manager.get_user_themes()
        if not user_themes:
            QMessageBox.information(self, "Информация", "Нет пользовательских тем.")
            return

        names = [t.display_name for t in user_themes]
        name, ok = QInputDialog.getItem(
            self, "Удалить тему",
            "Выберите тему для удаления:",
            names, 0, False
        )
        if not ok:
            return

        for t in user_themes:
            if t.display_name == name:
                reply = QMessageBox.question(
                    self, "Подтверждение",
                    f"Удалить тему '{t.display_name}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    theme_manager.delete_user_theme(t.name)
                    self._refresh_cards()
                break