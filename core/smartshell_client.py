"""
SmartShell GraphQL клиент.

⚠️ В PRODUCTION этот клиент НЕ используется напрямую — все запросы идут
через серверный прокси (ApiClient), где хранятся мастер-кредами.

Этот модуль оставлен для:
- Обратной совместимости с типизацией в других модулях
- Локальной отладки (если задать переменные окружения)

Секреты читаются ТОЛЬКО из переменных окружения / .env файла,
никогда не захардкожены в коде.
"""
import os
import threading
import time
import json
from pathlib import Path

import requests

# ============================================================
#  ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ============================================================
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv не установлен — работаем с os.environ

# Публичные настройки (не секреты)
from config import SMARTSHELL_GRAPHQL_URL, RATE_LIMIT_DELAY, SMARTSHELL_WAREHOUSE_IDS

# Секретные креды — ТОЛЬКО из переменных окружения.
# В production они отсутствуют на клиенте (живут только на VPS).
SMARTSHELL_LOGIN = os.getenv("SMARTSHELL_LOGIN", "")
SMARTSHELL_PASSWORD = os.getenv("SMARTSHELL_PASSWORD", "")


class SmartShellClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._token = None
        self._last_request_ts = 0
        self._rate_lock = threading.Lock()

    def login(self, point_name: str) -> bool:
        """Получает токен для конкретной точки (прямой режим, для отладки)."""
        company_id = SMARTSHELL_WAREHOUSE_IDS.get(point_name)
        if not company_id:
            print(f"[SmartShell] Неизвестная точка: {point_name}")
            return False

        if not SMARTSHELL_LOGIN or not SMARTSHELL_PASSWORD:
            print("[SmartShell] ⚠ Мастер-кредами не заданы (SMARTSHELL_LOGIN/SMARTSHELL_PASSWORD)")
            print("[SmartShell]    Используй ApiClient (серверный прокси) для production.")
            return False

        query = """
        mutation login {
            login(input: {
                login: "%s"
                password: "%s"
                company_id: %d
            }) {
                access_token
            }
        }
        """ % (SMARTSHELL_LOGIN, SMARTSHELL_PASSWORD, company_id)

        payload = {
            "operationName": "login",
            "query": query,
            "variables": {}
        }

        self._rate_limit()
        try:
            r = self.session.post(SMARTSHELL_GRAPHQL_URL, json=payload, timeout=15)
            r.raise_for_status()
            resp = r.json()
            if resp and "data" in resp and resp["data"].get("login"):
                self._token = resp["data"]["login"].get("access_token")
                if self._token:
                    self.session.headers["Authorization"] = f"Bearer {self._token}"
                    print(f"[SmartShell] ✓ Авторизация для '{point_name}' (company_id={company_id})")
                    return True
            print("[SmartShell] ✗ Токен не получен")
            if resp and "errors" in resp:
                for e in resp["errors"]:
                    print(f"  - {e.get('message', '')}")
        except Exception as e:
            print(f"[SmartShell] ошибка логина: {e}")
        return False

    def _rate_limit(self):
        with self._rate_lock:
            now = time.time()
            delta = now - self._last_request_ts
            if delta < RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY - delta)
            self._last_request_ts = time.time()

    def fetch_goods(self, search: str = ""):
        """
        Запрос товаров.
        Склад определяется токеном (получен при логине с company_id).
        """
        query = """query goods($input: GoodsInput) {
  goods(input: $input) {
    id
    title
    cost
    wholesale_cost
    amount
    eans
    vat
    use_global_discounts
    use_fair_sign
    comment
    is_excise
    category {
      id
      company_id
      title
      show_in_shell
      __typename
    }
    show_in_shell
    image
    in_combo
    low_stock_notification {
      enabled
      threshold
      __typename
    }
    highlighted
    __typename
  }
}"""

        input_vars = {}
        if search:
            input_vars["title_search"] = search

        payload = {
            "operationName": "goods",
            "query": query,
            "variables": {"input": input_vars}
        }

        self._rate_limit()
        try:
            r = self.session.post(SMARTSHELL_GRAPHQL_URL, json=payload, timeout=15)

            if r.status_code != 200:
                print(f"[SmartShell] HTTP {r.status_code}")
                print(f"  Request payload: {json.dumps(payload, ensure_ascii=False)[:300]}")
                print(f"  Response: {r.text[:500]}")
                return []

            resp = r.json()

            if "errors" in resp:
                print(f"[SmartShell] GraphQL ошибки:")
                for e in resp["errors"]:
                    print(f"  - {e.get('message', '')}")
                return []

            goods = resp.get("data", {}).get("goods", [])
            print(f"[SmartShell] ✓ Получено товаров: {len(goods)}" +
                  (f" (поиск: '{search}')" if search else ""))
            return goods

        except Exception as e:
            print(f"[SmartShell] ошибка запроса: {e}")
            return []

    # ============================================================
    #  НОРМАЛИЗАЦИЯ: списание (DISPOSAL) и внесение (ADD)
    # ============================================================
    def change_goods_quantity(self, items: list, operation: str) -> bool:
        """
        Изменяет количество товаров в SmartShell.

        Args:
            items: [{"id": product_id, "quantity": N}, ...]
            operation: "DISPOSAL" (списание) или "ADD" (внесение)

        Returns:
            True если успешно, False если ошибка.
        """
        query = """mutation changeGoodsQuantity($input: ChangeGoodsQuantityInput!) {
  changeGoodsQuantity(input: $input)
}"""
        variables = {
            "input": {
                "items": items,
                "operation": operation
            }
        }

        payload = {
            "operationName": "changeGoodsQuantity",
            "query": query,
            "variables": variables
        }

        self._rate_limit()
        try:
            r = self.session.post(SMARTSHELL_GRAPHQL_URL, json=payload, timeout=15)

            if r.status_code != 200:
                print(f"[SmartShell] ✗ changeGoodsQuantity HTTP {r.status_code}: {r.text[:300]}")
                return False

            resp = r.json()
            if "errors" in resp:
                for e in resp["errors"]:
                    print(f"[SmartShell] ✗ {e.get('message', '')}")
                return False

            print(f"[SmartShell] ✓ {operation}: {len(items)} позиций обработано")
            return True

        except Exception as e:
            print(f"[SmartShell] ✗ Ошибка changeGoodsQuantity: {e}")
            return False

    def change_goods_single(self, product_id: int, quantity: int, operation: str) -> bool:
        """Удобная обёртка для изменения количества одного товара."""
        return self.change_goods_quantity(
            items=[{"id": product_id, "quantity": quantity}],
            operation=operation
        )