"""
Мастер привязки точки продаж к ПК.
Использует:
- point_lock.py для работы с point.lock
- integrity_checker.py для вычисления HWID и хеша
- HTTP запросы к серверу для получения подписи

Использование:
  activate_point.exe --bind          # Интерактивный режим
  activate_point.exe --bind --point Ульяновская --master-password xxx
  activate_point.exe --info          # Показать текущую привязку
"""
import sys
import os
import httpx
import getpass
from pathlib import Path

# Добавляем путь к core модулям
sys.path.insert(0, str(Path(__file__).parent))

from core.point_lock import (
    get_hardware_id,
    save_point_lock_from_server,
    print_lock_info,
    _get_lock_file_path,
)
from core.integrity_checker import get_exe_hash
from config import PROXY_SERVER_URL, API_SECRET_KEY


# ============================================================
#  КОНСТАНТЫ
# ============================================================
AVAILABLE_POINTS = [
    "Русская",
    "Сахалинская",
    "Трамвайная",
    "Светланская",
    "Ульяновская",
    "Калинина",
]


# ============================================================
#  ИНТЕРАКТИВНЫЙ РЕЖИМ
# ============================================================
def interactive_bind():
    """Интерактивный режим привязки точки"""
    print("=" * 60)
    print("🔐 Мастер привязки точки продаж")
    print("=" * 60)
    print()
    
    # Шаг 1: Мастер-пароль
    try:
        master_password = getpass.getpass("Введите мастер-пароль: ")
    except (KeyboardInterrupt, EOFError):
        print("\n\n❌ Отменено пользователем")
        return False
    
    if not master_password:
        print("❌ Мастер-пароль не может быть пустым")
        return False
    
    # Шаг 2: Выбор точки
    print("\nДоступные точки:")
    for idx, point in enumerate(AVAILABLE_POINTS, 1):
        print(f"  {idx}. {point}")
    
    print()
    while True:
        try:
            choice = input("Выберите номер точки (1-6): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(AVAILABLE_POINTS):
                point_name = AVAILABLE_POINTS[idx]
                break
            print("❌ Неверный номер. Попробуйте снова.")
        except ValueError:
            print("❌ Введите число от 1 до 6")
        except (KeyboardInterrupt, EOFError):
            print("\n\n❌ Отменено пользователем")
            return False
    
    print(f"\n✓ Выбрана точка: {point_name}")
    
    # Шаг 3: Привязка
    return perform_binding(point_name, master_password)


# ============================================================
#  РЕАЛЬНАЯ ЛОГИКА ПРИВЯЗКИ
# ============================================================
def perform_binding(point_name: str, master_password: str) -> bool:
    """
    Выполняет привязку точки через сервер.
    
    Процесс:
    1. Вычислить HWID текущего ПК
    2. Отправить запрос на сервер с master_password
    3. Получить подпись (signature) от сервера
    4. Сохранить point.lock локально
    """
    print("\n" + "=" * 60)
    print("🔄 Выполняется привязка...")
    print("=" * 60)
    
    # Вычисляем HWID
    hwid = get_hardware_id()
    exe_hash = get_exe_hash()
    
    print(f"\n📊 Данные клиента:")
    print(f"  HWID:     {hwid[:16]}...")
    print(f"  Хеш .exe: {exe_hash[:16] if exe_hash else '—'}...")
    print(f"  Точка:    {point_name}")
    print(f"  Сервер:   {PROXY_SERVER_URL}")
    
    # Отправляем запрос на сервер
    print("\n📤 Отправка запроса на сервер...")
    
    try:
        with httpx.Client(verify=False, timeout=15) as client:
            response = client.post(
                f"{PROXY_SERVER_URL}/api/admin/bind-point",
                headers={
                    "X-API-Key": API_SECRET_KEY,
                    "X-Master-Key": master_password,  # ← Мастер-пароль как Master-Key
                    "Content-Type": "application/json",
                },
                json={
                    "point_name": point_name,
                    "hwid": hwid,
                    "exe_hash": exe_hash,
                }
            )
        
        # Обрабатываем ответ
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                signature = data["signature"]
                bound_at = data.get("bound_at")
                
                # Сохраняем point.lock
                success, message = save_point_lock_from_server(
                    point_name=point_name,
                    hwid=hwid,
                    signature=signature,
                    bound_at=bound_at
                )
                
                if success:
                    print("\n" + "=" * 60)
                    print("✅ ПРИВЯЗКА ЗАВЕРШЕНА УСПЕШНО!")
                    print("=" * 60)
                    print(f"  Точка:    {point_name}")
                    print(f"  HWID:     {hwid[:16]}...")
                    print(f"  Файл:     {_get_lock_file_path()}")
                    print()
                    print("Теперь можно запускать inventory_app.exe")
                    print("=" * 60)
                    return True
                else:
                    print(f"\n❌ Ошибка сохранения: {message}")
                    return False
            else:
                print(f"\n❌ Сервер вернул ошибку: {data}")
                return False
        
        elif response.status_code == 401:
            print("\n❌ Неверный API-Key")
            return False
        
        elif response.status_code == 403:
            print("\n❌ Неверный мастер-пароль или IP не в ADMIN_IPS")
            print(f"   Ответ сервера: {response.text[:200]}")
            return False
        
        elif response.status_code == 404:
            print(f"\n❌ Точка '{point_name}' не найдена в базе данных")
            return False
        
        else:
            print(f"\n❌ Ошибка сервера: HTTP {response.status_code}")
            print(f"   Ответ: {response.text[:200]}")
            return False
            
    except httpx.TimeoutException:
        print("\n❌ Таймаут подключения к серверу")
        return False
    except httpx.ConnectError:
        print(f"\n❌ Не удалось подключиться к серверу: {PROXY_SERVER_URL}")
        return False
    except Exception as e:
        print(f"\n❌ Ошибка: {type(e).__name__}: {e}")
        return False


# ============================================================
#  ПАРСИНГ АРГУМЕНТОВ
# ============================================================
def parse_args():
    """Разбирает аргументы командной строки"""
    args = sys.argv[1:]
    
    if not args or "--info" in args:
        return {"mode": "info"}
    
    if "--bind" in args:
        result = {"mode": "bind"}
        
        # Ищем --point
        for i, arg in enumerate(args):
            if arg == "--point" and i + 1 < len(args):
                result["point_name"] = args[i + 1]
            elif arg == "--master-password" and i + 1 < len(args):
                result["master_password"] = args[i + 1]
        
        return result
    
    if "--help" in args or "-h" in args:
        return {"mode": "help"}
    
    return {"mode": "info"}


def print_help():
    """Выводит справку"""
    print("""
🔐 Мастер привязки точки продаж
================================

Использование:
  activate_point.exe --bind                           Интерактивный режим
  activate_point.exe --bind --point Ульяновская       С указанием точки
  activate_point.exe --info                           Показать текущую привязку
  activate_point.exe --help                           Эта справка

Параметры:
  --bind                  Запустить процесс привязки
  --point <название>      Название точки (не обязательно)
  --master-password <pw>  Мастер-пароль (не рекомендуется - виден в истории)
  --info                  Показать информацию о текущей привязке
  --help, -h              Показать эту справку

Примеры:
  activate_point.exe --bind
  activate_point.exe --bind --point Ульяновская
  activate_point.exe --info
""")


# ============================================================
#  ГЛАВНАЯ ФУНКЦИЯ
# ============================================================
def main():
    args = parse_args()
    
    if args["mode"] == "help":
        print_help()
        return 0
    
    if args["mode"] == "info":
        print_lock_info()
        return 0
    
    if args["mode"] == "bind":
        # Если переданы все параметры — используем их
        if "point_name" in args and "master_password" in args:
            point_name = args["point_name"]
            master_password = args["master_password"]
            
            if point_name not in AVAILABLE_POINTS:
                print(f"❌ Неизвестная точка: {point_name}")
                print(f"   Доступные: {', '.join(AVAILABLE_POINTS)}")
                return 1
            
            success = perform_binding(point_name, master_password)
            return 0 if success else 1
        
        # Иначе — интерактивный режим
        success = interactive_bind()
        return 0 if success else 1
    
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n❌ Прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)