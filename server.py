import json
import logging
import threading
import time
from datetime import datetime
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from tools import TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("smart-home-mcp-openhab")


with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

prostorije = config["prostorije"]
pragovi = config.get("pragovi", {})
TEMP_MAX = pragovi.get("temperatura_max", 28)
TEMP_MIN = pragovi.get("temperatura_min", 18)
TERMOSTAT_DEFAULT = pragovi.get("termostat_default", 21)
HISTORY_SIZE = config.get("agent", {}).get("action_history_size", 50)

# openHAB konfiguracija
OPENHAB_URL = "http://localhost:8090/rest"
CACHE_TTL = config.get("agent", {}).get("openhab_cache_ttl", 8)  # sekunde

# Thread-safe state 
action_lock = threading.Lock()
action_history: deque = deque(maxlen=HISTORY_SIZE)

_cache_lock = threading.Lock()
_items_cache: dict = {}      # item_name -> state
_cache_timestamp: float = 0.0


def record_action(tool_name: str, args: dict, result: str):
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "tool": tool_name,
        "args": args,
        "result": result[:200]
    }
    with action_lock:
        action_history.appendleft(entry)


def _get_item_name(prostorija: str, uredjaj: str) -> str:
    """
    Vraća stvarni openHAB Item naziv za dati uređaj.

    Prvo pokušava pročitati eksplicitno mapiranje iz config.json
    ("item_name" polje) — to je najpouzdanije jer openHAB često
    ne generiše Item ime po istoj konvenciji kao Channel ID
    (npr. izvodi ga iz Channel Label-a, sa dodatnim underscore-ima
    ili potpuno drugim riječima).

    Ako "item_name" nije naveden za taj uređaj, koristi se stara
    konvencija (PascalCase spajanje) kao fallback, radi kompatibilnosti
    sa prostorijama koje još nisu ažurirane u config.json.
    """
    device_cfg = prostorije.get(prostorija, {}).get(uredjaj, {})
    item_name = device_cfg.get("item_name")
    if item_name:
        return item_name

    logger.warning(
        f"'item_name' nije definisan za {prostorija}.{uredjaj} u config.json — "
        f"koristim fallback konvenciju (provjeri da li se poklapa sa stvarnim openHAB Itemom!)."
    )
    prostorija_camel = "".join(part.capitalize() for part in prostorija.split("_"))
    uredjaj_camel = "".join(part.capitalize() for part in uredjaj.split("_"))
    return f"{prostorija_camel}_{uredjaj_camel}"


def _fetch_all_items() -> dict:
    """
    Dohvati SVE Iteme u jednom HTTP pozivu preko /rest/items
    (umjesto N pojedinačnih poziva po uređaju).
    """
    try:
        resp = requests.get(f"{OPENHAB_URL}/items", timeout=8)
        if resp.status_code != 200:
            logger.error(f"openHAB /items vratio status {resp.status_code}")
            return {}
        items = resp.json()
        return {item["name"]: str(item.get("state", "N/A")) for item in items}
    except Exception as e:
        logger.error(f"Greška pri bulk čitanju iz openHAB-a: {e}")
        return {}


def _get_items_snapshot(force: bool = False) -> dict:
    """
    Vraća cache-ovan snapshot svih Itema. Osvježava samo ako je cache
    stariji od CACHE_TTL sekundi (ili ako je force=True), umjesto da
    svaki tool-poziv gađa openHAB iznova.
    """
    global _items_cache, _cache_timestamp
    with _cache_lock:
        age = time.time() - _cache_timestamp
        if force or age > CACHE_TTL or not _items_cache:
            fresh = _fetch_all_items()
            if fresh:  # ne gazi cache praznim rezultatom ako openHAB nakratko ne odgovori
                _items_cache = fresh
                _cache_timestamp = time.time()
        return dict(_items_cache)


def invalidate_cache():
    """Pozvati nakon svake write komande da sljedeće čitanje bude svježe."""
    global _cache_timestamp
    with _cache_lock:
        _cache_timestamp = 0.0


def _send_openhab_command(item_name: str, command: str) -> bool:
    """Šalje komandu (POST) na openHAB Item."""
    try:
        headers = {"Content-Type": "text/plain"}
        resp = requests.post(f"{OPENHAB_URL}/items/{item_name}", data=str(command), headers=headers, timeout=5)
        ok = resp.status_code in {200, 201, 202}
        if ok:
            invalidate_cache()
        return ok
    except Exception as e:
        logger.error(f"Greška pri slanju komande na openHAB ({item_name}): {e}")
        return False


def execute_tool(name: str, args: dict) -> str:
    result = _execute(name, args)
    record_action(name, args, result)
    return result


def _execute(name: str, args: dict) -> str:

    if name == "get_all_sensors":
        snapshot = _get_items_snapshot()
        lines = []
        for prostorija, uredjaji in prostorije.items():
            for uredjaj in uredjaji.keys():
                item_name = _get_item_name(prostorija, uredjaj)
                state = snapshot.get(item_name, "N/A")
                lines.append(f"{item_name}: {state}")
        if not lines:
            return "Nema definisanih uređaja u konfiguraciji."
        return "\n".join(sorted(lines))

    elif name == "get_room_status":
        prostorija = args.get("prostorija")
        if prostorija not in prostorije:
            return f"Prostorija '{prostorija}' nije pronađena. Dostupne: {list(prostorije.keys())}"

        snapshot = _get_items_snapshot()
        lines = [f"Stanje prostorije: {prostorija}"]
        for naziv, info in prostorije[prostorija].items():
            item_name = _get_item_name(prostorija, naziv)
            state = snapshot.get(item_name, "N/A")
            lines.append(f"  {naziv} ({info['opis']}): {state}")
        return "\n".join(lines)

    elif name == "set_svjetlo":
        prostorija = args.get("prostorija")
        komanda = args.get("komanda")
        item_name = _get_item_name(prostorija, "svjetlo")
        ok = _send_openhab_command(item_name, komanda)
        return f"Svjetlo [{item_name}] → {komanda}" if ok else f"Greška pri slanju komande openHAB-u za {item_name}."

    elif name == "set_ventilator":
        prostorija = args.get("prostorija")
        komanda = args.get("komanda")
        item_name = _get_item_name(prostorija, "ventilator")
        ok = _send_openhab_command(item_name, komanda)
        return f"Ventilator [{item_name}] → {komanda}" if ok else f"Greška pri slanju komande openHAB-u za {item_name}."

    elif name == "set_prozor":
        prostorija = args.get("prostorija")
        komanda = args.get("komanda")
        item_name = _get_item_name(prostorija, "prozor")
        ok = _send_openhab_command(item_name, komanda)
        return f"Prozor [{item_name}] → {komanda}" if ok else f"Greška pri slanju komande openHAB-u za {item_name}."

    elif name == "set_termostat":
        prostorija = args.get("prostorija")
        temperatura = args.get("temperatura")
        if temperatura is None:
            return "Greška: temperatura nije navedena."
        item_name = _get_item_name(prostorija, "termostat")
        ok = _send_openhab_command(item_name, str(temperatura))
        return f"Termostat [{item_name}] → {temperatura}°C" if ok else f"Greška pri postavljanju termostata na openHAB-u za {item_name}."

    elif name == "detect_anomalies":
        snapshot = _get_items_snapshot()
        TRUTHY = {True, "true", "True", "ON", 1, "1", "detected", "OPEN"}
        kritično, upozorenja = [], []

        for prostorija, uredjaji in prostorije.items():
            for uredjaj in uredjaji.keys():
                item_name = _get_item_name(prostorija, uredjaj)
                value = snapshot.get(item_name, "N/A")

                if "senzor_dima" in uredjaj and value in TRUTHY:
                    kritično.append(f"DIM DETEKTOVAN: {item_name}")

                if "senzor_temperature" in uredjaj:
                    try:
                        temp = float(value)
                        if temp > TEMP_MAX:
                            upozorenja.append(f"Visoka temperatura ({temp:.1f}°C): {item_name}")
                        elif temp < TEMP_MIN:
                            upozorenja.append(f"Niska temperatura ({temp:.1f}°C): {item_name}")
                    except (ValueError, TypeError):
                        pass

                if "prozor" in uredjaj and value in TRUTHY:
                    upozorenja.append(f"Otvoren prozor: {item_name}")

                if "senzor_pokreta" in uredjaj and value in TRUTHY:
                    upozorenja.append(f"Pokret detektovan: {item_name}")

        if not kritično and not upozorenja:
            return "Nema anomalija. Sve je u redu."

        lines = []
        if kritično:
            lines.append("KRITIČNO")
            lines.extend(kritično)
        if upozorenja:
            lines.append("UPOZORENJA")
            lines.extend(upozorenja)
        return "\n".join(lines)

    elif name == "upravljaj_uredjajem":
        item_name = args.get("item_name")
        komanda = args.get("komanda")
        if not item_name or komanda is None:
            return "Greška: item_name i komanda su obavezni."
        ok = _send_openhab_command(item_name, komanda)
        return f"Direktna komanda: {item_name} → {komanda}" if ok else f"Greška pri slanju na openHAB Item {item_name}."

    elif name == "get_action_history":
        n = int(args.get("n", 10))
        with action_lock:
            recent = list(action_history)[:n]
        if not recent:
            return "Nema zabilježenih akcija u ovoj sesiji."
        lines = [f"Zadnjih {len(recent)} akcija:"]
        for entry in recent:
            lines.append(
                f"  [{entry['time']}] {entry['tool']}({json.dumps(entry['args'], ensure_ascii=False)}) "
                f"→ {entry['result'][:80]}"
            )
        return "\n".join(lines)

    return f"Nepoznat tool: '{name}'"


class MCPHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _send_json(self, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            })
            return

        method = data.get("method")
        req_id = data.get("id")
        logger.info(f"MCP ← {method}")

        if method == "initialize":
            self._send_json({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "SmartHome-openHAB", "version": "4.1"}
                }
            })

        elif method == "notifications/initialized":
            self._send_json({"jsonrpc": "2.0", "id": req_id, "result": {}})

        elif method == "tools/list":
            self._send_json({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"tools": TOOLS}
            })

        elif method == "tools/call":
            params = data.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result_text = execute_tool(tool_name, arguments)
            self._send_json({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result_text}]
                }
            })

        else:
            self._send_json({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}
            })


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 5000), MCPHandler)
    logger.info("SmartHome MCP openHAB Server v4.1 → http://0.0.0.0:5000")
    logger.info(f"Povezivanje na openHAB REST API: {OPENHAB_URL}")
    logger.info(f"Prostorije iz config.json: {list(prostorije.keys())}")
    logger.info(f"Cache TTL za openHAB čitanja: {CACHE_TTL}s")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server zaustavljen.")