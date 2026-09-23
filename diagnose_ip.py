"""
Диагностика IP-адреса клиента.
Обходит системный прокси (VPN Playnow) и идёт напрямую к VPS.

Запуск: python diagnose_ip.py
"""
import sys
import socket
import urllib.request
import ssl
from typing import Optional

# ============================================================
#  Поддержка httpx с учётом версий
# ============================================================
try:
    import httpx
    HTTPX_VERSION = tuple(int(x) for x in httpx.__version__.split(".")[:2])
except ImportError:
    print("❌ httpx не установлен. Установите: pip install httpx")
    sys.exit(1)

try:
    from config import PROXY_SERVER_URL, API_SECRET_KEY
except ImportError:
    # Fallback если config.py отсутствует
    PROXY_SERVER_URL = "https://78.17.47.74:8443"
    API_SECRET_KEY = ""


# ============================================================
#  Утилита: создание httpx-клиента БЕЗ прокси
# ============================================================
def create_direct_httpx_client(timeout: float = 15.0) -> "httpx.Client":
    """
    Создаёт httpx.Client который идёт НАПРЯМУЮ, игнорируя системный прокси.
    
    Ключевые параметры:
    - trust_env=False — не читать HTTP_PROXY/HTTPS_PROXY/NO_PROXY из окружения
    - proxy=None (httpx 0.28+) или proxies={} (httpx < 0.28) — без прокси
    """
    common_kwargs = {
        "timeout": timeout,
        "verify": False,
        "trust_env": False,
    }
    
    # В httpx 0.28+ параметр proxies deprecated, используется proxy=None
    if HTTPX_VERSION >= (0, 28):
        common_kwargs["proxy"] = None
    else:
        common_kwargs["proxies"] = {}
    
    return httpx.Client(**common_kwargs)


# ============================================================
#  Утилита: urllib запрос БЕЗ прокси
# ============================================================
def urllib_get_no_proxy(url: str, timeout: float = 10.0) -> Optional[str]:
    """
    HTTP GET через urllib, игнорируя системный прокси.
    Использует ProxyHandler({}) для отключения прокси.
    """
    try:
        # Создаём opener который НЕ использует прокси
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        
        # Отключаем проверку SSL для self-signed сертификатов
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        https_handler = urllib.request.HTTPSHandler(context=ssl_context)
        opener = urllib.request.build_opener(proxy_handler, https_handler)
        
        response = opener.open(url, timeout=timeout)
        return response.read().decode().strip()
    except Exception as e:
        return f"ERROR: {e}"


# ============================================================
#  Определение внешнего IP через разные сервисы
# ============================================================
def get_external_ip_via_services() -> dict:
    """Определяет внешний IP через разные сервисы (напрямую, без прокси)."""
    services = [
        "https://ifconfig.me",
        "https://api.ipify.org",
        "https://icanhazip.com",
        "https://checkip.amazonaws.com",
        "https://ipinfo.io/ip",
    ]
    
    results = {}
    for service in services:
        result = urllib_get_no_proxy(service)
        results[service] = result
        if result and not result.startswith("ERROR"):
            print(f"  ✓ {service}: {result}")
        else:
            print(f"  ✗ {service}: {result}")
    
    return results


# ============================================================
#  Информация о локальной сети
# ============================================================
def get_local_network_info() -> dict:
    info = {}
    
    # Локальный IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        info["local_ip"] = s.getsockname()[0]
        s.close()
    except Exception as e:
        info["local_ip"] = f"ERROR: {e}"
    
    info["hostname"] = socket.gethostname()
    return info


# ============================================================
#  Проверка системного прокси Windows
# ============================================================
def check_system_proxy() -> dict:
    """Проверяет системные настройки прокси через urllib.request.getproxies()."""
    import urllib.request
    proxies = urllib.request.getproxies()
    return proxies


# ============================================================
#  Проверка как VPS видит наш IP
# ============================================================
def check_vps_view() -> Optional[dict]:
    print("\n" + "=" * 60)
    print("🔬 Проверка: как VPS видит наш IP (НАПРЯМУЮ, минуя VPN)")
    print("=" * 60)
    
    url = f"{PROXY_SERVER_URL}/api/debug/ip"
    headers = {
        "X-API-Key": API_SECRET_KEY,
        "Content-Type": "application/json",
    }
    
    print(f"\n📡 Запрос: GET {url}")
    print(f"📦 httpx версия: {httpx.__version__}")
    print(f"🔒 trust_env=False, proxy=None (прямой канал)")
    
    try:
        with create_direct_httpx_client(timeout=15) as client:
            r = client.get(url, headers=headers)
            
            if r.status_code == 200:
                data = r.json()
                print(f"\n✅ VPS ответил успешно (HTTP 200)")
                print(f"\n📊 Информация о подключении:")
                print(f"   Direct IP (request.client.host): {data.get('direct_ip')}")
                print(f"   Port: {data.get('port')}")
                print(f"   X-Forwarded-For (первый IP): {data.get('first_forwarded_ip')}")
                
                print(f"\n🔍 Все IP-заголовки от клиента:")
                ip_headers = data.get('ip_headers', {})
                if ip_headers:
                    for header, value in ip_headers.items():
                        print(f"   {header}: {value}")
                else:
                    print(f"   (нет IP-заголовков — прямой канал)")
                
                wl = data.get('whitelist_check', {})
                print(f"\n🛡️ Проверка whitelist на VPS:")
                print(f"   Проверяемый IP: {wl.get('ip_being_checked')}")
                print(f"   Разрешён (ALLOWED_IPS): {wl.get('is_allowed')}")
                print(f"   Админ (ADMIN_IPS): {wl.get('is_admin')}")
                print(f"   Совпавшая сеть: {wl.get('matched_network')}")
                
                print(f"\n📋 Разрешённые сети на VPS:")
                for net in wl.get('allowed_networks', []):
                    print(f"   • {net}")
                for net in wl.get('admin_networks', []):
                    print(f"   • {net} (admin)")
                
                return data
                
            elif r.status_code == 403:
                print(f"\n❌ VPS вернул 403 Forbidden!")
                print(f"   Тело ответа: {r.text[:500]}")
                print(f"\n💡 Возможные причины:")
                print(f"   1. IP клиента не в ALLOWED_IPS / ADMIN_IPS")
                print(f"   2. Middleware блокирует /api/debug/* (не открыт)")
                return None
            elif r.status_code == 401:
                print(f"\n❌ VPS вернул 401 Unauthorized!")
                print(f"   Неверный X-API-Key или его нет в .env")
                return None
            else:
                print(f"\n❌ VPS вернул HTTP {r.status_code}")
                print(f"   Тело: {r.text[:500]}")
                return None
                
    except httpx.ConnectError as e:
        print(f"\n❌ Ошибка подключения к VPS: {e}")
        print(f"\n💡 Проверьте:")
        print(f"   1. VPS доступен: ping 78.17.47.74")
        print(f"   2. Сервис запущен: ssh root@78.17.47.74 'systemctl status qfact-api'")
        print(f"   3. Порт открыт: telnet 78.17.47.74 8443")
        return None
    except httpx.TimeoutException:
        print(f"\n❌ Таймаут подключения к VPS (15 сек)")
        print(f"   VPS не отвечает или недоступен")
        return None
    except Exception as e:
        print(f"\n❌ Непредвиденная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================
#  Главная функция
# ============================================================
def main():
    print("=" * 60)
    print("🔍 ДИАГНОСТИКА IP-АДРЕСА (обход системного прокси)")
    print("=" * 60)
    
    print(f"\n📡 VPS URL: {PROXY_SERVER_URL}")
    
    # 0. Системные прокси
    print("\n" + "=" * 60)
    print("⚙️ Системные настройки прокси (видит Python)")
    print("=" * 60)
    proxies = check_system_proxy()
    if proxies:
        for scheme, proxy_url in proxies.items():
            print(f"   {scheme}: {proxy_url}")
        print(f"\n⚠️ Системный прокси АКТИВЕН!")
        print(f"   Но этот скрипт его игнорирует (trust_env=False)")
    else:
        print(f"   Системный прокси не настроен")
    
    # 1. Локальная сеть
    print("\n" + "=" * 60)
    print("📍 Локальная сеть")
    print("=" * 60)
    local_info = get_local_network_info()
    print(f"  Hostname: {local_info.get('hostname')}")
    print(f"  Local IP: {local_info.get('local_ip')}")
    
    # 2. Внешний IP
    print("\n" + "=" * 60)
    print("🌐 Внешний IP (через разные сервисы, БЕЗ прокси)")
    print("=" * 60)
    external_ips = get_external_ip_via_services()
    
    # 3. Уникальность IP
    unique_ips = set(
        ip for ip in external_ips.values() 
        if ip and not str(ip).startswith("ERROR")
    )
    print(f"\n📊 Уникальных IP обнаружено: {len(unique_ips)}")
    for ip in unique_ips:
        print(f"   • {ip}")
    
    if len(unique_ips) > 1:
        print("\n⚠️  ВНИМАНИЕ: Разные сервисы видят РАЗНЫЕ IP!")
        print("   Это указывает на VPN/прокси с разными маршрутами")
    elif len(unique_ips) == 1:
        my_public_ip = list(unique_ips)[0]
        print(f"\n✅ Все сервисы видят один IP: {my_public_ip}")
    else:
        my_public_ip = None
    
    # 4. VPS
    vps_info = check_vps_view()
    
    # 5. Итог
    print("\n" + "=" * 60)
    print("📋 ИТОГОВЫЙ АНАЛИЗ")
    print("=" * 60)
    
    if vps_info and my_public_ip:
        vps_sees = vps_info.get('whitelist_check', {}).get('ip_being_checked')
        
        print(f"\nВнешний IP (по версии ifconfig.me): {my_public_ip}")
        print(f"IP который видит VPS:               {vps_sees}")
        
        if my_public_ip == vps_sees:
            print(f"\n✅ VPS видит тот же IP что и внешние сервисы")
            wl = vps_info.get('whitelist_check', {})
            if wl.get('is_allowed') or wl.get('is_admin'):
                print(f"✅ IP в whitelist — всё работает!")
                print(f"\n🎉 Можно закрывать смену — PDF придёт в Telegram")
            else:
                print(f"❌ IP НЕ в whitelist!")
                print(f"   Добавьте {my_public_ip} в ALLOWED_IPS или ADMIN_IPS на VPS")
        else:
            print(f"\n⚠️  РАСХОЖДЕНИЕ:")
            print(f"   Внешние сервисы видят: {my_public_ip}")
            print(f"   VPS видит:             {vps_sees}")
            print(f"\n💡 Это значит что:")
            print(f"   - Внешний трафик идёт через VPN (провайдер → Playnow)")
            print(f"   - Трафик к VPS идёт напрямую (через статический маршрут)")
            print(f"   - Это нормально! Статический маршрут работает ✅")
            
            wl = vps_info.get('whitelist_check', {})
            if wl.get('is_allowed') or wl.get('is_admin'):
                print(f"\n✅ VPS видит провайдерский IP и он в whitelist!")
                print(f"   Приложение работает корректно 🎉")
            else:
                print(f"\n⚠️ VPS видит провайдерский IP ({vps_sees}), но он не в whitelist")
                print(f"   Добавьте {vps_sees} в ALLOWED_IPS или ADMIN_IPS на VPS")
    
    elif vps_info and not my_public_ip:
        print("⚠️ Не удалось определить внешний IP, но VPS отвечает")
    else:
        print("❌ Не удалось провести полную диагностику")
    
    print("\n" + "=" * 60)
    print("🔧 РЕКОМЕНДАЦИИ")
    print("=" * 60)
    print("1. Если VPS видит провайдерский IP в whitelist — всё готово")
    print("2. Если VPS видит VPN-IP — добавьте его в ADMIN_IPS на VPS")
    print("3. При смене провайдера/VPN — обновите whitelist")


if __name__ == "__main__":
    # Подавляем предупреждения о невалидных SSL-сертификатах
    import warnings
    import urllib3
    warnings.filterwarnings("ignore")
    if hasattr(urllib3, "disable_warnings"):
        urllib3.disable_warnings()
    
    main()