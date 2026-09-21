"""
Прослойка обратной совместимости со старой дизайн-системой.

SmartShellColors теперь — прокси-объект, который читает цвета
из текущей активной темы через theme_manager.

Это значит, что весь старый код вида:
    SmartShellColors.BG_PRIMARY
    SmartShellColors.ACCENT_BLUE
    SmartShellColors.BTN_PRIMARY_HOVER
...продолжает работать без изменений, но автоматически использует
цвета текущей выбранной темы.
"""
from gui.themes import theme_manager, SMARTSHELL_DARK


class _ColorsProxy:
    """
    Прокси, который динамически читает атрибуты из палитры текущей темы.
    
    Преобразует имена UPPER_CASE → lower_case (snake_case),
    потому что в ColorPalette используются snake_case имена.
    """

    def __getattr__(self, name: str):
        palette = theme_manager.current_theme.palette
        attr_name = name.lower()
        if hasattr(palette, attr_name):
            return getattr(palette, attr_name)
        # Fallback для полей, которых нет в новой палитре
        # (например, специфичные для старого SmartShell поля)
        fallback_map = {
            "bg_tabs": palette.bg_item_secondary,
            "bg_divider": palette.border_gray_20,
            "text_link": palette.accent_blue,
            "text_error": palette.accent_red,
            "text_warning": palette.accent_orange,
            "text_green": palette.accent_green,
            "text_violet": palette.accent_violet,
            "icon_primary": palette.text_primary,
            "icon_secondary": palette.text_secondary,
            "accent_wave": "#38C9CF",
            "accent_pink": "#B540B8",
            "bg_orange_10": palette.bg_orange_10,
            "btn_primary_pressed": palette.btn_primary_pressed,
            "btn_red_hover": palette.bg_red_10,
            "btn_red_primary": palette.btn_danger,
            "border_blue": palette.accent_blue,
        }
        if attr_name in fallback_map:
            return fallback_map[attr_name]
        raise AttributeError(f"Color '{name}' not found in current theme palette")


# Глобальный синглтон-прокси — импортируется во все модули
SmartShellColors = _ColorsProxy()


def apply_global_style(app):
    """
    Применяет стиль текущей темы ко всему QApplication.
    
    Делегирует работу theme_manager, который:
    1. Генерирует QSS из Theme через generator.py
    2. Устанавливает его через app.setStyleSheet()
    3. Уведомляет подписчиков о смене темы
    """
    theme_manager.apply_theme(theme_manager.current_theme, app)