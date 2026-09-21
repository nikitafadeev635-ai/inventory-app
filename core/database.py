import pymysql
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT

class Database:
    _instance = None
    _conn = None

    @classmethod
    def get_connection(cls):
        if cls._instance is None:
            cls._instance = cls()
        if cls._conn is None:
            cls._connect()
        else:
            try:
                cls._conn.ping(reconnect=True)
            except Exception:
                cls._connect()
        return cls._conn

    @classmethod
    def _connect(cls):
        cls._conn = pymysql.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
            database=DB_NAME, port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            charset="utf8mb4", autocommit=True, connect_timeout=5,
        )

    @classmethod
    def close(cls):
        if cls._conn:
            cls._conn.close()
            cls._conn = None


# ============================================================
#  СОТРУДНИКИ
# ============================================================
def search_employees(query: str) -> list:
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT faname FROM employees WHERE faname LIKE %s ORDER BY faname LIMIT 50",
                        (f"%{query}%",))
            return [row['faname'] for row in cur.fetchall()]
    except pymysql.MySQLError:
        Database._connect()
        return search_employees(query)


def verify_employee(faname: str, password: str) -> bool:
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password FROM employees WHERE faname = %s", (faname,))
            row = cur.fetchone()
            return bool(row) and row['password'] == password
    except pymysql.MySQLError:
        Database._connect()
        return verify_employee(faname, password)


# ============================================================
#  ТАБЛИЦЫ ТОВАРОВ ПО ТОЧКАМ
# ============================================================
# Маппинг: название точки → имя таблицы
POINT_TABLE_MAP = {
    "Русская": "products_russkaya",
    "Трамвайная": "products_tramvaynaya",
    "Ульяновская": "products_ulyanovskaya",
    "Сахалинская": "products_sahalinskaya",
    "Светланская": "products_svetlanskaya",
    "Калинина": "products_kalinina",
}


def get_products_table(point_name: str) -> str:
    """Возвращает имя таблицы товаров для точки."""
    return POINT_TABLE_MAP.get(point_name, "products_russkaya")


def upsert_products(point_name: str, products: list):
    """
    Вставляет/обновляет товары в таблицу точки.
    products: [{"id": int, "title": str, "cost": float}, ...]
    """
    table = get_products_table(point_name)
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            sql = f"""
                INSERT INTO `{table}` (product_id, title, cost)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE title = VALUES(title), cost = VALUES(cost)
            """
            data = [(p["id"], p["title"], p.get("cost", 0)) for p in products]
            cur.executemany(sql, data)
            conn.commit()
            print(f"[DB] ✓ Upsert {len(data)} товаров в {table}")
    except pymysql.MySQLError as e:
        print(f"[DB] ✗ Ошибка upsert: {e}")
        Database._connect()


def get_product_by_id(point_name: str, product_id: int) -> dict:
    """Получает товар по ID из таблицы точки."""
    table = get_products_table(point_name)
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM `{table}` WHERE product_id = %s", (product_id,))
            return cur.fetchone()
    except pymysql.MySQLError:
        Database._connect()
        return None


# ============================================================
#  ОПЕРАЦИИ ИНВЕНТАРИЗАЦИИ (ЛОГ)
# ============================================================
def insert_operation(data: dict):
    """
    Вставляет запись в inventory_operations.
    data: {operation_date, point_name, administrator, product_id,
           product_title, quantity, cost, operation_type, reason, session_label}
    """
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO inventory_operations 
                (operation_date, point_name, administrator, product_id, 
                 product_title, quantity, cost, operation_type, reason, session_label)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cur.execute(sql, (
                data["operation_date"],
                data["point_name"],
                data["administrator"],
                data["product_id"],
                data["product_title"],
                data["quantity"],
                data.get("cost"),
                data["operation_type"],
                data["reason"],
                data.get("session_label", ""),
            ))
            conn.commit()
    except pymysql.MySQLError as e:
        print(f"[DB] ✗ Ошибка insert operation: {e}")
        Database._connect()


def insert_operations_batch(operations: list):
    """Массовая вставка операций."""
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO inventory_operations 
                (operation_date, point_name, administrator, product_id, 
                 product_title, quantity, cost, operation_type, reason, session_label)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            data = [(
                op["operation_date"], op["point_name"], op["administrator"],
                op["product_id"], op["product_title"], op["quantity"],
                op.get("cost"), op["operation_type"], op["reason"],
                op.get("session_label", ""),
            ) for op in operations]
            cur.executemany(sql, data)
            conn.commit()
            print(f"[DB] ✓ Записано {len(data)} операций")
    except pymysql.MySQLError as e:
        print(f"[DB] ✗ Ошибка batch insert: {e}")
        Database._connect()


def get_operations_by_session(session_label: str) -> list:
    """Получает все операции по метке сессии."""
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM inventory_operations WHERE session_label = %s ORDER BY operation_type, product_title",
                (session_label,)
            )
            return cur.fetchall()
    except pymysql.MySQLError:
        Database._connect()
        return []