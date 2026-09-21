"""
Локальный веб-сервер для синхронизации с телефонами.
v7.2 — Адаптация pending-значений + калькулятор.

Принцип работы:
- На телефоне: два типа данных
  itemUpdates: все значения (для UI, включая распределённые алгоритмом)
  manualItemUpdates: ТОЛЬКО ручные вводы по вкусам (для отправки на ПК)
- При отправке на ПК идут ТОЛЬКО manualItemUpdates
- На ПК применяется алгоритм распределения ТОЛЬКО на товары без ручного ввода

Новое в v7.2:
- Адаптация pending-значений при изменении stock (формула: actual_new = actual_old + (stock_new - stock_old))
- adapted_updates отдаются телефону через /api/groups
- 🧮 Калькулятор для подсчёта товаров с нескольких полок
"""
import json
import threading
import socket
import time
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class SyncServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.app = FastAPI(title="QFact Sync Server")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._session_id: Optional[str] = None
        self._groups: Dict[str, dict] = {}
        self._singles: Dict[int, dict] = {}
        self._group_updates: Dict[str, int] = {}
        self._item_updates: Dict[int, int] = {}
        self._single_updates: Dict[int, int] = {}
        # 🆕 Адаптированные значения для телефона
        self._adapted_updates: dict = {"item_updates": {}, "single_updates": {}, "group_updates": {}}
        self._callbacks = []
        self._version: int = 0
        self._setup_routes()
        self._thread: Optional[threading.Thread] = None
        self._server = None

    def _setup_routes(self):
        @self.app.get("/favicon.ico")
        async def favicon():
            return Response(content=b"", media_type="image/x-icon")

        @self.app.get("/api/health")
        async def health():
            return {
                "status": "ok",
                "session_active": self._session_id is not None,
                "session_id": self._session_id,
                "groups_count": len(self._groups),
                "singles_count": len(self._singles),
                "pending_count": (len(self._group_updates) +
                                  len(self._item_updates) +
                                  len(self._single_updates)),
                "version": self._version,
                "local_ip": get_local_ip(),
                "port": self.port,
            }

        @self.app.get("/api/groups")
        async def get_groups():
            print(f"[SyncServer] GET /api/groups — "
                  f"{len(self._groups)} групп, {len(self._singles)} одиночных")
            if not self._session_id:
                raise HTTPException(404, "Сессия не активна")
            groups_list = []
            for name, group_data in self._groups.items():
                groups_list.append({
                    "name": name,
                    "total_stock": group_data["total_stock"],
                    "products": group_data["products"],
                })
            groups_list.sort(key=lambda g: g["name"].lower())
            singles_list = []
            for pid, product in self._singles.items():
                singles_list.append({
                    "id": pid,
                    "title": product["title"],
                    "stock": product["stock"],
                })
            singles_list.sort(key=lambda p: p["title"].lower())
            return {
                "session_id": self._session_id,
                "groups": groups_list,
                "singles": singles_list,
                "groups_count": len(groups_list),
                "singles_count": len(singles_list),
                "version": self._version,
                # 🆕 Адаптированные значения для телефона
                "adapted_updates": self._adapted_updates,
            }

        @self.app.post("/api/update_all")
        async def update_all(request: Request):
            try:
                data = await request.json()
            except Exception as e:
                print(f"[SyncServer] ✗ Ошибка парсинга JSON: {e}")
                raise HTTPException(400, f"Invalid JSON: {e}")
            group_updates_in = data.get("group_updates", {})
            item_updates_in = data.get("item_updates", {})
            single_updates_in = data.get("single_updates", {})
            print(f"[SyncServer] POST /api/update_all — "
                  f"{len(group_updates_in)} групп, "
                  f"{len(item_updates_in)} ручных вкусов, "
                  f"{len(single_updates_in)} одиночных")
            if item_updates_in:
                print(f"[SyncServer] 📋 ТОЧНЫЕ ручные факты (manual):")
                for pid, actual in item_updates_in.items():
                    print(f"    pid={pid} → actual={actual}")
            for group_name, total_actual in group_updates_in.items():
                if group_name in self._groups:
                    try:
                        self._group_updates[group_name] = int(total_actual)
                    except (ValueError, TypeError):
                        pass
            for pid_str, actual in item_updates_in.items():
                try:
                    self._item_updates[int(pid_str)] = int(actual)
                except (ValueError, TypeError):
                    pass
            for pid_str, actual in single_updates_in.items():
                try:
                    pid = int(pid_str)
                    if pid in self._singles:
                        self._single_updates[pid] = int(actual)
                except (ValueError, TypeError):
                    pass
            for callback in self._callbacks:
                try:
                    callback({
                        "group_updates": self._group_updates,
                        "item_updates": self._item_updates,
                        "single_updates": self._single_updates,
                    })
                except Exception as e:
                    print(f"[SyncServer] Callback error: {e}")
            return {
                "success": True,
                "pending_groups": len(self._group_updates),
                "pending_items": len(self._item_updates),
                "pending_singles": len(self._single_updates),
            }

        @self.app.get("/api/pending_all")
        async def get_pending_all():
            pending = []
            for group_name, total_actual in self._group_updates.items():
                group_data = self._groups.get(group_name, {})
                total_stock = group_data.get("total_stock", 0)
                pending.append({
                    "type": "group", "name": group_name, "stock": total_stock,
                    "actual": total_actual, "delta": total_actual - total_stock,
                    "items": [
                        {"product_id": p["id"], "title": p["title"],
                         "stock": p["stock"], "actual": self._item_updates.get(p["id"])}
                        for p in group_data.get("products", [])
                    ],
                })
            for pid, actual in self._single_updates.items():
                product = self._singles.get(pid, {})
                stock = product.get("stock", 0)
                pending.append({
                    "type": "single", "product_id": pid, "name": product.get("title", "?"),
                    "stock": stock, "actual": actual, "delta": actual - stock,
                })
            return {"has_pending": len(pending) > 0, "updates": pending, "count": len(pending)}

        @self.app.post("/api/confirm_all")
        async def confirm_all():
            g = len(self._group_updates)
            i = len(self._item_updates)
            s = len(self._single_updates)
            self._group_updates.clear()
            self._item_updates.clear()
            self._single_updates.clear()
            return {"success": True, "applied_groups": g, "applied_items": i, "applied_singles": s}

        @self.app.post("/api/reject_all")
        async def reject_all():
            self._group_updates.clear()
            self._item_updates.clear()
            self._single_updates.clear()
            return {"success": True}

        @self.app.get("/", response_class=HTMLResponse)
        async def index():
            print("[SyncServer] GET / — отдаю HTML (v7.2 + калькулятор + адаптация)")
            html = self._get_mobile_html()
            return HTMLResponse(content=html, headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            })

    def start_session(self, session_id: str, groups_data: list, singles_data: list):
        self._session_id = session_id
        self._groups = {}
        self._singles = {}
        self._group_updates.clear()
        self._item_updates.clear()
        self._single_updates.clear()
        self._adapted_updates = {"item_updates": {}, "single_updates": {}, "group_updates": {}}
        self._version = 1
        for g in groups_data:
            self._groups[g["name"]] = {"name": g["name"], "total_stock": g["total_stock"], "products": g["products"]}
        for s in singles_data:
            self._singles[s["id"]] = {"id": s["id"], "title": s["title"], "stock": s["stock"]}
        print(f"[SyncServer] ✓ Сессия: {session_id} ({len(groups_data)} групп, {len(singles_data)} одиночных, v{self._version})")

    def update_data(self, groups_data: list, singles_data: list):
        """
        🆕 v7.2: Обновляет данные с АДАПТАЦИЕЙ pending-значений.
        Если stock изменился (продажа/внесение в SmartShell) —
        корректируем pending значения по формуле:
            actual_new = actual_old + (stock_new - stock_old)
        Адаптированные значения передаются телефону через adapted_updates.
        """
        if not self._session_id:
            return

        # Запоминаем СТАРЫЕ stock для адаптации
        old_stocks = {}
        for g in self._groups.values():
            old_stocks[f"group_{g['name']}"] = g["total_stock"]
            for p in g["products"]:
                old_stocks[f"item_{p['id']}"] = p["stock"]
        for s in self._singles.values():
            old_stocks[f"single_{s['id']}"] = s["stock"]

        # Сохраняем старые pending для переноса
        old_group_updates = dict(self._group_updates)
        old_item_updates = dict(self._item_updates)
        old_single_updates = dict(self._single_updates)

        # 🆕 Очищаем адаптированные значения (будут заполнены заново)
        self._adapted_updates = {"item_updates": {}, "single_updates": {}, "group_updates": {}}

        # Обновляем структуры
        self._groups = {}
        for g in groups_data:
            self._groups[g["name"]] = {"name": g["name"], "total_stock": g["total_stock"], "products": g["products"]}
        self._singles = {}
        for s in singles_data:
            self._singles[s["id"]] = {"id": s["id"], "title": s["title"], "stock": s["stock"]}

        # 🆕 АДАПТАЦИЯ pending-значений
        adapted_groups = 0
        adapted_items = 0
        adapted_singles = 0

        # Группы
        self._group_updates = {}
        for group_name, actual in old_group_updates.items():
            if group_name in self._groups:
                old_total = old_stocks.get(f"group_{group_name}")
                new_total = self._groups[group_name]["total_stock"]
                if old_total is not None and old_total != new_total:
                    stock_delta = new_total - old_total
                    actual = actual + stock_delta
                    self._adapted_updates["group_updates"][group_name] = actual
                    adapted_groups += 1
                self._group_updates[group_name] = actual

        # Точные ручные факты по товарам
        self._item_updates = {}
        for pid, actual in old_item_updates.items():
            found = False
            for g in self._groups.values():
                for p in g["products"]:
                    if p["id"] == pid:
                        old_stock = old_stocks.get(f"item_{pid}")
                        new_stock = p["stock"]
                        if old_stock is not None and old_stock != new_stock:
                            stock_delta = new_stock - old_stock
                            actual = actual + stock_delta
                            self._adapted_updates["item_updates"][str(pid)] = actual
                            adapted_items += 1
                        self._item_updates[pid] = actual
                        found = True
                        break
                if found:
                    break

        # Одиночные товары
        self._single_updates = {}
        for pid, actual in old_single_updates.items():
            if pid in self._singles:
                old_stock = old_stocks.get(f"single_{pid}")
                new_stock = self._singles[pid]["stock"]
                if old_stock is not None and old_stock != new_stock:
                    stock_delta = new_stock - old_stock
                    actual = actual + stock_delta
                    self._adapted_updates["single_updates"][str(pid)] = actual
                    adapted_singles += 1
                self._single_updates[pid] = actual

        self._version += 1
        kept_items = len(self._item_updates)

        # Логирование адаптаций
        if adapted_groups > 0 or adapted_items > 0 or adapted_singles > 0:
            print(f"[SyncServer] 🔄 АДАПТАЦИЯ по изменению stock:")
            if adapted_groups > 0:
                print(f"    Групп: {adapted_groups}")
            if adapted_items > 0:
                print(f"    Точных вкусов: {adapted_items}")
            if adapted_singles > 0:
                print(f"    Одиночных: {adapted_singles}")

        print(f"[SyncServer] ✓ Обновление: {len(groups_data)} групп, {len(singles_data)} одиночных, "
              f"сохранено {len(self._group_updates)}+{kept_items}+{len(self._single_updates)} pending, "
              f"адаптировано {adapted_groups}+{adapted_items}+{adapted_singles}, версия={self._version}")

    def stop_session(self):
        self._session_id = None
        self._groups.clear()
        self._singles.clear()
        self._group_updates.clear()
        self._item_updates.clear()
        self._single_updates.clear()
        self._adapted_updates = {"item_updates": {}, "single_updates": {}, "group_updates": {}}
        self._version = 0
        print("[SyncServer] Сессия остановлена")

    def get_pending_updates(self) -> list:
        result = []
        for group_name, total_actual in self._group_updates.items():
            group_data = self._groups.get(group_name, {})
            total_stock = group_data.get("total_stock", 0)
            result.append({
                "type": "group", "name": group_name, "stock": total_stock,
                "actual": total_actual, "delta": total_actual - total_stock,
                "items": [
                    {"product_id": p["id"], "title": p["title"],
                     "stock": p["stock"], "actual": self._item_updates.get(p["id"])}
                    for p in group_data.get("products", [])
                ],
            })
        for pid, actual in self._single_updates.items():
            product = self._singles.get(pid, {})
            stock = product.get("stock", 0)
            result.append({
                "type": "single", "product_id": pid, "name": product.get("title", "?"),
                "stock": stock, "actual": actual, "delta": actual - stock,
            })
        return result

    def apply_pending(self, callback):
        updates = {
            "group_updates": dict(self._group_updates),
            "item_updates": dict(self._item_updates),
            "single_updates": dict(self._single_updates),
        }
        self._group_updates.clear()
        self._item_updates.clear()
        self._single_updates.clear()
        return updates

    def on_pending_update(self, callback):
        self._callbacks.append(callback)

    def get_qr_url(self) -> str:
        local_ip = get_local_ip()
        return f"http://{local_ip}:{self.port}/?v={int(time.time())}"

    def _wait_for_ready(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(("127.0.0.1", self.port))
                s.close()
                print(f"[SyncServer] ✓ Порт {self.port} готов")
                return True
            except (ConnectionRefusedError, OSError):
                time.sleep(0.1)
            finally:
                try:
                    s.close()
                except:
                    pass
        print(f"[SyncServer] ⚠ Порт {self.port} не ответил за {timeout}с")
        return False

    def start(self):
        if self._thread and self._thread.is_alive():
            print("[SyncServer] Уже запущен")
            return

        def run():
            import asyncio
            config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
            server = uvicorn.Server(config)
            self._server = server
            asyncio.run(server.serve())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        self._wait_for_ready(timeout=5.0)
        print(f"[SyncServer] ✓ http://{get_local_ip()}:{self.port}/")

    def stop(self):
        if self._server:
            self._server.should_exit = True

    def _get_mobile_html(self) -> str:
        return r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QFact v7.2</title>
<style>
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; height: 100%; background: #0D1217; }
body { color: #fff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
.sticky-header { position: sticky; top: 0; z-index: 100; background: #0D1217;
                 padding: 12px 16px 8px; border-bottom: 1px solid #1f2937;
                 flex-shrink: 0; box-shadow: 0 2px 8px rgba(0,0,0,0.5); }
.sticky-header h1 { font-size: 18px; margin: 0 0 8px 0;
                    display: flex; align-items: center; justify-content: space-between; }
.sticky-header .status-line { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
#status { color: #94a3b8; font-size: 12px; flex: 1; }
#logToggle { background: #1a1a2e; color: #3b82f6; border: 1px solid #333;
              border-radius: 4px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
#logToggle:hover { background: #2a2a3e; }
.search { width: 100%; padding: 10px 12px; background: #161C23; color: #fff;
          border: 1px solid #555; border-radius: 6px; font-size: 14px; }
.search:focus { outline: none; border-color: #2C87FD; }
.log { background: #1a1a2e; padding: 8px; margin: 8px 16px 0; border-radius: 6px;
       font-family: monospace; font-size: 11px; max-height: 150px;
       overflow-y: auto; border: 1px solid #333; display: none; }
.log.visible { display: block; }
.log .ok { color: #10b981; }
.log .err { color: #ef4444; }
.log .info { color: #3b82f6; }
.log .warn { color: #f59e0b; }
.scroll-content { flex: 1; overflow-y: auto; padding: 8px 16px 160px;
                  -webkit-overflow-scrolling: touch; }
.section-title { font-size: 13px; color: #94a3b8; text-transform: uppercase;
                 letter-spacing: 1px; margin: 16px 0 8px; padding-left: 4px; }
.group { background: #161C23; border-radius: 8px; margin: 8px 0;
         overflow: hidden; border: 1px solid #1f2937; }
.group-header { display: flex; flex-wrap: wrap; align-items: center;
                padding: 12px; background: rgba(44,135,253,0.08); gap: 8px; }
.expand-arrow { color: #2C87FD; font-size: 14px; cursor: pointer; min-width: 20px; }
.group-title { font-weight: 600; font-size: 15px; flex: 1; min-width: 100px; cursor: pointer; }
.group-total { font-size: 12px; color: #94a3b8; white-space: nowrap; }
.group-total.has-changes { font-weight: bold; }
.group-input { width: 70px; padding: 8px; background: #0D1217; color: #fff;
               border: 1px solid #555; border-radius: 6px; text-align: center;
               font-size: 15px; font-weight: bold; }
.group-input:focus { border-color: #2C87FD; outline: none; }
.group-input.modified { border-color: #f59e0b; }
.group-input.equal { border-color: #10b981; color: #10b981; }
.group-input.less { border-color: #ef4444; color: #ef4444; }
.group-input.more { border-color: #3b82f6; color: #3b82f6; }
.items { display: none; padding: 4px 12px 12px; }
.items.open { display: block; }
.product { display: flex; align-items: center; gap: 8px; padding: 8px 0;
           border-top: 1px solid rgba(255,255,255,0.05); }
.product-name { flex: 1; font-size: 13px; color: #e5e7eb; min-width: 0;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.product-stock { font-size: 11px; color: #64748b; white-space: nowrap; }
.item-input { width: 65px; padding: 6px; background: #0D1217; color: #fff;
              border: 1px solid #444; border-radius: 5px; text-align: center;
              font-size: 14px; }
.item-input:focus { border-color: #2C87FD; outline: none; background: #1a1f2e; }
.item-input.active-field { border-color: #ff6b6b !important; box-shadow: 0 0 0 2px rgba(255,107,107,0.3); background: rgba(255,107,107,0.08); }
.item-input.modified { border-color: #f59e0b; background: rgba(245,158,11,0.08); }
.item-input.equal { border-color: #10b981; color: #10b981; }
.item-input.less { border-color: #ef4444; color: #ef4444; }
.item-input.more { border-color: #3b82f6; color: #3b82f6; }
.single { background: #161C23; border-radius: 8px; margin: 6px 0;
          padding: 10px 12px; display: flex; align-items: center; gap: 8px;
          border: 1px solid #1f2937; }
.single-name { flex: 1; font-size: 13px; color: #e5e7eb; min-width: 0;
               overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.single-stock { font-size: 11px; color: #64748b; white-space: nowrap; }
.bottom-actions { position: fixed; bottom: 16px; left: 16px; right: 16px;
                  background: #0D1217; border-top: 1px solid #1f2937;
                  padding: 10px 16px 16px; display: flex; gap: 10px; z-index: 10;
                  box-shadow: 0 -4px 12px rgba(0,0,0,0.5); }
.sync-btn { flex: 1; background: #2C87FD; color: #fff; border: none;
            padding: 14px; border-radius: 8px; font-size: 16px;
            font-weight: bold; cursor: pointer;
            box-shadow: 0 4px 12px rgba(44,135,253,0.4); }
.sync-btn:disabled { background: #555; box-shadow: none; cursor: default; }
.calc-btn { width: 60px; background: #ff6b6b; color: #fff; border: none;
            padding: 14px; border-radius: 8px; font-size: 20px;
            cursor: pointer; box-shadow: 0 4px 12px rgba(255,107,107,0.4);
            display: flex; align-items: center; justify-content: center; }
.calc-btn:active { background: #ee5a52; }
.hint { font-size: 11px; color: #64748b; padding: 8px 12px;
        background: rgba(44,135,253,0.05); border-top: 1px solid rgba(44,135,253,0.1); }

/* 🧮 КАЛЬКУЛЯТОР */
.calc-modal { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
              background: rgba(0,0,0,0.85); z-index: 1000;
              align-items: center; justify-content: center; padding: 20px; }
.calc-modal.active { display: flex; }
.calculator { background: #161C23; border-radius: 16px; padding: 20px;
              max-width: 360px; width: 100%; box-shadow: 0 20px 60px rgba(0,0,0,0.7);
              border: 1px solid #1f2937; }
.calc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.calc-header-title { font-size: 16px; font-weight: 600; color: #e5e7eb; }
.calc-close { background: transparent; border: none; color: #94a3b8;
              font-size: 22px; cursor: pointer; padding: 4px 8px; }
.calc-close:hover { color: #fff; }
.calc-active-info { font-size: 11px; color: #f59e0b; margin-bottom: 8px;
                    padding: 6px 8px; background: rgba(245,158,11,0.1);
                    border-radius: 4px; text-align: center; min-height: 24px; }
.calc-display { background: #0D1217; padding: 20px; border-radius: 10px;
                margin-bottom: 16px; text-align: right; font-size: 32px;
                font-weight: 600; min-height: 70px; word-wrap: break-word;
                word-break: break-all; color: #fff; border: 1px solid #1f2937; }
.calc-expression { font-size: 13px; color: #64748b; text-align: right;
                   margin-bottom: 4px; min-height: 18px; }
.calc-buttons { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.calc-btn-key { padding: 18px; border: none; border-radius: 10px;
                font-size: 20px; font-weight: 500; cursor: pointer;
                background: #1f2937; color: #fff; transition: all 0.15s; }
.calc-btn-key:active { transform: scale(0.95); background: #374151; }
.calc-btn-key.operator { background: #2C87FD; color: #fff; }
.calc-btn-key.operator:active { background: #1e6ed6; }
.calc-btn-key.equals { background: #10b981; color: #fff; grid-column: span 2; }
.calc-btn-key.equals:active { background: #059669; }
.calc-btn-key.clear { background: #ef4444; color: #fff; }
.calc-btn-key.clear:active { background: #b91c1c; }
.calc-btn-key.backspace { background: #6b7280; color: #fff; }
.calc-btn-key.backspace:active { background: #4b5563; }
.calc-apply { background: #ff6b6b; color: #fff; border: none;
              padding: 14px; border-radius: 10px; font-size: 16px;
              font-weight: 600; cursor: pointer; margin-top: 12px;
              width: 100%; box-shadow: 0 4px 12px rgba(255,107,107,0.3); }
.calc-apply:active { background: #ee5a52; }
.calc-apply:disabled { background: #555; box-shadow: none; cursor: default; }
.calc-info { text-align: center; color: #64748b; font-size: 11px; margin-top: 10px; }
</style>
</head>
<body>
<div class="sticky-header">
    <h1>
        <span>📦 QFact v7.2</span>
        <button id="logToggle" onclick="toggleLog()">📋 Лог</button>
    </h1>
    <div class="status-line">
        <div id="status">Загрузка...</div>
    </div>
    <input type="text" class="search" id="search" placeholder="🔍 Поиск по бренду или товару..." oninput="onSearch()">
</div>
<div class="log" id="log"></div>
<div class="scroll-content" id="scrollContent">
    <div id="content"></div>
</div>

<div class="bottom-actions">
    <button class="calc-btn" id="calcBtn" onclick="openCalculator()" title="Калькулятор">🧮</button>
    <button class="sync-btn" id="syncBtn" disabled onclick="syncData()">📤 Синхронизировать</button>
</div>

<!-- 🧮 КАЛЬКУЛЯТОР -->
<div class="calc-modal" id="calcModal">
    <div class="calculator">
        <div class="calc-header">
            <span class="calc-header-title">🧮 Калькулятор</span>
            <button class="calc-close" onclick="closeCalculator()">✕</button>
        </div>
        <div class="calc-active-info" id="calcActiveInfo">Выберите поле для применения результата</div>
        <div class="calc-expression" id="calcExpression"></div>
        <div class="calc-display" id="calcDisplay">0</div>
        <div class="calc-buttons">
            <button class="calc-btn-key clear" onclick="calcClear()">C</button>
            <button class="calc-btn-key backspace" onclick="calcBackspace()">←</button>
            <button class="calc-btn-key operator" onclick="calcOperator('/')">÷</button>
            <button class="calc-btn-key operator" onclick="calcOperator('*')">×</button>
            <button class="calc-btn-key" onclick="calcNumber('7')">7</button>
            <button class="calc-btn-key" onclick="calcNumber('8')">8</button>
            <button class="calc-btn-key" onclick="calcNumber('9')">9</button>
            <button class="calc-btn-key operator" onclick="calcOperator('-')">−</button>
            <button class="calc-btn-key" onclick="calcNumber('4')">4</button>
            <button class="calc-btn-key" onclick="calcNumber('5')">5</button>
            <button class="calc-btn-key" onclick="calcNumber('6')">6</button>
            <button class="calc-btn-key operator" onclick="calcOperator('+')">+</button>
            <button class="calc-btn-key" onclick="calcNumber('1')">1</button>
            <button class="calc-btn-key" onclick="calcNumber('2')">2</button>
            <button class="calc-btn-key" onclick="calcNumber('3')">3</button>
            <button class="calc-btn-key" onclick="calcNumber('.')">.</button>
            <button class="calc-btn-key" onclick="calcNumber('0')" style="grid-column: span 2;">0</button>
            <button class="calc-btn-key equals" onclick="calcEquals()">=</button>
        </div>
        <button class="calc-apply" id="calcApply" onclick="calcApply()">✓ Применить к полю</button>
        <div class="calc-info">Нажмите на поле → используйте калькулятор → Применить</div>
    </div>
</div>

<script>
var groups = [], singles = [];
var itemUpdates = {}, manualItemUpdates = {}, singleUpdates = {};
var expandedGroups = {}, currentVersion = 0, refreshInterval = null, currentSearch = '';
var logVisible = false;

// 🧮 Калькулятор
var activeInput = null;
var calcValue = '0', calcCurrentOp = null, calcPrevious = null, calcNewNumber = true, calcExpression = '';

function toggleLog() {
    logVisible = !logVisible;
    var log = document.getElementById('log'), btn = document.getElementById('logToggle');
    if (logVisible) { log.classList.add('visible'); btn.textContent = '✕ Скрыть'; }
    else { log.classList.remove('visible'); btn.textContent = '📋 Лог'; }
}

function addLog(msg, type) {
    var el = document.getElementById('log'), line = document.createElement('div');
    line.className = type || 'info';
    line.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    el.appendChild(line); el.scrollTop = el.scrollHeight;
    console.log('[QFact][' + (type || 'info') + '] ' + msg);
}

function findGroup(name) {
    for (var i = 0; i < groups.length; i++) if (groups[i].name === name) return groups[i];
    return null;
}

function findSingle(pid) {
    for (var i = 0; i < singles.length; i++) if (singles[i].id === pid) return singles[i];
    return null;
}

function findGroupByProductId(pid) {
    pid = parseInt(pid);
    for (var i = 0; i < groups.length; i++)
        for (var j = 0; j < groups[i].products.length; j++)
            if (groups[i].products[j].id === pid) return groups[i];
    return null;
}

function getGroupTotal(group) {
    var total = 0, hasChanges = false;
    for (var i = 0; i < group.products.length; i++) {
        var p = group.products[i];
        if (itemUpdates[p.id] !== undefined) { total += itemUpdates[p.id]; hasChanges = true; }
        else total += p.stock;
    }
    return hasChanges ? total : null;
}

function distribute(total, products) {
    var totalStock = 0;
    for (var i = 0; i < products.length; i++) totalStock += products[i].stock;
    if (totalStock === 0) {
        var perItem = Math.floor(total / products.length), result = [];
        for (var i = 0; i < products.length; i++) result.push(perItem);
        var leftover = total - perItem * products.length;
        for (var j = 0; j < leftover && j < result.length; j++) result[j]++;
        return result;
    }
    var delta = total - totalStock, exact = [], floored = [];
    for (var i = 0; i < products.length; i++) {
        var e = delta * (products[i].stock / totalStock);
        exact.push(e); floored.push(Math.floor(e));
    }
    var sum = 0;
    for (var i = 0; i < floored.length; i++) sum += floored[i];
    var leftover = delta - sum, remainders = [];
    for (var i = 0; i < exact.length; i++) remainders.push({r: exact[i] - floored[i], i: i});
    remainders.sort(function(a, b) { return b.r - a.r; });
    for (var j = 0; j < leftover; j++) floored[remainders[j % remainders.length].i] += 1;
    var result = [];
    for (var i = 0; i < products.length; i++) result.push(products[i].stock + floored[i]);
    return result;
}

function safeId(name) { return name.replace(/[^a-zA-Zа-яА-Я0-9]/g, '_'); }

// 🆕 Адаптация значений при обновлении версии (продажа/внесение)
function applyAdaptedUpdates(adapted) {
    if (!adapted) return;
    var count = 0;
    addLog('🔄 applyAdaptedUpdates called', 'info');
    if (adapted.item_updates) {
        addLog('  item_updates keys: ' + Object.keys(adapted.item_updates).join(', '), 'info');
        for (var pid in adapted.item_updates) {
            var pidInt = parseInt(pid);
            var newValue = parseInt(adapted.item_updates[pid]);
            addLog('  Processing pid=' + pidInt + ', new value=' + newValue, 'info');
            if (itemUpdates[pidInt] !== undefined || itemUpdates[pid] !== undefined) {
                var oldValue = itemUpdates[pidInt] !== undefined ? itemUpdates[pidInt] : itemUpdates[pid];
                addLog('    Old value: ' + oldValue + ', New value: ' + newValue, 'info');
                itemUpdates[pidInt] = newValue;
                itemUpdates[pid] = newValue;
                if (manualItemUpdates[pidInt] !== undefined || manualItemUpdates[pid] !== undefined) {
                    manualItemUpdates[pidInt] = newValue;
                    manualItemUpdates[pid] = newValue;
                }
                count++;
            } else {
                addLog('    pid=' + pidInt + ' not found in itemUpdates', 'warn');
            }
        }
    }
    if (adapted.single_updates) {
        for (var pid in adapted.single_updates) {
            var pidInt = parseInt(pid);
            var newValue = parseInt(adapted.single_updates[pid]);
            if (singleUpdates[pidInt] !== undefined || singleUpdates[pid] !== undefined) {
                singleUpdates[pidInt] = newValue;
                singleUpdates[pid] = newValue;
                count++;
            }
        }
    }
    if (count > 0) {
        addLog('🔄 Адаптировано значений при продаже/внесении: ' + count, 'warn');
    }
}

function loadData() {
    addLog('Loading...', 'info');
    fetch('/api/health')
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function(h) {
            if (!h.session_active) throw new Error('Session not active');
            if (currentVersion > 0 && h.version !== currentVersion) {
                addLog('⚡ v' + currentVersion + ' → v' + h.version + ' (обновление stock)', 'warn');
            }
            currentVersion = h.version;
            return fetch('/api/groups');
        })
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function(d) {
            groups = d.groups; singles = d.singles;
            if (d.adapted_updates) {
                applyAdaptedUpdates(d.adapted_updates);
            }
            addLog('✓ ' + groups.length + ' групп, ' + singles.length + ' одиночных', 'ok');
            document.getElementById('status').textContent = '✓ ' + groups.length + ' групп • ' + singles.length + ' одиночных';
            render();
        })
        .catch(function(e) {
            addLog('✗ ' + e.message, 'err');
            document.getElementById('status').textContent = '✗ ' + e.message;
        });
}

function startVersionCheck() {
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(function() {
        fetch('/api/health')
            .then(function(r) { return r.json(); })
            .then(function(h) {
                if (h.version !== currentVersion) {
                    addLog('⚡ Обновление v' + h.version, 'warn');
                    loadData();
                }
            })
            .catch(function() {});
    }, 5000);
}

function onSearch() { currentSearch = document.getElementById('search').value.toLowerCase(); render(); }

function render() {
    var scrollContent = document.getElementById('scrollContent');
    var scrollTop = scrollContent ? scrollContent.scrollTop : 0;
    var filteredGroups = groups, filteredSingles = singles;
    if (currentSearch) {
        filteredGroups = [];
        for (var i = 0; i < groups.length; i++)
            if (groups[i].name.toLowerCase().indexOf(currentSearch) !== -1) filteredGroups.push(groups[i]);
        filteredSingles = [];
        for (var i = 0; i < singles.length; i++)
            if (singles[i].title.toLowerCase().indexOf(currentSearch) !== -1) filteredSingles.push(singles[i]);
    }
    var html = '';
    if (filteredGroups.length > 0) {
        html += '<div class="section-title">📚 Группы (' + filteredGroups.length + ')</div>';
        for (var i = 0; i < filteredGroups.length; i++) {
            var g = filteredGroups[i], sid = safeId(g.name);
            var isOpen = expandedGroups[sid] === true;
            html += '<div class="group"><div class="group-header">';
            html += '<span class="expand-arrow" onclick="toggleGroup(\'' + sid + '\')">' + (isOpen ? '▼' : '▶') + '</span>';
            html += '<span class="group-title" onclick="toggleGroup(\'' + sid + '\')">' + g.name + '</span>';
            html += '<span class="group-total" id="total_' + sid + '">Учёт: ' + g.total_stock + '</span>';
            html += '<input type="number" class="group-input" id="groupinput_' + sid + '" ';
            html += 'placeholder="' + g.total_stock + '" ';
            html += 'data-group="' + g.name.replace(/"/g, '&quot;') + '" ';
            html += 'onclick="event.stopPropagation()">';
            html += '</div><div class="items' + (isOpen ? ' open' : '') + '" id="items_' + sid + '">';
            for (var j = 0; j < g.products.length; j++) {
                var p = g.products[j];
                html += '<div class="product"><span class="product-name">' + p.title + '</span>';
                html += '<span class="product-stock">' + p.stock + ' шт</span>';
                html += '<input type="number" class="item-input" data-pid="' + p.id + '" ';
                html += 'data-group="' + g.name.replace(/"/g, '&quot;') + '" placeholder="?"></div>';
            }
            html += '<div class="hint">💡 Ввод в шапке — распределится. Ввод по вкусам — сохранится точно.</div>';
            html += '</div></div>';
        }
    }
    if (filteredSingles.length > 0) {
        html += '<div class="section-title">📄 Одиночные (' + filteredSingles.length + ')</div>';
        for (var i = 0; i < filteredSingles.length; i++) {
            var s = filteredSingles[i];
            html += '<div class="single"><span class="single-name">' + s.title + '</span>';
            html += '<span class="single-stock">Учёт: ' + s.stock + '</span>';
            html += '<input type="number" class="item-input" data-single-id="' + s.id + '" placeholder="?"></div>';
        }
    }
    if (filteredGroups.length === 0 && filteredSingles.length === 0)
        html = '<p style="text-align:center; color:#666; padding:40px;">Ничего не найдено</p>';
    document.getElementById('content').innerHTML = html;
    attachInputHandlers(); restoreInputValues();
    for (var i = 0; i < filteredGroups.length; i++) updateGroupDisplay(filteredGroups[i].name);
    if (scrollContent) scrollContent.scrollTop = scrollTop;
}

function attachInputHandlers() {
    var itemInputs = document.querySelectorAll('.item-input[data-pid]');
    for (var i = 0; i < itemInputs.length; i++) {
        (function(input) {
            input.addEventListener('focus', function() { setActiveInput(input); });
            input.addEventListener('input', function(e) {
                var pid = parseInt(e.target.dataset.pid);
                onItemInput(pid, e.target.value, e.target.dataset.group, e.target);
            });
        })(itemInputs[i]);
    }
    var singleInputs = document.querySelectorAll('.item-input[data-single-id]');
    for (var i = 0; i < singleInputs.length; i++) {
        (function(input) {
            input.addEventListener('focus', function() { setActiveInput(input); });
            input.addEventListener('input', function(e) {
                var pid = parseInt(e.target.dataset.singleId);
                onSingleInput(pid, e.target.value, e.target);
            });
        })(singleInputs[i]);
    }
    var groupInputs = document.querySelectorAll('.group-input');
    for (var i = 0; i < groupInputs.length; i++) {
        (function(input) {
            input.addEventListener('focus', function() { setActiveInput(input); });
            input.addEventListener('input', function(e) {
                onGroupInput(e.target.dataset.group, e.target.value, e.target);
            });
        })(groupInputs[i]);
    }
}

// 🧮 Функции калькулятора
function setActiveInput(input) {
    if (activeInput && activeInput !== input) activeInput.classList.remove('active-field');
    activeInput = input;
    input.classList.add('active-field');
    updateCalcActiveInfo();
}

function updateCalcActiveInfo() {
    var info = document.getElementById('calcActiveInfo');
    var apply = document.getElementById('calcApply');
    if (!info) return;
    if (!activeInput) {
        info.textContent = '⚠ Выберите поле в списке товаров';
        info.style.color = '#ef4444';
        info.style.background = 'rgba(239,68,68,0.1)';
        if (apply) apply.disabled = true;
        return;
    }
    var label = '';
    if (activeInput.dataset.pid) {
        var pid = parseInt(activeInput.dataset.pid);
        var p = null;
        for (var i = 0; i < groups.length && !p; i++)
            for (var j = 0; j < groups[i].products.length; j++)
                if (groups[i].products[j].id === pid) { p = groups[i].products[j]; break; }
        label = p ? ('🎯 ' + p.title) : ('🎯 Товар #' + pid);
    } else if (activeInput.dataset.singleId) {
        var pid = parseInt(activeInput.dataset.singleId);
        var s = findSingle(pid);
        label = s ? ('🎯 ' + s.title) : ('🎯 Товар #' + pid);
    } else if (activeInput.dataset.group) {
        label = '🎯 Группа: ' + activeInput.dataset.group;
    }
    info.textContent = label;
    info.style.color = '#f59e0b';
    info.style.background = 'rgba(245,158,11,0.1)';
    if (apply) apply.disabled = false;
}

function openCalculator() {
    if (!activeInput) {
        alert('⚠ Сначала нажмите на поле ввода товара.\nПоле подсветится красным — это значит оно активно.\nЗатем откройте калькулятор.');
        return;
    }
    document.getElementById('calcModal').classList.add('active');
    updateCalcActiveInfo();
    calcClear();
}

function closeCalculator() {
    document.getElementById('calcModal').classList.remove('active');
}

function updateCalcDisplay() {
    document.getElementById('calcDisplay').textContent = calcValue;
    var exprEl = document.getElementById('calcExpression');
    exprEl.textContent = calcExpression;
}

function calcNumber(num) {
    if (calcNewNumber) { calcValue = num; calcNewNumber = false; }
    else {
        if (calcValue === '0' && num !== '.') calcValue = num;
        else if (num === '.' && calcValue.indexOf('.') !== -1) return;
        else calcValue += num;
    }
    updateCalcDisplay();
}

function calcOperator(op) {
    if (calcPrevious !== null && !calcNewNumber) calcEquals();
    calcPrevious = parseFloat(calcValue);
    calcCurrentOp = op;
    calcNewNumber = true;
    var opSymbol = {'+':'+', '-':'−', '*':'×', '/':'÷'}[op] || op;
    calcExpression = calcPrevious + ' ' + opSymbol;
    updateCalcDisplay();
}

function calcEquals() {
    if (calcCurrentOp === null || calcPrevious === null) return;
    var current = parseFloat(calcValue), result;
    switch (calcCurrentOp) {
        case '+': result = calcPrevious + current; break;
        case '-': result = calcPrevious - current; break;
        case '*': result = calcPrevious * current; break;
        case '/': result = current !== 0 ? calcPrevious / current : 0; break;
        default: result = current;
    }
    var opSymbol = {'+':'+', '-':'−', '*':'×', '/':'÷'}[calcCurrentOp] || '';
    calcExpression = calcPrevious + ' ' + opSymbol + ' ' + current + ' =';
    calcValue = formatCalcResult(result);
    calcCurrentOp = null; calcPrevious = null; calcNewNumber = true;
    updateCalcDisplay();
}

function formatCalcResult(num) {
    if (Number.isInteger(num)) return num.toString();
    var rounded = Math.round(num * 100) / 100;
    if (Number.isInteger(rounded)) return rounded.toString();
    return rounded.toString();
}

function calcClear() {
    calcValue = '0'; calcCurrentOp = null; calcPrevious = null;
    calcNewNumber = true; calcExpression = '';
    updateCalcDisplay();
}

function calcBackspace() {
    if (calcNewNumber) return;
    if (calcValue.length > 1) calcValue = calcValue.slice(0, -1);
    else calcValue = '0';
    updateCalcDisplay();
}

function calcApply() {
    if (!activeInput) { alert('⚠ Нет активного поля'); return; }
    var result = parseFloat(calcValue);
    if (isNaN(result)) { alert('⚠ Некорректное значение'); return; }
    var rounded = Math.round(result);
    if (rounded < 0) rounded = 0;
    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeInputValueSetter.call(activeInput, rounded.toString());
    activeInput.dispatchEvent(new Event('input', { bubbles: true }));
    activeInput.dispatchEvent(new Event('change', { bubbles: true }));
    addLog('🧮 Калькулятор: ' + calcValue + ' → ' + rounded, 'ok');
    closeCalculator();
}

document.getElementById('calcModal').addEventListener('click', function(e) {
    if (e.target.id === 'calcModal') closeCalculator();
});

function restoreInputValues() {
    var itemInputs = document.querySelectorAll('.item-input[data-pid]');
    for (var i = 0; i < itemInputs.length; i++) {
        var pid = parseInt(itemInputs[i].dataset.pid);
        if (itemUpdates[pid] !== undefined) {
            itemInputs[i].value = itemUpdates[pid];
            applyItemStyles(itemInputs[i], itemUpdates[pid], findGroupByProductId(pid));
        }
    }
    var singleInputs = document.querySelectorAll('.item-input[data-single-id]');
    for (var i = 0; i < singleInputs.length; i++) {
        var pid = parseInt(singleInputs[i].dataset.singleId);
        if (singleUpdates[pid] !== undefined) {
            singleInputs[i].value = singleUpdates[pid];
            applySingleStyles(singleInputs[i], singleUpdates[pid], findSingle(pid));
        }
    }
}

function applyItemStyles(input, actual, group) {
    var wasActive = input.classList.contains('active-field');
    input.className = 'item-input modified';
    if (wasActive) input.classList.add('active-field');
    if (group) {
        var p = null;
        for (var i = 0; i < group.products.length; i++)
            if (group.products[i].id === parseInt(input.dataset.pid)) { p = group.products[i]; break; }
        if (p) {
            var delta = actual - p.stock;
            if (delta === 0) input.classList.add('equal');
            else if (delta < 0) input.classList.add('less');
            else input.classList.add('more');
        }
    }
}

function applySingleStyles(input, actual, single) {
    var wasActive = input.classList.contains('active-field');
    input.className = 'item-input modified';
    if (wasActive) input.classList.add('active-field');
    if (single) {
        var delta = actual - single.stock;
        if (delta === 0) input.classList.add('equal');
        else if (delta < 0) input.classList.add('less');
        else input.classList.add('more');
    }
}

function onItemInput(pid, value, groupName, inputElement) {
    if (value === '' || value === null) {
        delete itemUpdates[pid]; delete manualItemUpdates[pid];
        inputElement.className = 'item-input';
        if (activeInput === inputElement) inputElement.classList.add('active-field');
    } else {
        var num = parseInt(value);
        if (!isNaN(num)) {
            itemUpdates[pid] = num; manualItemUpdates[pid] = num;
            applyItemStyles(inputElement, num, findGroup(groupName));
        }
    }
    updateGroupDisplay(groupName); updateSyncButton();
}

function onSingleInput(pid, value, inputElement) {
    if (value === '' || value === null) delete singleUpdates[pid];
    else { var num = parseInt(value); if (!isNaN(num)) singleUpdates[pid] = num; }
    if (value !== '' && value !== null) applySingleStyles(inputElement, parseInt(value), findSingle(pid));
    else { inputElement.className = 'item-input'; if (activeInput === inputElement) inputElement.classList.add('active-field'); }
    updateSyncButton();
}

function onGroupInput(groupName, value, inputElement) {
    var group = findGroup(groupName); if (!group) return;
    if (value === '' || value === null) {
        for (var i = 0; i < group.products.length; i++) {
            var pid = group.products[i].id;
            delete itemUpdates[pid]; delete manualItemUpdates[pid];
        }
    } else {
        var total = parseInt(value); if (isNaN(total)) return;
        var distributed = distribute(total, group.products);
        for (var i = 0; i < group.products.length; i++) {
            var pid = group.products[i].id;
            itemUpdates[pid] = distributed[i]; delete manualItemUpdates[pid];
        }
    }
    updateGroupItemsValues(groupName); updateGroupDisplay(groupName); updateSyncButton();
}

function updateGroupItemsValues(groupName) {
    var group = findGroup(groupName); if (!group) return;
    var sid = safeId(groupName);
    var container = document.getElementById('items_' + sid); if (!container) return;
    var inputs = container.querySelectorAll('.item-input');
    for (var i = 0; i < inputs.length; i++) {
        var pid = parseInt(inputs[i].dataset.pid);
        var wasActive = activeInput === inputs[i];
        if (itemUpdates[pid] !== undefined) {
            inputs[i].value = itemUpdates[pid];
            applyItemStyles(inputs[i], itemUpdates[pid], group);
        } else {
            inputs[i].value = ''; inputs[i].className = 'item-input';
        }
        if (wasActive) inputs[i].classList.add('active-field');
    }
}

function updateGroupDisplay(groupName) {
    var group = findGroup(groupName); if (!group) return;
    var sid = safeId(groupName);
    var totalEl = document.getElementById('total_' + sid);
    var groupInput = document.getElementById('groupinput_' + sid);
    var total = getGroupTotal(group);
    if (totalEl) {
        if (total === null) {
            totalEl.textContent = 'Учёт: ' + group.total_stock;
            totalEl.className = 'group-total'; totalEl.style.color = '';
        } else {
            var delta = total - group.total_stock, sign = delta >= 0 ? '+' : '';
            totalEl.textContent = 'Σ ' + total + ' (Δ' + sign + delta + ')';
            totalEl.className = 'group-total has-changes';
            if (delta === 0) totalEl.style.color = '#10b981';
            else if (delta < 0) totalEl.style.color = '#ef4444';
            else totalEl.style.color = '#3b82f6';
        }
    }
    if (groupInput) {
        var wasActive = groupInput.classList.contains('active-field');
        groupInput.value = total !== null ? total : '';
        groupInput.className = 'group-input';
        if (wasActive) groupInput.classList.add('active-field');
        if (total !== null) {
            var delta = total - group.total_stock;
            if (delta === 0) groupInput.classList.add('equal');
            else if (delta < 0) groupInput.classList.add('less');
            else groupInput.classList.add('more');
            groupInput.classList.add('modified');
        }
    }
}

function toggleGroup(sid) {
    expandedGroups[sid] = !expandedGroups[sid];
    var container = document.getElementById('items_' + sid);
    var arrow = document.querySelector('#items_' + sid).previousElementSibling.querySelector('.expand-arrow');
    if (container) {
        if (expandedGroups[sid]) container.classList.add('open');
        else container.classList.remove('open');
    }
    if (arrow) arrow.textContent = expandedGroups[sid] ? '▼' : '▶';
}

function updateSyncButton() {
    var btn = document.getElementById('syncBtn');
    var count = Object.keys(itemUpdates).length + Object.keys(singleUpdates).length;
    if (count > 0) { btn.disabled = false; btn.textContent = '📤 Синхронизировать (' + count + ')'; }
    else { btn.disabled = true; btn.textContent = '📤 Синхронизировать'; }
}

function syncData() {
    var itemUpdatesToSend = {};
    for (var pid in manualItemUpdates) itemUpdatesToSend[pid] = manualItemUpdates[pid];
    var groupUpdates = {}, touchedGroups = {};
    for (var pid in manualItemUpdates) { var g = findGroupByProductId(parseInt(pid)); if (g) touchedGroups[g.name] = true; }
    for (var pid in itemUpdates) { var g = findGroupByProductId(parseInt(pid)); if (g) touchedGroups[g.name] = true; }
    for (var gn in touchedGroups) { var g = findGroup(gn); var total = getGroupTotal(g); if (total !== null) groupUpdates[gn] = total; }
    var singleUpdatesToSend = {};
    for (var pid in singleUpdates) singleUpdatesToSend[pid] = singleUpdates[pid];
    addLog('═══════════════════════════════', 'warn');
    addLog('📤 ОТПРАВКА:', 'warn');
    addLog('  Групп: ' + Object.keys(groupUpdates).length, 'info');
    addLog('  Ручных вкусов: ' + Object.keys(itemUpdatesToSend).length, 'info');
    addLog('  Одиночных: ' + Object.keys(singleUpdatesToSend).length, 'info');
    addLog('═══════════════════════════════', 'warn');
    var btn = document.getElementById('syncBtn');
    btn.disabled = true; btn.textContent = '⏳ Отправка...';
    fetch('/api/update_all', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            group_updates: groupUpdates,
            item_updates: itemUpdatesToSend,
            single_updates: singleUpdatesToSend
        })
    })
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function(d) {
        addLog('✓ Принято: ' + d.pending_groups + ' групп, ' + d.pending_items + ' вкусов, ' + d.pending_singles + ' одиночных', 'ok');
        btn.disabled = false; updateSyncButton();
    })
    .catch(function(e) {
        addLog('✗ Ошибка: ' + e.message, 'err');
        btn.disabled = false; updateSyncButton();
    });
}

addLog('Script started v7.2 (калькулятор + адаптация)', 'ok');
addLog('🧮 Калькулятор: нажмите на поле → 🧮 → примените', 'ok');
addLog('🔄 Если товар купили — факт автоматически скорректируется', 'ok');
loadData();
startVersionCheck();
</script>
</body>
</html>"""


sync_server = SyncServer()