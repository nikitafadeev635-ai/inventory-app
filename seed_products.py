"""
Скрипт создания таблиц товаров по точкам + таблицы операций.
Запускать один раз: python seed_products.py
"""
import pymysql
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT
from core.database import POINT_TABLE_MAP


def create_tables():
    print("Подключение к MySQL...")
    conn = pymysql.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, port=DB_PORT, charset="utf8mb4"
    )
    cur = conn.cursor()

    # === Таблицы товаров по точкам ===
    for point_name, table_name in POINT_TABLE_MAP.items():
        print(f"  Создание таблицы {table_name}...")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS `{table_name}` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                product_id INT NOT NULL UNIQUE,
                title VARCHAR(500) NOT NULL,
                cost DECIMAL(10, 2) DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_product_id (product_id),
                INDEX idx_title (title(255))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

    # === Таблица операций ===
    print("  Создание таблицы inventory_operations...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_operations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            operation_date DATETIME NOT NULL,
            point_name VARCHAR(100) NOT NULL,
            administrator VARCHAR(255) NOT NULL,
            product_id INT NOT NULL,
            product_title VARCHAR(500) NOT NULL,
            quantity INT NOT NULL,
            cost DECIMAL(10, 2) DEFAULT NULL,
            operation_type ENUM('DISPOSAL', 'ADD') NOT NULL,
            reason VARCHAR(500) DEFAULT '',
            session_label VARCHAR(500) DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_date (operation_date),
            INDEX idx_point (point_name),
            INDEX idx_admin (administrator(100)),
            INDEX idx_session (session_label(255)),
            INDEX idx_type (operation_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("\n✅ Все таблицы созданы успешно!")
    print(f"   Таблицы товаров: {', '.join(POINT_TABLE_MAP.values())}")
    print(f"   Таблица операций: inventory_operations")


if __name__ == "__main__":
    create_tables()