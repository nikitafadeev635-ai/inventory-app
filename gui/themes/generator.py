"""
Генератор Qt StyleSheet из объекта Theme.
"""
from gui.themes.base import Theme


def generate_stylesheet(theme: Theme) -> str:
    """Возвращает полный QSS для применения к QApplication."""
    p = theme.palette

    return f"""
/* ============================================================
   Тема: {theme.display_name}
   ============================================================ */

QWidget {{
    background-color: {p.bg_primary};
    color: {p.text_primary};
    font-family: {p.font_family};
    font-size: 14px;
    font-weight: 400;
}}

QLabel {{
    color: {p.text_primary};
    background: transparent;
}}

QLabel[secondary="true"] {{
    color: {p.text_secondary};
}}

/* ============================================================
   КНОПКИ
   ============================================================ */
QPushButton {{
    background-color: {p.btn_primary};
    color: {p.text_light};
    border: none;
    border-radius: {p.border_radius};
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 500;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {p.btn_primary_hover};
}}

QPushButton:pressed {{
    background-color: {p.btn_primary_pressed};
}}

QPushButton:disabled {{
    background-color: {p.btn_disabled};
    color: {p.text_disable};
}}

QPushButton[variant="secondary"] {{
    background-color: {p.btn_secondary};
    color: {p.accent_blue};
}}
QPushButton[variant="secondary"]:hover {{
    background-color: {p.btn_secondary_hover};
}}

QPushButton[variant="danger"] {{
    background-color: {p.btn_danger};
}}
QPushButton[variant="danger"]:hover {{
    background-color: {p.btn_danger_hover};
}}

/* ============================================================
   ИНПУТЫ
   ============================================================ */
QLineEdit {{
    background-color: {p.input_bg};
    color: {p.text_primary};
    border: 1px solid {p.border_gray_20};
    border-radius: {p.border_radius};
    padding: 10px 14px;
    font-size: 14px;
    selection-background-color: {p.bg_blue_30};
}}

QLineEdit:focus {{
    border: 1px solid {p.accent_blue};
}}

QLineEdit:disabled {{
    background-color: {p.input_bg_disabled};
    color: {p.text_disable};
}}

QLineEdit::placeholder {{
    color: {p.text_disable};
}}

/* ============================================================
   КОМБОБОКСЫ
   ============================================================ */
QComboBox {{
    background-color: {p.input_bg};
    color: {p.text_primary};
    border: 1px solid {p.border_gray_20};
    border-radius: {p.border_radius};
    padding: 10px 14px;
    font-size: 14px;
    min-height: 20px;
}}

QComboBox:hover {{
    border: 1px solid {p.border_gray_30};
}}

QComboBox:focus {{
    border: 1px solid {p.accent_blue};
}}

QComboBox::drop-down {{
    border: none;
    width: 30px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {p.text_secondary};
    margin-right: 12px;
}}

QComboBox QAbstractItemView {{
    background-color: {p.bg_item_primary};
    color: {p.text_primary};
    border: 1px solid {p.border_gray_20};
    border-radius: {p.border_radius};
    padding: 4px;
    outline: none;
    selection-background-color: {p.bg_blue_20};
    selection-color: {p.text_primary};
}}

QComboBox QAbstractItemView::item {{
    padding: 8px 12px;
    border-radius: 4px;
    min-height: 20px;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {p.bg_blue_10};
}}

QComboBox QAbstractItemView::item:selected {{
    background-color: {p.bg_blue_20};
}}

/* ============================================================
   ЧЕКБОКСЫ
   ============================================================ */
QCheckBox {{
    color: {p.text_primary};
    spacing: 8px;
    font-size: 14px;
    background: transparent;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    background-color: {p.input_bg};
    border: 1.5px solid {p.border_gray_30};
}}

QCheckBox::indicator:hover {{
    border-color: {p.accent_blue};
    background-color: {p.bg_blue_10};
}}

QCheckBox::indicator:checked {{
    background-color: {p.accent_blue};
    border-color: {p.accent_blue};
}}

/* ============================================================
   ТАБЛИЦЫ
   ============================================================ */
QTableWidget {{
    background-color: {p.bg_item_primary};
    alternate-background-color: rgba(255, 255, 255, 0.02);
    color: {p.text_primary};
    border: 1px solid {p.border_gray_20};
    border-radius: {p.border_radius};
    gridline-color: {p.border_gray_10};
    font-size: 14px;
    selection-background-color: {p.bg_blue_20};
    selection-color: {p.text_primary};
}}

QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {p.border_gray_10};
}}

QTableWidget::item:selected {{
    background-color: {p.bg_blue_20};
    color: {p.text_primary};
}}

QHeaderView::section {{
    background-color: {p.bg_primary};
    color: {p.text_secondary};
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid {p.border_gray_20};
    border-right: 1px solid {p.border_gray_10};
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ============================================================
   СКРОЛЛБАРЫ
   ============================================================ */
QScrollBar:vertical {{
    background: {p.bg_primary};
    width: 14px;
    margin: 0;
    border-radius: {p.border_radius};
}}

QScrollBar::handle:vertical {{
    background: {p.accent_blue};
    border: 5px solid transparent;
    border-radius: {p.border_radius};
    min-height: 30px;
    background-clip: padding-box;
}}

QScrollBar::handle:vertical:hover {{
    background: {p.btn_primary_hover};
    background-clip: padding-box;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: {p.bg_primary};
    height: 14px;
    border-radius: {p.border_radius};
}}

QScrollBar::handle:horizontal {{
    background: {p.accent_blue};
    border: 5px solid transparent;
    border-radius: {p.border_radius};
    min-width: 30px;
    background-clip: padding-box;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ============================================================
   ДИАЛОГИ
   ============================================================ */
QDialog {{
    background-color: {p.bg_modal};
}}

/* ============================================================
   TOOLTIPS
   ============================================================ */
QToolTip {{
    background-color: {p.bg_item_primary};
    color: {p.text_primary};
    border: 1px solid {p.border_gray_20};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""