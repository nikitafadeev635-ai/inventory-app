import pymysql
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT

EMPLOYEES_DATA = [
    ("Фролов Глеб", "@npc_ceo", "rCRTeOjNauCKYjlf1Lf7"),
    ("Бондарчук Алина", "@chfuldlgx", "8yeOnWCzHdLYPxEWMvOW"),
    ("Павлов Кирилл", "@runduk0", "LEnfvqhXdE5myNg21Vse"),
    ("Александрова Александра", "@irenis02", "nfvqhXdE5myNg21Vs"),
    ("Смолина Ася", "@petterr_parrker", "gMhBBYkrGDmRjjmUpk5U"),
    ("Маун Алексей", "@Alekseijbum", "alexmaun"),
    ("Сиразеев Тимур", "@atekumba", "Zbc1IS80kXofnhdcFSKj"),
    ("Чужаков Евгений", "@awgeprince", "crockodilezhenya0231"),
    ("Шкляр Тимофей", "@Say_itme", "tvG688ruxS0gExQGVCAM"),
    ("Тетрятник Денис", "@poluchishpak", "uQCYbtmqF0B98lHpDVai"),
    ("Зубков Андрей", "@quazawer", "ySCNRwzKyjS4WEwR6wA7"),
    ("Каменев Анатолий", "@tol_a1", "pS1U1ZebAFUoWzIuRYah"),
    ("Гутарь Валерий", "@yeyosharm", "XTzbAtc5CaovUv8cqhUh"),
    ("Комлев Артем", "@tortpwnz", "LCsG2gjai6yGrhjPaDi6"),
    ("Переладов Илья", "@Blackscorpionsk", "KlXSHjX12tuP0V1GZObu"),
    ("Синявский Никита", "@Nelp_Flypper", "WhNFAda1P8FezVREE8aA"),
    ("Шпорт Нина", "@ohshitlmao", "bankashprotov"),
    ("Солоиденко Иван", "@Angel62623", "JdC5YwbzlApjAhO2hPAi"),
    ("Лавров Андрей", "@tBsj7Trdx7kskj", "BIFryKhZ7agSPcEeUiAS"),
    ("Романов Александр", "@sora_extzeee", "JX1iCKeRBAhUFeumADLx"),
    ("Гончар Виталий", "@cNOBGG", "jyZSbIt3I1mbPRnYfUYk"),
    ("Шушеначев Кирилл", "@anumkaw", "7yertr31ea5f3w33qx"),
    ("Ефремова Алина", "@EkAfire", "V90UIKBDDIJsZbK3b4w2"),
    ("Кочетов Кирилл", "@tnext66", "I4PsAacdxxHSKhHEuVqi"),
    ("Михеев Сергей", "@vabalabadabd", "SWgqrcEMOUAom1JMT3HJ"),
    ("Фадеев Никита", "@Clevmore", "jeZs56WBe4RgOSepCPnG"),
    ("Мокроусов Егор", "@illuminati1213", "5WLRrrKLeaJ3dOZ11CUi"),
    ("Коньков Андрей", "@Zhbanovv0", "5gLRrr31eafee3we1qwe"),
]


def seed():
    print("Подключение к MySQL...")
    conn = pymysql.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, port=DB_PORT, charset="utf8mb4"
    )
    cur = conn.cursor()

    # 1. Создание таблицы
    print("Создание таблицы employees...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INT AUTO_INCREMENT PRIMARY KEY,
            faname VARCHAR(255) NOT NULL UNIQUE,
            tg_teg VARCHAR(100),
            password VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # 2. Наполнение данными (с игнорированием дубликатов)
    print(f"Добавление {len(EMPLOYEES_DATA)} сотрудников...")
    sql = """
        INSERT IGNORE INTO employees (faname, tg_teg, password) 
        VALUES (%s, %s, %s)
    """
    cur.executemany(sql, EMPLOYEES_DATA)
    conn.commit()
    
    inserted = cur.rowcount
    print(f"Готово! Добавлено новых записей: {inserted}.")
    
    cur.close()
    conn.close()


if __name__ == "__main__":
    seed()