import json
import sqlite3
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import paho.mqtt.client as mqtt
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "farm.db"
BROKER_HOST = "31.56.208.196"
BROKER_PORT = 1883
SENSORS_TOPIC = "farm/+/sensors/#"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
KNOWN_SENSOR_TOPICS = {
    "farm/tray_1/sensors/climate",
    "farm/tray_1/sensors/water",
}
KNOWN_DEVICE_TYPES = {"pump", "light", "fan"}


def get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    with get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                status TEXT,
                last_seen DATETIME
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT,
                payload TEXT,
                timestamp DATETIME
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                thought TEXT,
                commands_json TEXT
            )
            """
        )
        connection.commit()


def current_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_json_payload(payload: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict):
        return parsed

    return None


def update_device_status(device_id: str) -> None:
    last_seen = current_timestamp()
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO devices (id, status, last_seen)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                last_seen = excluded.last_seen
            """,
            (device_id, "online", last_seen),
        )
        connection.commit()


def save_telemetry(topic: str, payload: str) -> None:
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO telemetry (topic, payload, timestamp)
            VALUES (?, ?, ?)
            """,
            (topic, payload, current_timestamp()),
        )
        connection.commit()


def save_ai_log(thought: str, commands: list[dict[str, Any]]) -> None:
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO ai_logs (timestamp, thought, commands_json)
            VALUES (?, ?, ?)
            """,
            (current_timestamp(), thought, json.dumps(commands, ensure_ascii=False)),
        )
        connection.commit()


def get_recent_telemetry(limit: int = 15) -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, topic, payload, timestamp
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    records: list[dict[str, Any]] = []
    for row in reversed(rows):
        record = dict(row)
        record["parsed_payload"] = parse_json_payload(str(record["payload"]))
        records.append(record)
    return records


def get_recent_ai_logs(limit: int = 50) -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, timestamp, thought, commands_json
            FROM ai_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def strip_markdown_backticks(raw_text: str) -> str:
    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned[3:].lstrip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip(" \n\r\t:")
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

    cleaned = cleaned.strip("`").strip()

    if cleaned.lower().startswith("json"):
        candidate = cleaned[4:].lstrip(" \n\r\t:")
        if candidate.startswith("{") or candidate.startswith("["):
            cleaned = candidate

    return cleaned.replace("```", "").strip()


def call_ollama(prompt: str, *, format_json: bool) -> str:
    request_payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    if format_json:
        request_payload["format"] = "json"

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=40) as response:
        response_body = response.read().decode("utf-8")

    parsed_response = json.loads(response_body)
    raw_text = str(parsed_response.get("response", ""))
    return strip_markdown_backticks(raw_text)


def build_decision_prompt(records: list[dict[str, Any]]) -> str:
    telemetry_json = json.dumps(records, ensure_ascii=False, indent=2)
    return (
        "Ты — Нейроагроном, автономный агент управления городской фермой.\n"
        "У тебя есть данные с датчиков и история предыдущих замеров.\n"
        "ПРАВИЛА ПРИНЯТИЯ РЕШЕНИЙ:\n\n"
        "Если температура воздуха (air_temp) > 28°C — включи вентилятор (fan).\n"
        "Если влажность (humidity) < 50% — включи насос на 5 секунд (pump, duration: 5).\n"
        "Если температура воды (water_temp) < 18°C — включи свет для обогрева (light).\n"
        "Если все показатели в норме — не включай ничего.\n"
        "Анализируй динамику: если температура быстро растёт (разница > 2°C за 3 замера) — это тревожный знак.\n\n"
        "Отвечай ТОЛЬКО валидным JSON без markdown-обёрток:\n"
        "{\n"
        '"thought": "Краткое объяснение решения на русском языке",\n'
        '"commands": [\n'
        '{"device_type": "fan", "state": "ON"},\n'
        '{"device_type": "pump", "state": "TIMER", "duration": 5}\n'
        "]\n"
        "}\n"
        "Если действий не требуется — возвращай пустой массив commands.\n\n"
        "Последние записи телеметрии:\n"
        f"{telemetry_json}"
    )


def build_chat_prompt(
    message: str,
    telemetry_records: list[dict[str, Any]],
    ai_log_records: list[dict[str, Any]],
) -> str:
    telemetry_json = json.dumps(telemetry_records, ensure_ascii=False, indent=2)
    ai_logs_json = json.dumps(ai_log_records, ensure_ascii=False, indent=2)
    return (
        "Ты — Нейроагроном, умный ИИ-агроном городской фермы. "
        "Отвечай на вопросы пользователя только на основе реальных данных с датчиков "
        "и своих предыдущих решений. Не выдумывай. Если данных нет — скажи об этом.\n\n"
        "Последние 5 записей телеметрии:\n"
        f"{telemetry_json}\n\n"
        "Последние 3 записи журнала решений ИИ:\n"
        f"{ai_logs_json}\n\n"
        "Вопрос пользователя:\n"
        f"{message}\n\n"
        "Ответь кратко, понятно и только на русском языке."
    )


def normalize_commands(raw_commands: Any) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    logs: list[str] = []

    if not isinstance(raw_commands, list):
        return normalized, ["Поле commands в ответе модели имеет неверный формат."]

    for raw_command in raw_commands:
        if not isinstance(raw_command, dict):
            logs.append(f"Пропущена некорректная команда: {raw_command!r}")
            continue

        device_type = str(raw_command.get("device_type", "")).strip()
        state = str(raw_command.get("state", "")).strip().upper()

        if device_type not in KNOWN_DEVICE_TYPES:
            logs.append(f"Пропущена команда с неизвестным устройством: {raw_command!r}")
            continue

        if state not in {"ON", "OFF", "TIMER"}:
            logs.append(f"Пропущена команда с неверным состоянием: {raw_command!r}")
            continue

        command: dict[str, Any] = {
            "device_type": device_type,
            "state": state,
        }

        duration = raw_command.get("duration")
        if state == "TIMER":
            if not isinstance(duration, (int, float)) or duration <= 0:
                logs.append(f"Пропущена TIMER-команда без корректной duration: {raw_command!r}")
                continue
            command["duration"] = float(duration)

        normalized.append(command)

    return normalized, logs


def publish_ai_command(command: dict[str, Any]) -> str:
    device_type = str(command["device_type"])
    state = str(command["state"])
    topic = f"farm/tray_1/cmd/{device_type}"

    if state == "TIMER":
        duration = command["duration"]
        payload = f"TIMER {duration:g}"
        action = f"Опубликована команда: {device_type} -> TIMER {duration:g}"
    else:
        payload = state
        action = f"Опубликована команда: {device_type} -> {state}"

    app.state.mqtt_client.publish(topic, payload)
    return f"{action} в топик {topic}"


def on_connect(client, userdata, flags, reason_code, properties) -> None:
    if reason_code == 0:
        client.subscribe(SENSORS_TOPIC)
    else:
        print(f"[БЭКЕНД] Ошибка подключения к MQTT: {reason_code}")


def on_message(client, userdata, msg) -> None:
    payload = msg.payload.decode("utf-8")
    parts = msg.topic.split("/")

    if "sensors" in msg.topic and msg.topic in KNOWN_SENSOR_TOPICS:
        save_telemetry(msg.topic, payload)

    if len(parts) >= 3:
        device_id = parts[1]
        update_device_status(device_id)
        print(f"[БЭКЕНД] Данные от {device_id}: {payload}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="backend_service")
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(BROKER_HOST, BROKER_PORT, 60)
    mqtt_client.loop_start()

    app.state.mqtt_client = mqtt_client

    try:
        yield
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DeviceControlRequest(BaseModel):
    target_id: str
    device_type: Literal["pump", "light", "fan"]
    state: Literal["ON", "OFF", "TIMER"]
    duration: float | None = None


class ChatRequest(BaseModel):
    message: str


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok", "db": "initialized"}


@app.post("/api/device/control")
def control_device(request: DeviceControlRequest) -> dict[str, str]:
    topic = f"farm/{request.target_id}/cmd/{request.device_type}"
    payload = request.state

    if request.state == "TIMER" and request.duration is not None:
        payload = f"TIMER {request.duration:g}"

    app.state.mqtt_client.publish(topic, payload)
    return {
        "status": "sent",
        "target_id": request.target_id,
        "device_type": request.device_type,
        "state": request.state,
        "payload": payload,
    }


@app.post("/api/ai/decide")
def ai_decide() -> dict[str, Any]:
    logs: list[str] = []
    telemetry_records = get_recent_telemetry(15)

    if not telemetry_records:
        return {"logs": ["В базе нет записей телеметрии."], "thought": "", "commands": []}

    try:
        raw_decision = call_ollama(build_decision_prompt(telemetry_records), format_json=True)
        decision = json.loads(raw_decision)
    except Exception as exc:
        return {
            "logs": [f"Не удалось получить корректное решение от Ollama: {exc}"],
            "thought": "",
            "commands": [],
        }

    if not isinstance(decision, dict):
        return {
            "logs": ["Модель вернула ответ не в формате JSON-объекта."],
            "thought": "",
            "commands": [],
        }

    thought = str(decision.get("thought", "")).strip()
    normalized_commands, normalization_logs = normalize_commands(decision.get("commands", []))
    logs.extend(normalization_logs)

    if thought:
        logs.insert(0, f"Мысль Нейроагронома: {thought}")
    else:
        thought = "Модель не дала пояснения."
        logs.insert(0, f"Мысль Нейроагронома: {thought}")

    save_ai_log(thought, normalized_commands)

    if not normalized_commands:
        logs.append("Действия не требуются.")
        return {"logs": logs, "thought": thought, "commands": normalized_commands}

    for command in normalized_commands:
        logs.append(publish_ai_command(command))

    return {"logs": logs, "thought": thought, "commands": normalized_commands}


@app.get("/api/logs")
def get_logs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return get_recent_ai_logs(limit)


@app.post("/api/chat")
def chat_with_ai(request: ChatRequest) -> dict[str, str]:
    telemetry_records = get_recent_telemetry(5)
    ai_log_records = get_recent_ai_logs(3)
    prompt = build_chat_prompt(request.message, telemetry_records, ai_log_records)

    try:
        reply = call_ollama(prompt, format_json=False)
    except Exception as exc:
        return {"reply": f"Не удалось получить ответ от Ollama: {exc}"}

    if not reply:
        reply = "Недостаточно данных для ответа."

    return {"reply": reply}
