"""
Группировщик товаров по брендам/производителям.

Извлекает "базовое имя" из полного названия товара и объединяет
варианты одного бренда в группу.

Примеры:
    "HQD Apple Juice"      → "HQD"
    "Флеш Ягоды"           → "Флеш"
    "Добрый Кола 1л"       → "Добрый"
    "Red Bull Energy 250"  → "Red Bull"
"""
import re
from typing import List, Dict
from items.product import Product
from core.product_group import ProductGroup


KNOWN_BRANDS = {
    # === ДВУХСЛОВНЫЕ БРЕНДЫ (приоритет) ===
    r'\bКитайская\s*Кола\b': 'Китайская Кола',  # ← ДОБАВИТЬ
    r'\bРед\s*Булл\b': 'Ред Булл',
    r'\bLet\'?s\s*Be\b': "Let's Be",
    r'\bГорячая\s*Штучка\b': 'Горячая Штучка',
    r'\bБона\s*Аква\b': 'Бона Аква',
    r'\bФанки\s*Манки\b': 'Фанки Манки',
    r'\bЛит\s*Энерджи\b': 'Лит Энерджи',
    r'\bДобрый\s*Кола\b': 'Добрый Кола',
    r'\bДобрый\s*Палпи\b': 'Добрый Палпи',
    r'\bДоширак\s*Лапша\b': 'Доширак Лапша',
    r'\bДоширак\s*Пюре\b': 'Доширак Пюре',
    r'\bФруктовый\s*Сад\b': 'Фруктовый Сад',
    r'\bМоя\s*Семья\b': 'Моя Семья',
    r'\bRed\s*Bull\b': 'Red Bull',
    r'\bAdrenaline\s*Rush\b': 'Adrenaline Rush',
    r'\bLost\s*Mary\b': 'Lost Mary',
    r'\bElf\s*Bar\b': 'Elf Bar',
    r'\bPuff\s*Bar\b': 'Puff Bar',
    r'\bCoca[-\s]?Cola\b': 'Coca-Cola',
    
    # === ЭЛЕКТРОНКИ / ВЕЙПЫ ===
    r'\bHQD\b': 'HQD',
    r'\bIget\b': 'Iget',
    r'\bVozol\b': 'Vozol',
    
    # === ЭНЕРГЕТИКИ ===
    r'\bMonster\b': 'Monster',
    r'\bFlash\b': 'Flash',
    r'\bФлеш\b': 'Флеш',
    r'\bBurn\b': 'Burn',
    r'\bTornado\b': 'Tornado',
    r'\bGorilla\b': 'Gorilla',
    r'\bГорилла\b': 'Горилла',
    r'\bАдреналин\b': 'Адреналин',
    r'\bБерн\b': 'Берн',
    r'\bВольт\b': 'Вольт',
    r'\bВулкан\b': 'Вулкан',
    r'\bЛит\s*Энерджи\b': 'Лит Энерджи',
    
    # === СОКИ / НАПИТКИ ===
    r'\bДобрый\b': 'Добрый',  # fallback если не "Добрый Кола" или "Добрый Палпи"
    r'\bRich\b': 'Rich',
    r'\bJ7\b': 'J7',
    r'\bЛюбимый\b': 'Любимый',
    r'\bЛиптон\b': 'Липтон',
    r'\bМилкис\b': 'Милкис',
    r'\bНатахтари\b': 'Натахтари',
    r'\bГринк\b': 'Гринк',
    
    # === КОЛА / ГАЗИРОВКИ ===
    r'\bPepsi\b': 'Pepsi',
    r'\bSprite\b': 'Sprite',
    r'\bFanta\b': 'Fanta',
    r'\bБона\b': 'Бона',
    
    # === ЕДА / СНЕКИ ===
    r'\bДоширак\b': 'Доширак',  # fallback если не "Доширак Лапша" или "Доширак Пюре"
    r'\bLays\b': 'Lays',
    r'\bPringles\b': 'Pringles',
    r'\bDoritos\b': 'Doritos',
    r'\bCheetos\b': 'Cheetos',
    r'\bЛейз\b': 'Лейз',
    r'\bСникерс\b': 'Сникерс',
    r'\bМарс\b': 'Марс',
    r'\bБаунти\b': 'Баунти',
    r'\bТвикс\b': 'Твикс',
    r'\bПеперо\b': 'Пеперо',
    r'\bЗавертон\b': 'Завертон',
    r'\bЧебуречище\b': 'Чебуречище',
    r'\bШаурма\b': 'Шаурма',
    r'\bСендвич\b': 'Сендвич',
    
    # === СЛАДОСТИ ===
    r'\bЧупа[-\s]?[Чч]упс\b': 'Чупа-Чупс',  # универсально: и Чупа-Чупс, и Чупа-чупс
    r'\bЗебра\b': 'Зебра',
    r'\bЭскимо\b': 'Эскимо',
    r'\bЛесная\b': 'Лесная',
    
    # === БРЕНДЫ СО СПЕЦСИМВОЛАМИ ===
    r"\bM&M's\b": "M&M's",
    r"\bO'?zera\b": "O'zera",
}


def extract_brand_name(title: str) -> str:
    """
    Извлекает имя бренда из полного названия товара.
    
    Алгоритм:
    1. Ищем совпадение со словарём KNOWN_BRANDS (приоритет)
    2. Если не нашли — берём первые 1-2 слова как fallback
    
    Args:
        title: полное название (например, "HQD Apple Juice 5000 puffs")
    
    Returns:
        Имя бренда (например, "HQD")
    """
    if not title:
        return "Без бренда"
    
    # 1. Приоритетный поиск по словарю
    for pattern, brand_name in KNOWN_BRANDS.items():
        if re.search(pattern, title, re.IGNORECASE):
            return brand_name
    
    # 2. Fallback: эвристика по первым словам
    # Разбиваем на слова, игнорируя объёмы и числа
    words = re.split(r'\s+', title.strip())
    
    # Убираем слова-числа и объёмы (250ml, 1л, 5000, и т.д.)
    clean_words = []
    for w in words:
        # Пропускаем слова с цифрами или единицами измерения
        if re.match(r'^\d', w):
            continue
        if re.match(r'^(ml|l|г|кг|мл|л|puffs|шт|pack)$', w, re.IGNORECASE):
            continue
        clean_words.append(w)
    
    if not clean_words:
        return title.split()[0] if title.split() else "Без бренда"
    
    # Берём первое слово + второе если первое короткое (<4 букв)
    if len(clean_words[0]) < 4 and len(clean_words) > 1:
        return f"{clean_words[0]} {clean_words[1]}"
    
    return clean_words[0]


def group_products(products: List[Product]) -> List[ProductGroup]:
    """
    Группирует товары по брендам.
    
    Args:
        products: список товаров из SmartShell
    
    Returns:
        Список ProductGroup, отсортированный по имени бренда
    """
    groups_dict: Dict[str, ProductGroup] = {}
    
    for product in products:
        brand = extract_brand_name(product.title)
        
        if brand not in groups_dict:
            groups_dict[brand] = ProductGroup(name=brand)
        
        groups_dict[brand].products.append(product)
    
    # Сортируем товары внутри каждой группы
    for group in groups_dict.values():
        group.sort_products()
    
    # Сортируем группы по имени
    groups = sorted(groups_dict.values(), key=lambda g: g.name.lower())
    
    print(f"[Grouper] ✓ Сгруппировано {len(products)} товаров в {len(groups)} брендов")
    return groups


def find_group_by_product(groups: List[ProductGroup], product_id: int) -> ProductGroup:
    """Находит группу, содержащую товар с заданным ID."""
    for group in groups:
        for p in group.products:
            if p.id == product_id:
                return group
    return None


def get_brand_stats(groups: List[ProductGroup]) -> Dict[str, int]:
    """Возвращает статистику по брендам (для отладки)."""
    return {g.name: len(g.products) for g in groups}