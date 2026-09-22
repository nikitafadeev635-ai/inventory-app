#!/usr/bin/env python3
"""
Миграция паролей сотрудников с plaintext на bcrypt.
Запуск: python migrate_passwords.py
"""
import os
import sys
import pymysql
import bcrypt
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

def migrate_passwords():
    """Хеширует все plaintext пароли в таблице employees."""
    print("=" * 60)
    print("🔐 Миграция паролей на bcrypt")
    print("=" * 60)
    
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Получаем всех сотрудников
        cursor.execute("SELECT id, faname, password FROM employees")
        employees = cursor.fetchall()
        
        print(f"\n📊 Найдено сотрудников: {len(employees)}")
        
        migrated = 0
        skipped = 0
        failed = 0
        
        for emp in employees:
            emp_id = emp['id']
            faname = emp['faname']
            password = emp['password']
            
            # Проверяем, уже ли пароль захеширован
            if password.startswith('$2b$') or password.startswith('$2a$') or password.startswith('$2y$'):
                print(f"  ⏭️  {faname}: уже захеширован")
                skipped += 1
                continue
            
            # Хешируем пароль
            try:
                hashed = bcrypt.hashpw(
                    password.encode('utf-8'),
                    bcrypt.gensalt(rounds=12)
                ).decode('utf-8')
                
                # Обновляем в БД
                cursor.execute(
                    "UPDATE employees SET password = %s WHERE id = %s",
                    (hashed, emp_id)
                )
                conn.commit()
                
                print(f"  ✅ {faname}: мигрирован ({len(password)} → {len(hashed)} символов)")
                migrated += 1
                
            except Exception as e:
                print(f"  ❌ {faname}: ошибка - {e}")
                failed += 1
        
        print("\n" + "=" * 60)
        print(f"📈 Результаты:")
        print(f"  ✅ Мигрировано: {migrated}")
        print(f"  ⏭️  Пропущено (уже хеш): {skipped}")
        print(f"  ❌ Ошибок: {failed}")
        print("=" * 60)
        
        # Проверка результата
        if migrated > 0:
            print("\n🔍 Проверка хешей:")
            cursor.execute("SELECT faname, LEFT(password, 20) as hash_preview FROM employees LIMIT 5")
            for row in cursor.fetchall():
                print(f"  {row['faname']}: {row['hash_preview']}...")
        
        cursor.close()
        conn.close()
        
        if migrated > 0:
            print("\n✅ Миграция завершена успешно!")
            print("⚠️  Важно: перезапустите сервис qfact-api для применения изменений")
        else:
            print("\nℹ️  Все пароли уже захешированы, миграция не требуется")
        
        return 0
        
    except pymysql.Error as e:
        print(f"\n❌ Ошибка подключения к БД: {e}")
        print("\n💡 Проверьте переменные в .env:")
        print(f"   DB_HOST={DB_CONFIG['host']}")
        print(f"   DB_PORT={DB_CONFIG['port']}")
        print(f"   DB_USER={DB_CONFIG['user']}")
        print(f"   DB_NAME={DB_CONFIG['database']}")
        return 1
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(migrate_passwords())