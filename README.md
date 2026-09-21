# 📦 Inventory App (QFact)

Система инвентаризации для сети магазинов CyberMG. 
Автоматизация пересменки с интеграцией SmartShell, синхронизацией с мобильным устройством, 
финансовой ответственностью и PDF-отчётами.

## 🏗️ Архитектура

```
┌─────────────────┐      ┌──────────────┐      ┌──────────────┐
│  ПК (PyQt6)     │ ───► │ VPS (FastAPI)│ ───► │  SmartShell  │
│  inventory_app  │      │ apiqfact     │      │  (GraphQL)   │
└────────┬────────┘      └──────┬───────┘      └──────────────┘
         │                       │
         │ sync_server           │
         │ (localhost:8080)      ▼
         │                 ┌──────────┐
         ▼                 │  MySQL   │
┌─────────────────┐        │  (БД)    │
│  📱 Телефон     │        └──────────┘
│  (мобильный     │
│   веб-интерфейс)│
└─────────────────┘
```

## 📁 Структура проекта

```
inventory_app/
├── main.py                         # Точка входа
├── config.py                       # Конфигурация (URL, warehouse_ids)
├── .env                            # Секреты (НЕ в Git!)
├── .env.example                    # Шаблон секретов
│
├── items/
│   └── product.py                  # Модель Product
│
├── core/                           # Ядро бизнес-логики
│   ├── session.py                  # current_session (Singleton)
│   ├── goods_cache.py              # Кеш товаров и групп
│   ├── product_group.py            # ProductGroup (группы брендов)
│   ├── product_grouper.py          # Группировка по брендам
│   ├── normalization.py            # NormalizationService (план/применение/верификация)
│   ├── normalization_verifier.py   # Верификация в SmartShell
│   ├── sync_server.py              # Локальный сервер для телефона (FastAPI)
│   ├── inventory_repository.py     # Сохранение в БД через VPS
│   ├── report_generator.py         # PDF-отчёты (ReportLab)
│   ├── database.py                 # Локальная SQLite
│   └── api_client.py               # HTTP-клиент к VPS
│
├── gui/                            # Интерфейс (PyQt6)
│   ├── inventory_window.py         # Главное окно пересчёта
│   ├── normalization_dialog.py     # План нормализации
│   ├── trouble_dialog.py           # Причины расхождений
│   ├── verification_dialog.py      # Ручная верификация
│   ├── completion_dialog.py        # Финальный чеклист
│   ├── sync_qr_dialog.py           # QR-код для телефона
│   ├── inventory_customizer.py     # Настройка темы
│   ├── styles.py                   # SmartShellColors
│   ├── themes.py                   # theme_manager
│   └── gif_background.py           # Анимированный фон
│
├── reports/                        # PDF-отчёты (не в Git)
└── docs/                           # Документация
    ├── architecture.md
    └── deployment.md
```

## 🚀 Быстрый старт

### Установка
```bash
git clone https://github.com/nikitafadeev635-ai/inventory-app.git
cd inventory-app
pip install -r requirements.txt
cp .env.example .env
# Заполни .env реальными данными
```

### Запуск
```bash
python main.py
```

## 🔐 Конфигурация (.env)

```env
SMARTSHELL_GRAPHQL_URL=https://billing.smartshell.gg/api/graphql
SS_MASTER_LOGIN=your_login
SS_MASTER_PASSWORD=your_password
PROXY_SERVER_URL=https://your-vps:8443
API_SECRET_KEY=random_string
JWT_SECRET=random_string
WAREHOUSE_RUSSKAYA=1598
WAREHOUSE_SAHALINSKAYA=3241
WAREHOUSE_TRAMVAYNAYA=2610
WAREHOUSE_SVETLAYA=7879
WAREHOUSE_ULYANOVSKAYA=4532
WAREHOUSE_KALININA=10178
```

## 📊 Ключевые возможности

- ✅ Пересчёт с группировкой по брендам
- ✅ Синхронизация с телефоном (QR-код, веб-интерфейс)
- ✅ Адаптация факта при продаже во время пересчёта
- ✅ Калькулятор в мобильном интерфейсе
- ✅ Нормализация расхождений (списание/внесение)
- ✅ TroubleDialog с причинами и ссылками
- ✅ PDF-отчёты с кириллицей
- ✅ Финансовая ответственность (к оплате / на проверке)
- ✅ Безопасное закрытие (БД → PDF → SmartShell)
- ✅ CompletionDialog с чеклистом этапов

## 🛠️ Технологии

- **Клиент:** Python 3.14, PyQt6, ReportLab
- **Сервер:** FastAPI, Uvicorn, PyMySQL, httpx
- **БД:** MySQL 8.0 (VPS), SQLite (локально)
- **Синхронизация:** FastAPI + WebSocket (локально)
- **Интеграция:** SmartShell GraphQL API

## 🔒 Безопасность

- Все секреты в `.env` (не коммитится!)
- Клиент не имеет прямого доступа к SmartShell и БД
- Все операции проксируются через VPS
- JWT аутентификация

## 📝 Версионирование

Проект использует **Semantic Versioning** + **Conventional Commits**:

- `feat:` — новая функциональность
- `fix:` — исправление бага
- `docs:` — изменения в документации
- `refactor:` — рефакторинг
- `chore:` — обслуживание

Примеры коммитов:
```bash
git commit -m "feat(sync): add client-side stock adaptation"
git commit -m "fix(ui): align columns in inventory table"
git commit -m "docs: add deployment guide"
```

## 👥 Как работать с проектом (для AI)

Если вы AI-ассистент и получаете ссылку на этот репозиторий:

1. Изучите `README.md` (этот файл)
2. Прочитайте `docs/architecture.md` для понимания связей модулей
3. Используйте `grep`/`find` для поиска конкретных функций
4. Проверяйте `CHANGELOG.md` для истории изменений

## 📄 Лицензия

Proprietary © CyberMG 2024