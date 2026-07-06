import json
import os
import sys
import time
import logging
import threading

import requests
from groq import Groq
from dotenv import load_dotenv

from system_prompt import get_system_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("smarthome-agent")

load_dotenv()

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

agent_cfg = config.get("agent", {})

MCP_URL = "http://localhost:5000"
GROQ_MODEL = "llama-3.3-70b-versatile"
POLL_INTERVAL = agent_cfg.get("poll_interval", 30)
MAX_ITERATIONS = agent_cfg.get("max_iterations", 10)
ACTION_COOLDOWN = agent_cfg.get("action_cooldown", 300)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
if not GROQ_API_KEY:
    raise EnvironmentError(
        "GROQ_API_KEY nije postavljen! "
        "Postavi ga kao env varijablu: export GROQ_API_KEY=gsk_..."
    )

groq_client = Groq(api_key=GROQ_API_KEY)

_cooldown_lock = threading.Lock()
_last_actions: dict[str, float] = {}


def _cooldown_key(tool_name: str, args: dict) -> str:
    prostorija = args.get("prostorija", "")
    komanda = args.get("komanda", args.get("temperatura", ""))
    return f"{tool_name}:{prostorija}:{komanda}"


def is_on_cooldown(tool_name: str, args: dict) -> bool:
    if tool_name in {"get_all_sensors", "get_room_status", "detect_anomalies", "get_action_history"}:
        return False
    key = _cooldown_key(tool_name, args)
    with _cooldown_lock:
        last = _last_actions.get(key, 0)
        return (time.time() - last) < ACTION_COOLDOWN


def mark_executed(tool_name: str, args: dict):
    key = _cooldown_key(tool_name, args)
    with _cooldown_lock:
        _last_actions[key] = time.time()

_req_id = 0
_req_lock = threading.Lock()


def mcp_request(method: str, params: dict = None, retries: int = 3, delay: float = 2.0) -> dict:
    global _req_id
    with _req_lock:
        _req_id += 1
        req_id = _req_id

    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {}
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(MCP_URL, json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.error(f"MCP greška ({method}): {data['error']}")
                return {}
            return data.get("result", {})
        except requests.exceptions.ConnectionError:
            logger.warning(f"MCP nedostupan — pokušaj {attempt}/{retries}")
            if attempt < retries:
                time.sleep(delay)
        except requests.exceptions.Timeout:
            logger.warning(f"MCP timeout ({method}) — pokušaj {attempt}/{retries}")
            if attempt < retries:
                time.sleep(delay)
        except Exception as e:
            logger.error(f"MCP zahtjev neuspješan ({method}): {e}")
            return {}

    logger.error(f"MCP nedostupan nakon {retries} pokušaja ({method}).")
    return {}


def get_sensor_snapshot() -> dict:
    """Dohvati trenutno stanje senzora direktno preko MCP alata (za diff provjeru)."""
    result = mcp_request("tools/call", {
        "name": "get_all_sensors",
        "arguments": {}
    })
    contents = result.get("content", [])
    text = "\n".join(c.get("text", "") for c in contents if c.get("type") == "text")
    return text


def get_mcp_tools() -> list:
    result = mcp_request("tools/list")
    return result.get("tools", [])


def call_mcp_tool(tool_name: str, arguments: dict) -> str:
    result = mcp_request("tools/call", {
        "name": tool_name,
        "arguments": arguments
    })
    contents = result.get("content", [])
    return "\n".join(c.get("text", "") for c in contents if c.get("type") == "text")


def mcp_tool_to_groq(mcp_tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": mcp_tool["name"],
            "description": mcp_tool["description"],
            "parameters": mcp_tool["inputSchema"]
        }
    }


def run_agent_turn(user_message: str, mcp_tools: list) -> str:
    """
    Jedan krug: šalje poruku Groq-u, obrađuje tool pozive i vraća konačni odgovor.
    """
    groq_tools = [mcp_tool_to_groq(t) for t in mcp_tools]
    system_prompt = get_system_prompt(config)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    logger.info(f"Šaljem Groq-u: {user_message[:80]}…")

    for iteration in range(MAX_ITERATIONS):
        try:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                tools=groq_tools,
                tool_choice="auto",
                max_tokens=768,
            )
        except Exception as e:
            logger.error(f"Groq API greška: {e}")
            return f"Greška pri komunikaciji s Groq API-jem: {e}"

        message = response.choices[0].message

        # Dodaj odgovor modela u historiju (bez null tool_calls)
        assistant_msg: dict = {
            "role": "assistant",
            "content": message.content or "",
        }
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in message.tool_calls
            ]
        messages.append(assistant_msg)

        # Nema tool poziva, agent je gotov
        if not message.tool_calls:
            logger.info(f"Agent završio u {iteration + 1} iteracija.")
            return message.content or "(bez odgovora)"

        # Izvrši sve tražene tool pozive
        for tool_call in message.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            # Provjeri cooldown
            if is_on_cooldown(fn_name, fn_args):
                remaining = ACTION_COOLDOWN - (time.time() - _last_actions.get(
                    _cooldown_key(fn_name, fn_args), 0))
                tool_result = (
                    f"Akcija '{fn_name}' je nedavno već izvršena. "
                    f"Cooldown: još {remaining:.0f}s. Preskačem."
                )
                logger.info(f"Cooldown: {fn_name}({fn_args}) — preskačem.")
            else:
                logger.info(f"Tool poziv: {fn_name}({fn_args})")
                tool_result = call_mcp_tool(fn_name, fn_args)
                mark_executed(fn_name, fn_args)
                logger.info(f"Tool rezultat: {tool_result[:120]}…")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result
            })

    logger.warning(f"Agent nije završio u {MAX_ITERATIONS} koraka.")
    return f"(Agent nije završio u dozvoljenom broju koraka: {MAX_ITERATIONS})"


def autonomous_monitor(mcp_tools: list):
    logger.info(f"Autonomni nadzor pokrenut (interval: {POLL_INTERVAL}s)")
    consecutive_errors = 0
    last_snapshot = None
    UNCHANGED_LIMIT = 5  # nakon ovoliko nepromijenjenih ciklusa, ipak provjeri LLM-om (safety-net)
    unchanged_count = 0

    while True:
        try:
            snapshot = get_sensor_snapshot()

            if snapshot == last_snapshot and unchanged_count < UNCHANGED_LIMIT:
                unchanged_count += 1
                logger.info(
                    f"Stanje senzora nepromijenjeno — preskačem Groq poziv "
                    f"({unchanged_count}/{UNCHANGED_LIMIT})."
                )
                time.sleep(POLL_INTERVAL)
                continue

            last_snapshot = snapshot
            unchanged_count = 0

            prompt = (
                "Provjeri trenutno stanje svih senzora u kući. "
                "Na osnovu stanja donesi sve potrebne odluke i izvrši akcije. "
                "Provjeri historiju akcija da ne ponavljaš iste komande. "
                "Prijavi šta si uradio i zašto."
            )
            odgovor = run_agent_turn(prompt, mcp_tools)
            consecutive_errors = 0
            print("\n" + "=" * 60)
            print("[AUTONOMNI AGENT]")
            print(odgovor)
            print("=" * 60 + "\n")
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Greška u autonomnom modu (#{consecutive_errors}): {e}")
            if consecutive_errors >= 5:
                logger.critical("5 uzastopnih grešaka — pauziram 5 minuta.")
                time.sleep(300)
                consecutive_errors = 0

        time.sleep(POLL_INTERVAL)


def interactive_mode(mcp_tools: list):
    print("\nSmartHome Agent — interaktivni mod")
    print(f"Model: {GROQ_MODEL} | MCP: {MCP_URL}")
    print("Upiši 'exit' za izlaz, 'auto' za autonomni nadzor.\n")

    while True:
        try:
            user_input = input("Ti: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDoviđenja!")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            print("Doviđenja!")
            break
        if user_input.lower() == "auto":
            autonomous_monitor(mcp_tools)
            break

        odgovor = run_agent_turn(user_input, mcp_tools)
        print(f"\nAgent: {odgovor}\n")


if __name__ == "__main__":
    logger.info("Inicijalizacija MCP sesije…")
    mcp_request("initialize")
    mcp_request("notifications/initialized")

    mcp_tools = get_mcp_tools()
    if not mcp_tools:
        logger.warning("MCP server nije vratio alate. Provjeri da li je server.py pokrenut.")
    else:
        logger.info(f"Učitano {len(mcp_tools)} alata: {[t['name'] for t in mcp_tools]}")

    if "--auto" in sys.argv:
        autonomous_monitor(mcp_tools)
    else:
        interactive_mode(mcp_tools)