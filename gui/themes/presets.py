"""
Три встроенных стиля приложения с расширенной палитрой.
"""
from gui.themes.base import Theme, ColorPalette


# ============================================================
#  1️⃣ SMARTSHELL DARK
# ============================================================
SMARTSHELL_DARK = Theme(
    name="smartshell_dark",
    display_name="SmartShell Dark",
    description="Фирменная тёмная тема SmartShell. Синие акценты, строгий стиль.",
    is_builtin=True,
    palette=ColorPalette(
        bg_primary="#0D1217",
        bg_item_primary="#161C23",
        bg_item_secondary="rgba(255, 255, 255, 0.1)",
        bg_modal="#0D1217",

        text_primary="#FFFFFF",
        text_secondary="rgba(255, 255, 255, 0.5)",
        text_disable="rgba(255, 255, 255, 0.3)",
        text_light="#FFFFFF",

        accent_blue="#2C87FD",
        accent_red="#FF3636",
        accent_orange="#FF7E36",
        accent_green="#27AE60",
        accent_violet="#7C62FF",

        bg_blue_10="rgba(44, 135, 253, 0.1)",
        bg_blue_20="rgba(44, 135, 253, 0.2)",
        bg_blue_30="rgba(44, 135, 253, 0.3)",
        bg_red_10="rgba(255, 54, 54, 0.1)",
        bg_red_20="rgba(255, 54, 54, 0.2)",
        bg_green_10="rgba(39, 174, 96, 0.1)",
        bg_green_20="rgba(39, 174, 96, 0.2)",

        btn_primary="#2C87FD",
        btn_primary_hover="#297BE6",
        btn_primary_pressed="#2670CF",
        btn_secondary="rgba(44, 135, 253, 0.1)",
        btn_secondary_hover="rgba(44, 135, 253, 0.2)",
        btn_disabled="rgba(255, 255, 255, 0.05)",
        btn_danger="rgba(231, 46, 46, 1)",
        btn_danger_hover="#c72626",

        border_gray_10="rgba(255, 255, 255, 0.1)",
        border_gray_20="rgba(255, 255, 255, 0.2)",
        border_gray_30="rgba(255, 255, 255, 0.3)",

        input_bg="#161C23",
        input_bg_disabled="rgba(255, 255, 255, 0.05)",

        font_family='"Inter", "Segoe UI", system-ui, sans-serif',
        
        # Панель инвентаризации
        top_bar_bg="rgba(22, 28, 35, 220)",
        top_bar_border="rgba(255, 255, 255, 0.2)",
        top_bar_label="rgba(255, 255, 255, 0.5)",
        top_bar_value="#FFFFFF",
        timer_color="#2C87FD",
        
        header_card_bg="rgba(22, 28, 35, 180)",
        header_card_border="rgba(255, 255, 255, 0.2)",
        header_label="rgba(255, 255, 255, 0.5)",
        header_value="#FFFFFF",
        header_divider="rgba(255, 255, 255, 0.2)",
        
        table_row_more_bg="rgba(44, 135, 253, 60)",
        table_row_more_fg="#93C5FD",
        table_row_less_bg="rgba(255, 54, 54, 60)",
        table_row_less_fg="#FCA5A5",
        table_row_equal_bg="rgba(39, 174, 96, 60)",
        table_row_equal_fg="#86EFAC",
        
        status_badge_more_bg="rgba(44, 135, 253, 0.2)",
        status_badge_more_fg="#2C87FD",
        status_badge_less_bg="rgba(255, 54, 54, 0.1)",
        status_badge_less_fg="#FF3636",
        status_badge_equal_bg="rgba(39, 174, 96, 0.1)",
        status_badge_equal_fg="#27AE60",
        
        background_path="",
        background_overlay_alpha=180,
    ),
)


# ============================================================
#  2️⃣ CYBER NEON
# ============================================================
CYBER_NEON = Theme(
    name="cyber_neon",
    display_name="Cyber Neon",
    description="Яркий киберпанк-стиль. Фиолетовые и розовые неоновые акценты.",
    is_builtin=True,
    palette=ColorPalette(
        bg_primary="#0A0118",
        bg_item_primary="#1A0B2E",
        bg_item_secondary="rgba(255, 0, 200, 0.08)",
        bg_modal="#0A0118",

        text_primary="#F5E6FF",
        text_secondary="rgba(245, 230, 255, 0.55)",
        text_disable="rgba(245, 230, 255, 0.3)",
        text_light="#FFFFFF",

        accent_blue="#00F0FF",
        accent_red="#FF0066",
        accent_orange="#FFB800",
        accent_green="#00FF94",
        accent_violet="#B026FF",

        bg_blue_10="rgba(0, 240, 255, 0.1)",
        bg_blue_20="rgba(0, 240, 255, 0.2)",
        bg_blue_30="rgba(0, 240, 255, 0.3)",
        bg_red_10="rgba(255, 0, 102, 0.15)",
        bg_red_20="rgba(255, 0, 102, 0.25)",
        bg_green_10="rgba(0, 255, 148, 0.12)",
        bg_green_20="rgba(0, 255, 148, 0.22)",

        btn_primary="#B026FF",
        btn_primary_hover="#C850FF",
        btn_primary_pressed="#9010E0",
        btn_secondary="rgba(176, 38, 255, 0.15)",
        btn_secondary_hover="rgba(176, 38, 255, 0.25)",
        btn_disabled="rgba(245, 230, 255, 0.08)",
        btn_danger="#FF0066",
        btn_danger_hover="#FF3388",

        border_gray_10="rgba(176, 38, 255, 0.15)",
        border_gray_20="rgba(176, 38, 255, 0.3)",
        border_gray_30="rgba(176, 38, 255, 0.5)",

        input_bg="#1A0B2E",
        input_bg_disabled="rgba(245, 230, 255, 0.05)",

        font_family='"Rajdhani", "Inter", "Segoe UI", sans-serif',
        
        # Панель инвентаризации — неоновые цвета
        top_bar_bg="rgba(26, 11, 46, 230)",
        top_bar_border="rgba(176, 38, 255, 0.4)",
        top_bar_label="rgba(245, 230, 255, 0.6)",
        top_bar_value="#F5E6FF",
        timer_color="#00F0FF",
        
        header_card_bg="rgba(26, 11, 46, 200)",
        header_card_border="rgba(176, 38, 255, 0.4)",
        header_label="rgba(245, 230, 255, 0.6)",
        header_value="#F5E6FF",
        header_divider="rgba(176, 38, 255, 0.4)",
        
        table_row_more_bg="rgba(0, 240, 255, 50)",
        table_row_more_fg="#00F0FF",
        table_row_less_bg="rgba(255, 0, 102, 50)",
        table_row_less_fg="#FF0066",
        table_row_equal_bg="rgba(0, 255, 148, 50)",
        table_row_equal_fg="#00FF94",
        
        status_badge_more_bg="rgba(0, 240, 255, 0.25)",
        status_badge_more_fg="#00F0FF",
        status_badge_less_bg="rgba(255, 0, 102, 0.25)",
        status_badge_less_fg="#FF0066",
        status_badge_equal_bg="rgba(0, 255, 148, 0.2)",
        status_badge_equal_fg="#00FF94",
        
        background_path="",
        background_overlay_alpha=160,
    ),
)


# ============================================================
#  3️⃣ CLEAN LIGHT
# ============================================================
CLEAN_LIGHT = Theme(
    name="clean_light",
    display_name="Clean Light",
    description="Минималистичная светлая тема. Чистота, воздух, акцент на контенте.",
    is_builtin=True,
    palette=ColorPalette(
        bg_primary="#F8FAFC",
        bg_item_primary="#FFFFFF",
        bg_item_secondary="rgba(15, 23, 42, 0.04)",
        bg_modal="#FFFFFF",

        text_primary="#0F172A",
        text_secondary="rgba(15, 23, 42, 0.6)",
        text_disable="rgba(15, 23, 42, 0.35)",
        text_light="#FFFFFF",

        accent_blue="#3B82F6",
        accent_red="#EF4444",
        accent_orange="#F59E0B",
        accent_green="#10B981",
        accent_violet="#8B5CF6",

        bg_blue_10="rgba(59, 130, 246, 0.08)",
        bg_blue_20="rgba(59, 130, 246, 0.15)",
        bg_blue_30="rgba(59, 130, 246, 0.25)",
        bg_red_10="rgba(239, 68, 68, 0.08)",
        bg_red_20="rgba(239, 68, 68, 0.15)",
        bg_green_10="rgba(16, 185, 129, 0.08)",
        bg_green_20="rgba(16, 185, 129, 0.15)",

        btn_primary="#3B82F6",
        btn_primary_hover="#2563EB",
        btn_primary_pressed="#1D4ED8",
        btn_secondary="rgba(59, 130, 246, 0.08)",
        btn_secondary_hover="rgba(59, 130, 246, 0.15)",
        btn_disabled="rgba(15, 23, 42, 0.05)",
        btn_danger="#EF4444",
        btn_danger_hover="#DC2626",

        border_gray_10="rgba(15, 23, 42, 0.08)",
        border_gray_20="rgba(15, 23, 42, 0.12)",
        border_gray_30="rgba(15, 23, 42, 0.2)",

        input_bg="#FFFFFF",
        input_bg_disabled="rgba(15, 23, 42, 0.05)",

        box_shadow="rgba(15, 23, 42, 0.08)",

        font_family='"Inter", "Segoe UI", system-ui, sans-serif',
        
        # Панель инвентаризации — светлые цвета
        top_bar_bg="rgba(255, 255, 255, 240)",
        top_bar_border="rgba(15, 23, 42, 0.12)",
        top_bar_label="rgba(15, 23, 42, 0.6)",
        top_bar_value="#0F172A",
        timer_color="#3B82F6",
        
        header_card_bg="rgba(255, 255, 255, 220)",
        header_card_border="rgba(15, 23, 42, 0.12)",
        header_label="rgba(15, 23, 42, 0.6)",
        header_value="#0F172A",
        header_divider="rgba(15, 23, 42, 0.12)",
        
        table_row_more_bg="rgba(59, 130, 246, 40)",
        table_row_more_fg="#2563EB",
        table_row_less_bg="rgba(239, 68, 68, 40)",
        table_row_less_fg="#DC2626",
        table_row_equal_bg="rgba(16, 185, 129, 40)",
        table_row_equal_fg="#059669",
        
        status_badge_more_bg="rgba(59, 130, 246, 0.12)",
        status_badge_more_fg="#3B82F6",
        status_badge_less_bg="rgba(239, 68, 68, 0.12)",
        status_badge_less_fg="#EF4444",
        status_badge_equal_bg="rgba(16, 185, 129, 0.12)",
        status_badge_equal_fg="#10B981",
        
        background_path="",
        background_overlay_alpha=200,
    ),
)


BUILTIN_THEMES = [SMARTSHELL_DARK, CYBER_NEON, CLEAN_LIGHT]