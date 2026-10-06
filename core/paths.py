"""
Управление путями в приложении.
Корректно работает и в режиме разработки (.py), и в собранном режиме (.exe).

Принцип работы:
- В режиме разработки: base_dir = корень проекта
- В режиме .exe: base_dir = папка где лежит .exe
- bundle_dir: временная папка PyInstaller (для встроенных ресурсов)

Все внешние данные (отчёты, темы, конфиги) хранятся рядом с .exe,
а не во временной папке, которая удаляется при закрытии приложения.
"""
import sys
import os
from pathlib import Path


def is_frozen() -> bool:
    """Проверяет, запущено ли приложение как .exe (PyInstaller)"""
    return getattr(sys, 'frozen', False)


def get_base_dir() -> Path:
    """
    Возвращает базовую директорию приложения.
    - В режиме разработки: папка проекта (где лежит main.py)
    - В режиме .exe: папка где лежит inventory_app.exe
    """
    if is_frozen():
        # PyInstaller: sys.executable — путь к самому .exe
        return Path(sys.executable).parent
    else:
        # Разработка: поднимаемся на уровень от core/ к корню проекта
        return Path(__file__).parent.parent


def get_bundle_dir() -> Path:
    """
    Возвращает директорию с внутренними ресурсами бандла.
    Используется ТОЛЬКО для ресурсов, упакованных внутрь .exe
    через --add-data при сборке PyInstaller.
    """
    if is_frozen():
        # PyInstaller распаковывает --add-data ресурсы в sys._MEIPASS
        return Path(sys._MEIPASS)
    else:
        # В режиме разработки — это корень проекта
        return Path(__file__).parent.parent


# ============================================================
#  ВНЕШНИЕ ДИРЕКТОРИИ (создаются автоматически рядом с .exe)
# ============================================================

def get_assets_dir() -> Path:
    """Картинки фона, GIF-анимации и другие внешние ресурсы"""
    path = get_base_dir() / "assets"
    path.mkdir(exist_ok=True)
    return path


def get_reports_dir() -> Path:
    """Сохранённые PDF-отчёты по нормализации"""
    path = get_base_dir() / "reports"
    path.mkdir(exist_ok=True)
    return path


def get_themes_dir() -> Path:
    """Пользовательские темы (user_themes/*.json)"""
    path = get_base_dir() / "user_themes"
    path.mkdir(exist_ok=True)
    return path


def get_mapping_dir() -> Path:
    """Маппинг товаров по точкам (mapping/*.json)"""
    path = get_base_dir() / "mapping"
    path.mkdir(exist_ok=True)
    return path


def get_logs_dir() -> Path:
    """Логи приложения"""
    path = get_base_dir() / "logs"
    path.mkdir(exist_ok=True)
    return path


def get_cache_dir() -> Path:
    """Кеш данных (goods_cache и др.)"""
    path = get_base_dir() / "cache"
    path.mkdir(exist_ok=True)
    return path


# ============================================================
#  КОНКРЕТНЫЕ ФАЙЛЫ
# ============================================================

def get_point_lock_path() -> Path:
    """Файл привязки точки (point.lock)"""
    return get_base_dir() / "point.lock"


def get_env_path() -> Path:
    """Файл конфигурации .env"""
    return get_base_dir() / ".env"


def get_background_gif_path() -> Path:
    """Файл фоновой GIF-анимации"""
    return get_base_dir() / "background.gif"


# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_asset_path(filename: str) -> Path:
    """
    Получает путь к ресурсу (картинка, шрифт и т.п.).
    
    Приоритет:
    1. Внешняя папка assets/ рядом с .exe (можно менять)
    2. Встроенный бандл (--add-data при сборке)
    3. Fallback на внешний путь
    """
    # 1. Внешний путь (приоритет — пользователь может заменять файлы)
    external = get_assets_dir() / filename
    if external.exists():
        return external
    
    # 2. Встроенный в бандл
    bundled = get_bundle_dir() / "assets" / filename
    if bundled.exists():
        return bundled
    
    # 3. Fallback (даже если не существует)
    return external


def get_font_path(filename: str = "arial.ttf") -> Path:
    """
    Получает путь к шрифту.
    Сначала ищет рядом с .exe, потом в системных шрифтах.
    """
    # 1. Рядом с .exe (в папке fonts/)
    local = get_base_dir() / "fonts" / filename
    if local.exists():
        return local
    
    # 2. В бандле
    bundled = get_bundle_dir() / "fonts" / filename
    if bundled.exists():
        return bundled
    
    # 3. Системные шрифты Windows
    windir = os.environ.get('WINDIR', r'C:\Windows')
    system = Path(windir) / "Fonts" / filename
    if system.exists():
        return system
    
    # 4. Fallback
    return local


def get_theme_path(theme_name: str) -> Path:
    """Получает путь к файлу пользовательской темы"""
    return get_themes_dir() / f"{theme_name}.json"


def get_mapping_path(point_name: str) -> Path:
    """Получает путь к файлу маппинга точки"""
    return get_mapping_dir() / f"{point_name}.json"


# ============================================================
#  ДИАГНОСТИКА (для отладки)
# ============================================================

def print_paths_info():
    """Выводит информацию о путях — полезно для отладки"""
    print("=" * 60)
    print("📂 Пути приложения:")
    print(f"  Режим: {'🔧 Разработка (.py)' if not is_frozen() else '📦 Сборка (.exe)'}")
    print(f"  base_dir:   {get_base_dir()}")
    print(f"  bundle_dir: {get_bundle_dir()}")
    print(f"  reports:    {get_reports_dir()}")
    print(f"  themes:     {get_themes_dir()}")
    print(f"  point.lock: {get_point_lock_path()}")
    print(f"  .env:       {get_env_path()}")
    print("=" * 60)


# Автозапуск диагностики при импорте (в dev-режиме)
if __name__ == "__main__":
    print_paths_info()