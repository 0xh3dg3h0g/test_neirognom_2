# -*- coding: utf-8 -*-
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
load_dotenv(BASE_DIR.parent / ".env")

DEFAULT_TARGET_ID = os.getenv("SIM_TARGET_ID", "tray_1")
DEFAULT_BROKER_HOST = os.getenv("BROKER_HOST", "127.0.0.1")
DEFAULT_BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
DEFAULT_CLIENT_ID = os.getenv("SIM_CLIENT_ID", "neurognome_web_simulator")
DEFAULT_DAY_SCENARIO_DURATION_MS = 15_000


class BrokerConfig(BaseModel):
    host: str = Field(default=DEFAULT_BROKER_HOST, min_length=1)
    port: int = Field(default=DEFAULT_BROKER_PORT, ge=1, le=65535)
    username: str = ""
    password: str = ""
    client_id: str = DEFAULT_CLIENT_ID
    target_id: str = DEFAULT_TARGET_ID
    use_tls: bool = False


class SensorPayload(BaseModel):
    air_temp: float | None = None
    humidity: float | None = None
    water_temp: float | None = None
    ph: float | None = None
    ec: float | None = None
    retain: bool = True


class DeviceCommand(BaseModel):
    device_type: Literal["pump", "light", "fan", "humidifier"]
    state: Literal["ON", "OFF", "TIMER"]
    duration: float | None = None


class DayScenarioCommand(BaseModel):
    duration_ms: int = DEFAULT_DAY_SCENARIO_DURATION_MS
    start_delay_ms: int = 1_200


class SimulatorMode(BaseModel):
    mode: Literal["NORMAL", "HEAT", "COLD"]


class MqttSimulator:
    def __init__(self) -> None:
        self.config = BrokerConfig()
        self.client: mqtt.Client | None = None
        self.connected = False
        self.connection_message = "Отключено"
        self.mode = "NORMAL"
        self.logs: deque[dict[str, Any]] = deque(maxlen=400)
        self.sequence = 0
        self.loop = None
        self.websockets: set[WebSocket] = set()
        self.state_lock = threading.RLock()
        self.ws_lock = threading.Lock()
        self.timers: dict[str, threading.Timer] = {}
        self.day_finish_timer: threading.Timer | None = None
        self.devices = {
            "pump": False,
            "light": False,
            "fan": False,
            "humidifier": False,
        }
        self.day_scenario = {
            "active": False,
            "start_at_ms": None,
            "duration_ms": DEFAULT_DAY_SCENARIO_DURATION_MS,
        }

    def attach_loop(self, loop) -> None:
        self.loop = loop

    def public_config(self) -> dict[str, Any]:
        with self.state_lock:
            return {
                "host": self.config.host,
                "port": self.config.port,
                "username": self.config.username,
                "password": "",
                "has_password": bool(self.config.password),
                "client_id": self.config.client_id,
                "target_id": self.config.target_id,
                "use_tls": self.config.use_tls,
            }

    def log(
        self,
        topic: str,
        payload: str | dict[str, Any],
        direction: Literal["rx", "tx", "system", "error"],
        source: str = "simulator",
    ) -> dict[str, Any]:
        payload_text = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if isinstance(payload, dict)
            else str(payload)
        )
        with self.state_lock:
            self.sequence += 1
            entry = {
                "id": f"log-{int(time.time() * 1000)}-{self.sequence}",
                "timestamp_ms": int(time.time() * 1000),
                "topic": topic,
                "payload": payload_text,
                "direction": direction,
                "source": source,
            }
            self.logs.append(entry)

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._broadcast_from_loop, entry)

        return entry

    def _broadcast_from_loop(self, entry: dict[str, Any]) -> None:
        import asyncio

        asyncio.create_task(self.broadcast(entry))

    def logs_snapshot(self, limit: int = 160) -> list[dict[str, Any]]:
        with self.state_lock:
            return list(self.logs)[-limit:]

    async def register_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        with self.ws_lock:
            self.websockets.add(websocket)

        for entry in self.logs_snapshot(180):
            await websocket.send_json(entry)

    async def unregister_ws(self, websocket: WebSocket) -> None:
        with self.ws_lock:
            self.websockets.discard(websocket)

    async def broadcast(self, entry: dict[str, Any]) -> None:
        with self.ws_lock:
            websockets = tuple(self.websockets)

        stale: list[WebSocket] = []
        for websocket in websockets:
            try:
                await websocket.send_json(entry)
            except Exception:
                stale.append(websocket)

        if stale:
            with self.ws_lock:
                for websocket in stale:
                    self.websockets.discard(websocket)

    def connect(self, config: BrokerConfig) -> dict[str, Any]:
        self.disconnect(publish_offline=False)

        with self.state_lock:
            self.config = config
            self.connected = False
            self.connection_message = "Подключение"
            self._cancel_all_timers()
            self.devices = {key: False for key in self.devices}
            self.day_scenario = {
                "active": False,
                "start_at_ms": None,
                "duration_ms": DEFAULT_DAY_SCENARIO_DURATION_MS,
            }

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.client_id)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.will_set(self.availability_topic(), "offline", qos=0, retain=True)

        if config.username:
            client.username_pw_set(config.username, config.password or None)
        if config.use_tls:
            client.tls_set()

        try:
            client.connect(config.host, config.port, 60)
            client.loop_start()
        except Exception as exc:
            with self.state_lock:
                self.client = None
                self.connected = False
                self.connection_message = str(exc)
            self.log("mqtt/connect", f"Ошибка подключения: {exc}", "error")
            raise HTTPException(status_code=502, detail=f"MQTT connect failed: {exc}") from exc

        with self.state_lock:
            self.client = client

        self.log(
            "mqtt/connect",
            {
                "host": config.host,
                "port": config.port,
                "target_id": config.target_id,
                "client_id": config.client_id,
                "tls": config.use_tls,
            },
            "system",
        )
        return self.snapshot()

    def disconnect(self, publish_offline: bool = True) -> dict[str, Any]:
        with self.state_lock:
            client = self.client
            self.client = None
            self.connected = False
            self.connection_message = "Отключено"
            self._cancel_all_timers()

        if client:
            try:
                if publish_offline:
                    client.publish(self.availability_topic(), "offline", retain=True)
                    self.log(self.availability_topic(), "offline", "tx")
                client.loop_stop()
                client.disconnect()
            except Exception as exc:
                self.log("mqtt/disconnect", f"Ошибка отключения: {exc}", "error")

        return self.snapshot()

    def _cancel_all_timers(self) -> None:
        for timer in self.timers.values():
            timer.cancel()
        self.timers.clear()
        if self.day_finish_timer:
            self.day_finish_timer.cancel()
            self.day_finish_timer = None

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        failed = bool(getattr(reason_code, "is_failure", False))
        if failed:
            with self.state_lock:
                self.connected = False
                self.connection_message = str(reason_code)
            self.log("mqtt/connect", f"Ошибка подключения: {reason_code}", "error")
            return

        topics = [
            "farm/+/cmd/#",
            "farm/+/status/#",
            "farm/+/sensors/#",
            "farm/sim/#",
        ]
        for topic in topics:
            client.subscribe(topic)

        with self.state_lock:
            self.connected = True
            self.connection_message = "Подключено"

        self.log("mqtt/subscriptions", {"topics": topics}, "system")
        self._publish_raw(self.availability_topic(), "online", retain=True)
        self.publish_status()

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        with self.state_lock:
            self.connected = False
            self.connection_message = "Отключено" if str(reason_code) == "Normal disconnection" else str(reason_code)
        self.log("mqtt/disconnect", self.connection_message, "system")

    def _on_message(self, client, userdata, msg) -> None:
        payload = msg.payload.decode("utf-8", errors="replace")
        self.log(msg.topic, payload, "rx", source="mqtt")

        parts = msg.topic.split("/")
        with self.state_lock:
            target_id = self.config.target_id

        if msg.topic == "farm/sim/control":
            normalized = payload.strip().upper()
            if normalized in {"NORMAL", "HEAT", "COLD"}:
                with self.state_lock:
                    self.mode = normalized
            return

        if len(parts) >= 4 and parts[0] == "farm" and parts[1] == target_id:
            if parts[2] == "cmd":
                self.apply_device_command(parts[-1], payload)
            elif parts[2] == "status":
                self.apply_external_status(parts[3], payload)

    def apply_external_status(self, status_type: str, payload: str) -> None:
        if status_type == "availability":
            return
        if status_type != "devices":
            return

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(parsed, dict):
            return

        with self.state_lock:
            for device in self.devices:
                if device in parsed:
                    self.devices[device] = bool(parsed[device])
            if "day_scenario_running" in parsed:
                self.day_scenario["active"] = bool(parsed["day_scenario_running"])
            if parsed.get("day_start_at_ms"):
                self.day_scenario["start_at_ms"] = int(parsed["day_start_at_ms"])
            if parsed.get("day_duration_ms"):
                self.day_scenario["duration_ms"] = int(parsed["day_duration_ms"])

    def apply_device_command(self, device: str, payload: str) -> None:
        if device not in self.devices:
            return

        body = payload.strip()
        if body.startswith("{"):
            self._apply_json_command(device, body)
            return

        normalized = body.upper()
        if normalized == "ON":
            self.set_device(device, True)
        elif normalized == "OFF":
            self.set_device(device, False)
        elif normalized.startswith("TIMER "):
            try:
                seconds = max(0.1, float(normalized.split(" ", 1)[1]))
            except ValueError:
                return
            self.set_device_timer(device, seconds)
        elif device == "light" and normalized in {"DAY", "DAY_SCENARIO"}:
            self.start_day_scenario(now_ms(), DEFAULT_DAY_SCENARIO_DURATION_MS)

    def _apply_json_command(self, device: str, body: str) -> None:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return

        command = str(parsed.get("command", "")).upper()
        if device == "light" and command in {"DAY", "DAY_SCENARIO"}:
            start_at_ms = int(parsed.get("start_at_ms") or (now_ms() + int(parsed.get("start_in_ms") or 0)))
            duration_ms = int(parsed.get("duration_ms") or DEFAULT_DAY_SCENARIO_DURATION_MS)
            self.start_day_scenario(start_at_ms, duration_ms)
        elif command in {"ON", "OFF"}:
            self.set_device(device, command == "ON")
        elif command == "TIMER":
            self.set_device_timer(device, float(parsed.get("duration") or 1))

    def set_device(self, device: str, enabled: bool) -> None:
        with self.state_lock:
            self.devices[device] = enabled
            timer = self.timers.pop(device, None)
            if timer:
                timer.cancel()
            if device == "light" and not enabled:
                self.day_scenario["active"] = False
        self.publish_status()

    def set_device_timer(self, device: str, seconds: float) -> None:
        with self.state_lock:
            timer = self.timers.pop(device, None)
            if timer:
                timer.cancel()
            self.devices[device] = True
            next_timer = threading.Timer(seconds, lambda: self.set_device(device, False))
            next_timer.daemon = True
            self.timers[device] = next_timer
            next_timer.start()
        self.publish_status()

    def start_day_scenario(self, start_at_ms: int, duration_ms: int) -> None:
        duration_ms = max(1_000, min(int(duration_ms), 24 * 60 * 60 * 1000))
        with self.state_lock:
            if self.day_finish_timer:
                self.day_finish_timer.cancel()
            self.devices["light"] = True
            self.day_scenario = {
                "active": True,
                "start_at_ms": int(start_at_ms),
                "duration_ms": duration_ms,
            }
            delay_seconds = max(0.1, (int(start_at_ms) + duration_ms - now_ms()) / 1000)
            self.day_finish_timer = threading.Timer(delay_seconds, self.finish_day_scenario)
            self.day_finish_timer.daemon = True
            self.day_finish_timer.start()
        self.publish_status()

    def finish_day_scenario(self) -> None:
        with self.state_lock:
            self.devices["light"] = False
            self.day_scenario["active"] = False
            self.day_finish_timer = None
        self.publish_status()

    def publish_sensors(self, payload: SensorPayload) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []

        climate: dict[str, float] = {}
        if payload.air_temp is not None:
            climate["air_temp"] = round(float(payload.air_temp), 2)
        if payload.humidity is not None:
            climate["humidity"] = round(float(payload.humidity), 2)
        if climate:
            topic = self.topic("sensors/climate")
            self._publish_json(topic, climate, retain=payload.retain)
            messages.append({"topic": topic, "payload": climate})

        water: dict[str, float] = {}
        if payload.water_temp is not None:
            water["water_temp"] = round(float(payload.water_temp), 2)
        if payload.ph is not None:
            water["ph"] = round(float(payload.ph), 2)
        if payload.ec is not None:
            water["ec"] = round(float(payload.ec), 2)
        if water:
            topic = self.topic("sensors/water")
            self._publish_json(topic, water, retain=payload.retain)
            messages.append({"topic": topic, "payload": water})

        if not messages:
            raise HTTPException(status_code=400, detail="Нет данных для публикации")

        return {"status": "sent", "messages": messages}

    def send_device_command(self, command: DeviceCommand) -> dict[str, Any]:
        payload = command.state
        if command.state == "TIMER" and command.duration:
            payload = f"TIMER {command.duration:g}"
        topic = self.topic(f"cmd/{command.device_type}")
        self._publish_raw(topic, payload)
        self.apply_device_command(command.device_type, payload)
        return {"status": "sent", "topic": topic, "payload": payload}

    def send_mode(self, mode: str) -> dict[str, Any]:
        self._publish_raw("farm/sim/control", mode)
        with self.state_lock:
            self.mode = mode
        return {"status": "sent", "topic": "farm/sim/control", "payload": mode}

    def send_day_scenario(self, command: DayScenarioCommand) -> dict[str, Any]:
        start_delay_ms = max(0, min(int(command.start_delay_ms), 60_000))
        duration_ms = max(1_000, min(int(command.duration_ms), 24 * 60 * 60 * 1000))
        start_at_ms = now_ms() + start_delay_ms
        payload = {
            "command": "DAY_SCENARIO",
            "start_at_ms": start_at_ms,
            "start_in_ms": start_delay_ms,
            "duration_ms": duration_ms,
            "stage_count": 10,
        }
        topic = self.topic("cmd/light")
        self._publish_json(topic, payload)
        self.start_day_scenario(start_at_ms, duration_ms)
        return {"status": "sent", "topic": topic, "payload": payload}

    def publish_status(self) -> None:
        self._publish_json(self.topic("status/devices"), self.device_status(), retain=True)

    def device_status(self) -> dict[str, Any]:
        with self.state_lock:
            devices = dict(self.devices)
            active = bool(self.day_scenario["active"])
            start_at_ms = self.day_scenario["start_at_ms"]
            duration_ms = int(self.day_scenario["duration_ms"])

        stage = 9
        pending = False
        if active and isinstance(start_at_ms, int):
            elapsed = now_ms() - start_at_ms
            pending = elapsed < 0
            if elapsed >= duration_ms:
                with self.state_lock:
                    self.devices["light"] = False
                    self.day_scenario["active"] = False
                active = False
                devices["light"] = False
            elif elapsed >= 0:
                stage = min(9, max(0, int((elapsed / duration_ms) * 9)))
            else:
                stage = 0

        return {
            **devices,
            "day_scenario_running": active,
            "day_scenario_pending": pending,
            "day_stage": stage,
            "day_start_at_ms": start_at_ms,
            "day_duration_ms": duration_ms,
            "uptime_ms": int(time.monotonic() * 1000),
        }

    def snapshot(self) -> dict[str, Any]:
        with self.state_lock:
            connected = self.connected
            message = self.connection_message
            mode = self.mode

        return {
            "connected": connected,
            "connection_message": message,
            "mode": mode,
            "config": self.public_config(),
            "devices": self.device_status(),
            "server_now_ms": now_ms(),
        }

    def topic(self, suffix: str) -> str:
        with self.state_lock:
            return f"farm/{self.config.target_id}/{suffix}"

    def availability_topic(self) -> str:
        return self.topic("status/availability")

    def _publish_json(self, topic: str, payload: dict[str, Any], retain: bool = False) -> None:
        self._publish_raw(topic, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), retain=retain)

    def _publish_raw(self, topic: str, payload: str, retain: bool = False) -> None:
        with self.state_lock:
            client = self.client
            connected = self.connected
        if not client or not connected:
            raise HTTPException(status_code=409, detail="MQTT broker is not connected")
        client.publish(topic, payload, retain=retain)
        self.log(topic, payload, "tx")


def now_ms() -> int:
    return int(time.time() * 1000)


simulator = MqttSimulator()
app = FastAPI(title="Neurognome MQTT Simulator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def on_startup() -> None:
    import asyncio

    simulator.attach_loop(asyncio.get_running_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    simulator.disconnect()
    simulator.attach_loop(None)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> dict[str, Any]:
    return simulator.snapshot()


@app.get("/api/logs")
def logs(limit: int = Query(default=180, ge=1, le=400)) -> list[dict[str, Any]]:
    return simulator.logs_snapshot(limit)


@app.post("/api/connect")
def connect(config: BrokerConfig) -> dict[str, Any]:
    return simulator.connect(config)


@app.post("/api/disconnect")
def disconnect() -> dict[str, Any]:
    return simulator.disconnect()


@app.post("/api/sensors")
def sensors(payload: SensorPayload) -> dict[str, Any]:
    return simulator.publish_sensors(payload)


@app.post("/api/device/control")
def device_control(command: DeviceCommand) -> dict[str, Any]:
    return simulator.send_device_command(command)


@app.post("/api/light/day")
def light_day(command: DayScenarioCommand) -> dict[str, Any]:
    return simulator.send_day_scenario(command)


@app.post("/api/simulator/mode")
def simulator_mode(mode: SimulatorMode) -> dict[str, Any]:
    return simulator.send_mode(mode.mode)


@app.websocket("/api/ws")
async def websocket_logs(websocket: WebSocket) -> None:
    await simulator.register_ws(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await simulator.unregister_ws(websocket)
