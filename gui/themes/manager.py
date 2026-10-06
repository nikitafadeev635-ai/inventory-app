"""
Менеджер тем: загрузка, сохранение, применение.
"""
import os
import json
from pathlib import Path
from typing import List, Optional

from gui.themes.base import Theme, ColorPalette
from gui.themes.presets import BUILTIN_THEMES
from gui.themes.generator import generate_stylesheet

# Папка для пользовательских тем (рядом с .exe)
from core.paths import get_themes_dir
USER_THEMES_DIR = get_themes_dir()

class ThemeManager:
    """Централизованный менеджер тем приложения."""

    def __init__(self):
        self._current_theme: Theme = BUILTIN_THEMES[0]  # SmartShell Dark по умолчанию
        self._on_change_callbacks = []
        USER_THEMES_DIR.mkdir(parents=True, exist_ok=True)

    # ============================================================
    #  Получение списка тем
    # ============================================================
    def get_builtin_themes(self) -> List[Theme]:
        """Возвращает встроенные темы."""
        return list(BUILTIN_THEMES)

    def get_user_themes(self) -> List[Theme]:
        """Загружает все пользовательские темы из JSON файлов."""
        user_themes = []
        if not USER_THEMES_DIR.exists():
            return user_themes

        for file_path in USER_THEMES_DIR.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                theme = Theme.from_dict(data)
                theme.is_builtin = False
                user_themes.append(theme)
            except Exception as e:
                print(f"[ThemeManager] Ошибка загрузки {file_path}: {e}")

        return user_themes

    def get_all_themes(self) -> List[Theme]:
        """Все темы: встроенные + пользовательские."""
        return self.get_builtin_themes() + self.get_user_themes()

    # ============================================================
    #  Применение темы
    # ============================================================
    @property
    def current_theme(self) -> Theme:
        return self._current_theme

    @property
    def colors(self) -> ColorPalette:
        """Быстрый доступ к палитре текущей темы."""
        return self._current_theme.palette

    def apply_theme(self, theme: Theme, app=None):
        """Применяет тему ко всему приложению."""
        self._current_theme = theme
        stylesheet = generate_stylesheet(theme)

        if app is not None:
            app.setStyleSheet(stylesheet)

        # Уведомляем подписчиков
        for callback in self._on_change_callbacks:
            try:
                callback(theme)
            except Exception as e:
                print(f"[ThemeManager] Ошибка в callback: {e}")

        print(f"[ThemeManager] ✓ Применена тема: {theme.display_name}")

    def apply_by_name(self, name: str, app=None) -> bool:
        """Применяет тему по имени."""
        for theme in self.get_all_themes():
            if theme.name == name:
                self.apply_theme(theme, app)
                return True
        print(f"[ThemeManager] ✗ Тема '{name}' не найдена")
        return False

    # ============================================================
    #  Сохранение пользовательских тем
    # ============================================================
    def save_user_theme(self, theme: Theme) -> Path:
        """Сохраняет тему как пользовательскую в JSON."""
        theme.is_builtin = False
        file_path = USER_THEMES_DIR / f"{theme.name}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(theme.to_dict(), f, ensure_ascii=False, indent=2)

        print(f"[ThemeManager] ✓ Тема сохранена: {file_path}")
        return file_path

    def delete_user_theme(self, name: str) -> bool:
        """Удаляет пользовательскую тему."""
        file_path = USER_THEMES_DIR / f"{name}.json"
        if file_path.exists():
            file_path.unlink()
            print(f"[ThemeManager] ✓ Тема удалена: {name}")
            return True
        return False

    def duplicate_theme(self, source: Theme, new_name: str, new_display_name: str) -> Theme:
        """Создаёт копию темы с новым именем."""
        new_theme = Theme(
            name=new_name,
            display_name=new_display_name,
            description=f"На основе {source.display_name}",
            is_builtin=False,
            palette=ColorPalette(**{
                k: getattr(source.palette, k)
                for k in ColorPalette.__dataclass_fields__
            }),
        )
        return new_theme

    # ============================================================
    #  Подписка на изменения
    # ============================================================
    def on_change(self, callback):
        """Регистрирует callback, который вызывается при смене темы."""
        self._on_change_callbacks.append(callback)


# ============================================================
#  Глобальный синглтон
# ============================================================
theme_manager = ThemeManager()