"""
Базовые классы для системы тем.
Расширенная версия с цветами для панели инвентаризации и поддержкой фонов.
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional


@dataclass
class ColorPalette:
    """Полная палитра цветов темы."""

    # === Фоны ===
    bg_primary: str = "#0D1217"
    bg_item_primary: str = "#161C23"
    bg_item_secondary: str = "rgba(255, 255, 255, 0.1)"
    bg_modal: str = "#0D1217"

    # === Текст ===
    text_primary: str = "#FFFFFF"
    text_secondary: str = "rgba(255, 255, 255, 0.5)"
    text_disable: str = "rgba(255, 255, 255, 0.3)"
    text_light: str = "#FFFFFF"

    # === Акценты (статусы) ===
    accent_blue: str = "#2C87FD"
    accent_red: str = "#FF3636"
    accent_orange: str = "#FF7E36"
    accent_green: str = "#27AE60"
    accent_violet: str = "#7C62FF"
    accent_wave: str = "#38C9CF"

    # === Полупрозрачные акценты ===
    bg_blue_10: str = "rgba(44, 135, 253, 0.1)"
    bg_blue_20: str = "rgba(44, 135, 253, 0.2)"
    bg_blue_30: str = "rgba(44, 135, 253, 0.3)"
    bg_red_10: str = "rgba(255, 54, 54, 0.1)"
    bg_red_20: str = "rgba(255, 54, 54, 0.2)"
    bg_green_10: str = "rgba(39, 174, 96, 0.1)"
    bg_green_20: str = "rgba(39, 174, 96, 0.2)"
    bg_orange_10: str = "rgba(255, 126, 54, 0.1)"

    # === Кнопки ===
    btn_primary: str = "#2C87FD"
    btn_primary_hover: str = "#297BE6"
    btn_primary_pressed: str = "#2670CF"
    btn_secondary: str = "rgba(44, 135, 253, 0.1)"
    btn_secondary_hover: str = "rgba(44, 135, 253, 0.2)"
    btn_disabled: str = "rgba(255, 255, 255, 0.05)"
    btn_danger: str = "rgba(231, 46, 46, 1)"
    btn_danger_hover: str = "#c72626"

    # === Границы ===
    border_gray_10: str = "rgba(255, 255, 255, 0.1)"
    border_gray_20: str = "rgba(255, 255, 255, 0.2)"
    border_gray_30: str = "rgba(255, 255, 255, 0.3)"

    # === Инпуты ===
    input_bg: str = "#161C23"
    input_bg_disabled: str = "rgba(255, 255, 255, 0.05)"

    # === Разное ===
    box_shadow: str = "rgba(13, 18, 23, 0.8)"
    font_family: str = '"Inter", "Segoe UI", system-ui, sans-serif'
    border_radius: str = "8px"
    border_radius_card: str = "12px"

    # ============================================================
    #  НОВОЕ: Цвета панели инвентаризации
    # ============================================================
    
    # Верхняя панель (СМЕНА / ТАЙМЕР / НАСТРОЕНИЕ)
    top_bar_bg: str = "rgba(22, 28, 35, 220)"
    top_bar_border: str = "rgba(255, 255, 255, 0.2)"
    top_bar_label: str = "rgba(255, 255, 255, 0.5)"
    top_bar_value: str = "#FFFFFF"
    timer_color: str = "#2C87FD"
    
    # Карточка хедера (ОТДАЮЩИЙ / ПРИНИМАЮЩИЙ / ТОЧКА)
    header_card_bg: str = "rgba(22, 28, 35, 180)"
    header_card_border: str = "rgba(255, 255, 255, 0.2)"
    header_label: str = "rgba(255, 255, 255, 0.5)"
    header_value: str = "#FFFFFF"
    header_divider: str = "rgba(255, 255, 255, 0.2)"
    
    # Таблица — цвета строк по статусам
    table_row_more_bg: str = "rgba(44, 135, 253, 60)"
    table_row_more_fg: str = "#93C5FD"
    table_row_less_bg: str = "rgba(255, 54, 54, 60)"
    table_row_less_fg: str = "#FCA5A5"
    table_row_equal_bg: str = "rgba(39, 174, 96, 60)"
    table_row_equal_fg: str = "#86EFAC"
    
    # Бейджи статусов (колонка "Статус")
    status_badge_more_bg: str = "rgba(44, 135, 253, 0.2)"
    status_badge_more_fg: str = "#2C87FD"
    status_badge_less_bg: str = "rgba(255, 54, 54, 0.1)"
    status_badge_less_fg: str = "#FF3636"
    status_badge_equal_bg: str = "rgba(39, 174, 96, 0.1)"
    status_badge_equal_fg: str = "#27AE60"
    
    # ============================================================
    #  НОВОЕ: Фон (гифка/картинка)
    # ============================================================
    background_path: str = ""  # пустая строка = без фона
    background_overlay_alpha: int = 180  # 0-255, прозрачность затемнения


@dataclass
class Theme:
    """Полная тема приложения."""
    name: str
    display_name: str
    description: str = ""
    is_builtin: bool = False
    palette: ColorPalette = field(default_factory=ColorPalette)

    def to_dict(self) -> Dict:
        """Преобразует тему в словарь (для JSON)."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "is_builtin": self.is_builtin,
            "palette": asdict(self.palette),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Theme":
        """Восстанавливает тему из словаря. Поддерживает старые темы без новых полей."""
        palette_data = data.get("palette", {})
        # Берём только те поля, которые есть в ColorPalette
        palette = ColorPalette(**{
            k: v for k, v in palette_data.items()
            if hasattr(ColorPalette, k)
        })
        return cls(
            name=data.get("name", "custom"),
            display_name=data.get("display_name", "Custom"),
            description=data.get("description", ""),
            is_builtin=data.get("is_builtin", False),
            palette=palette,
        )