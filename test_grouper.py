"""
Анализ группировки товаров на РЕАЛЬНЫХ данных из SmartShell.
Анализирует ВСЕ товары, включая те, что со stock=0 (закончились).
"""
import sys
from collections import Counter
import re

from core.api_client import ApiClient
from core.product_grouper import group_products, extract_brand_name, KNOWN_BRANDS
from items.product import Product


def main():
    print("=" * 70)
    print("🔍 АНАЛИЗ ГРУППИРОВКИ ТОВАРОВ (ВСЕ товары, включая stock=0)")
    print("=" * 70)

    # === 1. Подключение к серверу ===
    print("\n📡 Подключение к серверу...")
    client = ApiClient()

    # === 2. Показать список сотрудников ===
    print("\n👥 Получение списка сотрудников...")
    employees = client.search_employees("")
    if not employees:
        print("❌ Не удалось получить список сотрудников")
        return

    print(f"\n✅ Доступно сотрудников: {len(employees)}")
    print("\nСписок:")
    for i, emp in enumerate(employees[:20], 1):
        print(f"  {i:2}. {emp}")
    if len(employees) > 20:
        print(f"  ... и ещё {len(employees) - 20}")

    # === 3. Авторизация ===
    print("\n🔐 Авторизация")
    print("Доступные точки: Русская, Сахалинская, Трамвайная, Светланская, Ульяновская, Калинина")
    point = input("Точка [Русская]: ").strip() or "Русская"
    
    print("\nВведите ФИО (из списка выше):")
    faname = input("ФИО: ").strip()
    if not faname:
        print("❌ ФИО не может быть пустым")
        return
    
    password = input("Пароль: ").strip()
    if not password:
        print("❌ Пароль не может быть пустым")
        return

    print(f"\n⏳ Авторизация: {faname} @ {point}...")
    if not client.login(faname, password, point):
        print("❌ Ошибка авторизации. Проверь ФИО и пароль.")
        return

    print(f"✅ Авторизован: {faname} @ {point}")

    # === 4. Загрузка ВСЕХ товаров (без фильтра stock>0) ===
    print("\n⏳ Загрузка ВСЕХ товаров из SmartShell...")
    raw_goods = client.fetch_goods("")
    if not raw_goods:
        print("❌ Не удалось получить товары")
        return

    all_products = [Product.from_api(g) for g in raw_goods]
    
    # Разделяем на группы для статистики
    in_stock = [p for p in all_products if p.stock > 0]
    out_of_stock = [p for p in all_products if p.stock == 0]
    
    print(f"\n📦 Статистика ассортимента:")
    print(f"   ├─ Всего товаров: {len(all_products)}")
    print(f"   ├─ В наличии (stock > 0): {len(in_stock)}")
    print(f"   └─ Закончились (stock = 0): {len(out_of_stock)}")

    # === 5. Группировка ВСЕХ товаров ===
    print("\n🔄 Группировка ВСЕХ товаров по брендам...")
    groups = group_products(all_products)

    # === 6. Анализ ===
    print("\n" + "=" * 70)
    print("📊 РЕЗУЛЬТАТЫ АНАЛИЗА (ВСЕ товары)")
    print("=" * 70)

    multi_groups = [g for g in groups if len(g.products) >= 2]
    single_groups = [g for g in groups if len(g.products) == 1]

    total_products = len(all_products)
    grouped_products = sum(len(g.products) for g in multi_groups)
    single_products = len(single_groups)

    print(f"\n🎯 Всего групп: {len(groups)}")
    print(f"   ├─ ✅ Успешно сгруппировано (2+ товаров): {len(multi_groups)} групп")
    print(f"   │     Товаров в них: {grouped_products} из {total_products}")
    print(f"   └─ ⚠️  Одиночки (1 товар): {len(single_groups)} групп")

    coverage = grouped_products / total_products * 100 if total_products > 0 else 0
    print(f"\n📈 Покрытие группировкой: {coverage:.1f}% товаров входят в группы")

    # === 7. Анализ групп с учётом наличия ===
    print("\n" + "=" * 70)
    print("📦 АНАЛИЗ ГРУПП ПО НАЛИЧИЮ")
    print("=" * 70)

    groups_with_stock = []
    groups_without_stock = []
    groups_mixed = []

    for g in multi_groups:
        in_stock_count = sum(1 for p in g.products if p.stock > 0)
        if in_stock_count == len(g.products):
            groups_with_stock.append(g)
        elif in_stock_count == 0:
            groups_without_stock.append(g)
        else:
            groups_mixed.append(g)

    print(f"\n✅ Группы полностью в наличии: {len(groups_with_stock)}")
    print(f"⚠️  Группы частично в наличии: {len(groups_mixed)}")
    print(f"❌ Группы полностью закончились: {len(groups_without_stock)}")

    # === 8. Топ групп (ВСЕ товары) ===
    print("\n" + "=" * 70)
    print("🏆 ТОП-25 ГРУПП (ВСЕ товары, включая stock=0)")
    print("=" * 70)
    multi_sorted = sorted(multi_groups, key=lambda g: len(g.products), reverse=True)
    for i, g in enumerate(multi_sorted[:25], 1):
        in_stock_count = sum(1 for p in g.products if p.stock > 0)
        total_stock = sum(p.stock for p in g.products)
        status = f"{in_stock_count}/{len(g.products)} в наличии"
        print(f"\n{i:2}. [{g.name}] — {len(g.products)} товаров ({status}, учёт: {total_stock})")
        for p in g.products[:5]:
            stock_marker = f"✓{p.stock}" if p.stock > 0 else "✗0"
            print(f"      • {p.title} ({stock_marker})")
        if len(g.products) > 5:
            print(f"      ... и ещё {len(g.products) - 5} товаров")

    # === 9. Одиночки ===
    print("\n" + "=" * 70)
    print("⚠️  ОДИНОЧКИ (не удалось сгруппировать)")
    print("=" * 70)
    print(f"Всего: {len(single_groups)} товаров\n")

    # Разделяем одиночки по наличию
    singles_in_stock = [g for g in single_groups if g.products[0].stock > 0]
    singles_out_of_stock = [g for g in single_groups if g.products[0].stock == 0]

    print(f"├─ В наличии: {len(singles_in_stock)}")
    print(f"└─ Закончились: {len(singles_out_of_stock)}\n")

    print("Одиночки В НАЛИЧИИ:")
    for i, g in enumerate(singles_in_stock[:30], 1):
        p = g.products[0]
        print(f"{i:3}. [{g.name:20}] {p.title} (stock: {p.stock})")
    if len(singles_in_stock) > 30:
        print(f"\n... и ещё {len(singles_in_stock) - 30}")

    print("\nОдиночки ЗАКОНЧИЛИСЬ:")
    for i, g in enumerate(singles_out_of_stock[:30], 1):
        p = g.products[0]
        print(f"{i:3}. [{g.name:20}] {p.title} (stock: 0)")
    if len(singles_out_of_stock) > 30:
        print(f"\n... и ещё {len(singles_out_of_stock) - 30}")

    # === 10. Анализ первых слов ===
    print("\n" + "=" * 70)
    print("🔤 АНАЛИЗ ПЕРВЫХ СЛОВ (кандидаты в бренды)")
    print("=" * 70)

    first_words = []
    two_words = []
    for p in all_products:
        words = p.title.strip().split()
        if len(words) >= 1:
            first_words.append(words[0])
        if len(words) >= 2:
            two_words.append(f"{words[0]} {words[1]}")

    print("\nТОП-40 первых слов:")
    for word, count in Counter(first_words).most_common(40):
        in_dict = any(word.lower() in pat.lower() for pat in KNOWN_BRANDS.keys())
        marker = "✓ в словаре" if in_dict else "❌ НЕТ"
        print(f"   {word:30} — {count:3} раз  {marker}")

    print("\nТОП-30 двухсловных сочетаний:")
    for phrase, count in Counter(two_words).most_common(30):
        in_dict = any(phrase.lower() in pat.lower() for pat in KNOWN_BRANDS.keys())
        marker = "✓ в словаре" if in_dict else "❌ НЕТ"
        print(f"   {phrase:35} — {count:3} раз  {marker}")

    # === 11. Рекомендации ===
    print("\n" + "=" * 70)
    print("💡 РЕКОМЕНДАЦИИ")
    print("=" * 70)
    
    print("\nДобавь в KNOWN_BRANDS (core/product_grouper.py) эти паттерны:\n")

    suggested = []
    for word, count in Counter(first_words).most_common(20):
        if count >= 2:  # встречается 2+ раз (порог снижен)
            in_dict = any(word.lower() in pat.lower() for pat in KNOWN_BRANDS.keys())
            if not in_dict and len(word) > 2:
                suggested.append((word, count))

    for word, count in suggested[:15]:
        print(f'    r"\\b{re.escape(word)}\\b": "{word}",  # {count} товаров')

    # === 12. Итоговая статистика ===
    print("\n" + "=" * 70)
    print("📋 ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 70)
    print(f"\nВсего товаров на точке: {total_products}")
    print(f"В наличии: {len(in_stock)} ({len(in_stock)/total_products*100:.1f}%)")
    print(f"Закончились: {len(out_of_stock)} ({len(out_of_stock)/total_products*100:.1f}%)")
    print(f"\nГрупп (2+ товаров): {len(multi_groups)}")
    print(f"Одиночек: {len(single_groups)}")
    print(f"Покрытие группировкой: {coverage:.1f}%")
    print(f"\n✅ Анализ завершён!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⛔ Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)