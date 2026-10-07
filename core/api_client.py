"""
API клиент для общения с QFact сервером (VPS).
Заменяет прямые запросы к SmartShell.
Отключает использование системного прокси для всех запросов
(чтобы избежать ProxyError на порту 8443).

v2.0 — X-Client-Hash и X-Client-HWID в заголовках КАЖДОГО запроса
"""
import requests
import urllib3

from config import PROXY_SERVER_URL, PROXY_VERIFY_SSL, PROXY_CERT_PATH, API_SECRET_KEY

# 🆕 Импорт функций для вычисления HWID и хеша .exe
try:
    from core.integrity_checker import get_exe_hash, get_hardware_id
    _INTEGRITY_AVAILABLE = True
except ImportError:
    _INTEGRITY_AVAILABLE = False
    get_exe_hash = lambda: ""
    get_hardware_id = lambda: ""


class ApiClient:
    """Клиент для работы с QFact proxy сервером."""

    def __init__(self):
        self.server_url = PROXY_SERVER_URL
        self.session = requests.Session()

        # ============================================================
        #  🆕 ВЫЧИСЛЕНИЕ HWID И HASH (один раз при инициализации)
        # ============================================================
        self._client_hash = ""
        self._client_hwid = ""

        if _INTEGRITY_AVAILABLE:
            try:
                self._client_hash = get_exe_hash() or ""
                self._client_hwid = get_hardware_id() or ""
                print(f"[API] ✓ HWID: {self._client_hwid[:16]}...")
                print(f"[API] ✓ Hash: {self._client_hash[:16]}...")
            except Exception as e:
                print(f"[API] ⚠ Ошибка вычисления HWID/Hash: {e}")
                self._client_hash = ""
                self._client_hwid = ""
        else:
            print("[API] ⚠ integrity_checker недоступен — HWID/Hash не будут отправляться")

        # ============================================================
        #  🔑 ЗАГОЛОВКИ ДЛЯ ВСЕХ ЗАПРОСОВ
        # ============================================================
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": API_SECRET_KEY,
        }

        # 🆕 Добавляем HWID и Hash в ОСНОВНУЮ сессию (для ВСЕХ запросов)
        if self._client_hash:
            headers["X-Client-Hash"] = self._client_hash
        if self._client_hwid:
            headers["X-Client-HWID"] = self._client_hwid

        # Применяем заголовки ко всем последующим запросам
        self.session.headers.update(headers)

        self._token = None

        # ============================================================
        #  ОТКЛЮЧЕНИЕ СИСТЕМНОГО ПРОКСИ
        # ============================================================
        self.session.trust_env = False
        self.session.proxies = {
            "http": None,
            "https": None,
        }

        # Для self-signed сертификатов
        if not PROXY_VERIFY_SSL:
            self.session.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print(f"[API] ⚠ SSL verification disabled (self-signed cert)")
        elif PROXY_CERT_PATH:
            self.session.verify = PROXY_CERT_PATH

    # ============================================================
    #  ВСПОМОГАТЕЛЬНЫЙ МЕТОД: заголовки для отдельной сессии
    # ============================================================
    def _get_base_headers(self) -> dict:
        """Возвращает базовые заголовки (для методов которые создают свою сессию)"""
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": API_SECRET_KEY,
        }
        if self._client_hash:
            headers["X-Client-Hash"] = self._client_hash
        if self._client_hwid:
            headers["X-Client-HWID"] = self._client_hwid
        return headers

    # ============================================================
    #  АВТОРИЗАЦИЯ
    # ============================================================
    def login(self, faname: str, password: str, point_name: str) -> bool:
        """Авторизация через сервер. Получает JWT."""
        try:
            r = self.session.post(
                f"{self.server_url}/api/auth/login",
                json={
                    "faname": faname,
                    "password": password,
                    "point_name": point_name,
                },
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                self._token = data["access_token"]
                self.session.headers["Authorization"] = f"Bearer {self._token}"
                print(f"[API] ✓ Авторизация: {faname} @ {point_name}")
                return True
            print(f"[API] ✗ Login failed: {r.status_code} — {r.text[:200]}")
            return False
        except Exception as e:
            print(f"[API] ✗ Ошибка подключения к серверу: {e}")
            return False

    # ============================================================
    #  ТОВАРЫ
    # ============================================================
    def fetch_goods(self, search: str = "") -> list:
        """Получает товары через сервер."""
        try:
            r = self.session.get(
                f"{self.server_url}/api/goods/list",
                params={"search": search},
                timeout=20,
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("goods", [])
            if r.status_code == 401:
                print("[API] ✗ Токен истёк — требуется повторная авторизация")
                return []
        except Exception as e:
            print(f"[API] ✗ fetch_goods error: {e}")
        return []

    # ============================================================
    #  СОТРУДНИКИ
    # ============================================================
    def search_employees(self, query: str = "") -> list:
        """Публичный поиск сотрудников через сервер."""
        try:
            old_auth = self.session.headers.pop("Authorization", None)
            try:
                r = self.session.post(
                    f"{self.server_url}/api/employees/search",
                    json={"query": query},
                    timeout=10,
                )
            finally:
                if old_auth:
                    self.session.headers["Authorization"] = old_auth
            if r.status_code == 200:
                return r.json().get("employees", [])
            return []
        except Exception as e:
            print(f"[API] Ошибка search_employees: {e}")
            return []

    def verify_password(self, faname: str, password: str) -> dict:
        """Проверяет пароль конкретного сотрудника БЕЗ выдачи JWT."""
        try:
            session = requests.Session()
            session.verify = False
            session.trust_env = False
            session.proxies = {"http": None, "https": None}
            session.headers.update(self._get_base_headers())
            response = session.post(
                f"{self.server_url}/api/auth/verify_password",
                json={"faname": faname, "password": password},
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                print(f"[ApiClient] verify_password({faname}): "
                      f"verified={data.get('verified')}")
                return data
            else:
                print(f"[ApiClient] ✗ HTTP {response.status_code}: {response.text}")
                return {"verified": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            print(f"[ApiClient] ✗ Ошибка verify_password: {e}")
            return {"verified": False, "error": str(e)}

    # ============================================================
    #  НОРМАЛИЗАЦИЯ
    # ============================================================
    def normalize(self, operations: list, session_info: dict,
                  giver: str, receiver: str, point_name: str) -> dict:
        """Отправляет запрос на пакетную нормализацию."""
        try:
            r = self.session.post(
                f"{self.server_url}/api/normalize",
                json={
                    "operations": operations,
                    "session_info": session_info,
                    "giver": giver,
                    "receiver": receiver,
                    "point_name": point_name,
                },
                timeout=120,
            )
            if r.status_code == 200:
                return r.json()
            return {
                "success": 0,
                "failed": len(operations),
                "errors": [f"HTTP {r.status_code}: {r.text[:200]}"],
            }
        except Exception as e:
            return {
                "success": 0,
                "failed": len(operations),
                "errors": [str(e)],
            }

    def normalize_single(self, product_id: int, product_title: str, delta: int,
                         reason: str, operation_type: str, session_info: dict,
                         giver: str, receiver: str, point_name: str) -> dict:
        """Отправляет запрос на нормализацию ОДНОГО товара (legacy)."""
        try:
            r = self.session.post(
                f"{self.server_url}/api/normalize/single",
                json={
                    "product_id": product_id,
                    "product_title": product_title,
                    "delta": delta,
                    "reason": reason,
                    "type": operation_type,
                    "session_info": session_info,
                    "giver": giver,
                    "receiver": receiver,
                    "point_name": point_name,
                },
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============================================================
    #  TROUBLE — причины расхождений с ссылками
    # ============================================================
    def save_trouble_operations(self, operations: list, point_name: str,
                                administrator: str, session_label: str,
                                operation_date: str) -> dict:
        """Сохраняет trouble-операции с причинами и ссылками."""
        try:
            r = self.session.post(
                f"{self.server_url}/api/inventory/save-trouble-operations",
                json={
                    "operations": operations,
                    "point_name": point_name,
                    "administrator": administrator,
                    "session_label": session_label,
                    "operation_date": operation_date,
                },
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            return {"success": False, "inserted": 0,
                    "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"success": False, "inserted": 0, "error": str(e)}

    def save_correct_trouble(self, point_name: str, administrator: str,
                             cost: float, allitemTrouble: list, allitemDis: list,
                             costTrouble: float, costDisTrouble: float,
                             allRef: list, session_label: str) -> dict:
        """Сохраняет итог смены с учётом помилований."""
        try:
            r = self.session.post(
                f"{self.server_url}/api/inventory/save-correct-trouble",
                json={
                    "point_name": point_name,
                    "administrator": administrator,
                    "cost": cost,
                    "allitemTrouble": allitemTrouble,
                    "allitemDis": allitemDis,
                    "costTrouble": costTrouble,
                    "costDisTrouble": costDisTrouble,
                    "allRef": allRef,
                    "session_label": session_label,
                },
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            return {"success": False, "id": None,
                    "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"success": False, "id": None, "error": str(e)}

    # ============================================================
    #  КЛИЕНТЫ
    # ============================================================
    def search_client_by_phone(self, phone: str, point_name: str) -> dict:
        """Поиск клиента по номеру телефона через сервер."""
        try:
            old_auth = self.session.headers.pop("Authorization", None)
            try:
                r = self.session.post(
                    f"{self.server_url}/api/clients/search",
                    json={"phone": phone, "point_name": point_name},
                    timeout=15,
                )
            finally:
                if old_auth:
                    self.session.headers["Authorization"] = old_auth
            if r.status_code == 200:
                return r.json()
            else:
                print(f"[API] ✗ search_client: HTTP {r.status_code} — {r.text[:200]}")
                return {"found": False, "client": None, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            print(f"[API] ✗ search_client error: {e}")
            return {"found": False, "client": None, "error": str(e)}

    def update_client_deposit(self, client_uuid: str, new_deposit: float,
                              reason: str, point_name: str,
                              client_nickname: str = "Неизвестный",
                              client_phone: str = "—",
                              old_deposit: float = 0.0) -> dict:
        """Корректировка депозита клиента через сервер."""
        try:
            old_auth = self.session.headers.pop("Authorization", None)
            try:
                r = self.session.post(
                    f"{self.server_url}/api/clients/deposit",
                    json={
                        "client_uuid": client_uuid,
                        "new_deposit": new_deposit,
                        "reason": reason,
                        "point_name": point_name,
                        "client_nickname": client_nickname,
                        "client_phone": client_phone,
                        "old_deposit": old_deposit,
                    },
                    timeout=15,
                )
            finally:
                if old_auth:
                    self.session.headers["Authorization"] = old_auth
            if r.status_code == 200:
                return r.json()
            else:
                print(f"[API] ✗ update_deposit: HTTP {r.status_code} — {r.text[:200]}")
                return {"success": False, "message": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            print(f"[API] ✗ update_deposit error: {e}")
            return {"success": False, "message": str(e)}

    # ============================================================
    #  СВОЙСТВА
    # ============================================================
    @property
    def is_authenticated(self) -> bool:
        return self._token is not None

    @property
    def client_hwid(self) -> str:
        """Возвращает HWID текущего ПК (для отладки)."""
        return self._client_hwid

    @property
    def client_hash(self) -> str:
        """Возвращает hash текущего .exe (для отладки)."""
        return self._client_hash