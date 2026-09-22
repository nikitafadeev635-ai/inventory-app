#!/usr/bin/env python3
"""
Сброс пароля сотрудника.
Использование: python reset_password.py
"""
import os
import sys
import pymysql
import bcrypt
import getpass
from pathlib import Path

# Загружаем переменные окружения
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

# Параметры подключения к БД
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', '3306')),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'inventory'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}

def reset_password():
    print("=" * 60)
    print("🔑 Сброс пароля сотрудника")
    print("=" * 60)
    
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Показываем список сотрудников
        cursor.execute("SELECT id, faname FROM employees ORDER BY faname")
        employees = cursor.fetchall()
        
        print("\n📋 Список сотрудников:")
        for i, emp in enumerate(employees, 1):
            print(f"  {i}. {emp['faname']}")
        
        # Ввод данных
        faname = input("\n👤 ФИО сотрудника (или номер из списка): ").strip()
        
        # Если ввели номер — преобразуем в ФИО
        if faname.isdigit():
            idx = int(faname) - 1
            if 0 <= idx < len(employees):
                faname = employees[idx]['faname']
                print(f"   Выбрано: {faname}")
            else:
                print("❌ Неверный номер")
                return 1
        
        # Проверяем что сотрудник существует
        cursor.execute("SELECT id FROM employees WHERE faname = %s", (faname,))
        row = cursor.fetchone()
        if not row:
            print(f"❌ Сотрудник '{faname}' не найден в БД")
            return 1
        
        # Ввод нового пароля
        new_password = getpass.getpass("🔑 Новый пароль: ")
        if not new_password:
            print("❌ Пароль не может быть пустым")
            return 1
        
        new_password_confirm = getpass.getpass("🔑 Повторите пароль: ")
        if new_password != new_password_confirm:
            print("❌ Пароли не совпадают")
            return 1
        
        # Хеширование пароля
        hashed = bcrypt.hashpw(
            new_password.encode('utf-8'),
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')
        
        # Обновление в БД
        cursor.execute(
            "UPDATE employees SET password = %s WHERE faname = %s",
            (hashed, faname)
        )
        conn.commit()
        
        print(f"\n✅ Пароль обновлён для {faname}")
        print(f"   Новый пароль: {new_password}")
        print(f"   Хеш: {hashed[:50]}...")
        
        cursor.close()
        conn.close()
        return 0
        
    except pymysql.Error as e:
        print(f"\n❌ Ошибка БД: {e}")
        print("\n💡 Проверьте переменные в .env:")
        print(f"   DB_HOST={DB_CONFIG['host']}")
        print(f"   DB_USER={DB_CONFIG['user']}")
        print(f"   DB_NAME={DB_CONFIG['database']}")
        return 1
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(reset_password())