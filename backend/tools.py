import sqlite3
import os
import json

DB_PATH = os.getenv("DB_PATH", "farm.db")
CROPS_DIR = "crops_data"
CLIMATE_TOPIC = "farm/tray_1/sensors/climate"
WATER_TOPIC = "farm/tray_1/sensors/water"


def get_current_metrics():
    """Возвращает последние показания датчиков."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            result = {
                "temperature": None,
                "humidity": None,
                "water_temp": None,
            }

            cursor.execute(
                """
                SELECT payload
                FROM telemetry
                WHERE topic = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (CLIMATE_TOPIC,),
            )
            climate_row = cursor.fetchone()
            if climate_row:
                climate_payload = json.loads(climate_row[0])
                result["temperature"] = climate_payload.get("air_temp")
                result["humidity"] = climate_payload.get("humidity")

            cursor.execute(
                """
                SELECT payload
                FROM telemetry
                WHERE topic = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (WATER_TOPIC,),
            )
            water_row = cursor.fetchone()
            if water_row:
                water_payload = json.loads(water_row[0])
                result["water_temp"] = water_payload.get("water_temp")

            return result
    except Exception as e:
        return {"error": str(e)}


def get_history(metric_name, hours=24):
    """Возвращает усредненную историю за указанное количество часов."""
    metric_config = {
        "temperature": (CLIMATE_TOPIC, "air_temp"),
        "humidity": (CLIMATE_TOPIC, "humidity"),
        "water_temp": (WATER_TOPIC, "water_temp"),
    }
    if metric_name not in metric_config:
        return {"error": f"Неизвестная метрика: {metric_name}"}

    try:
        hours = int(hours)
        topic, payload_key = metric_config[metric_name]

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Группируем по часам, чтобы не переполнить контекст ИИ
            query = """
                SELECT strftime('%Y-%m-%d %H:00', timestamp) as hour,
                       ROUND(AVG(json_extract(payload, ?)), 2) as avg_val
                FROM telemetry
                WHERE topic = ?
                  AND timestamp >= datetime('now', ?)
                GROUP BY hour
                ORDER BY hour ASC
            """
            cursor.execute(query, (f"$.{payload_key}", topic, f"-{hours} hours"))
            rows = cursor.fetchall()
            return [{"hour": row[0], "avg_value": row[1]} for row in rows]
    except Exception as e:
        return {"error": str(e)}


def get_crop_rules(crop_name):
    """Читает правила выращивания культуры из Markdown файла."""
    # Защита от выхода из директории
    safe_name = "".join(c for c in crop_name if c.isalnum() or c in (" ", "-", "_")).strip()
    file_path = os.path.join(CROPS_DIR, f"{safe_name}.md")

    if not os.path.exists(file_path):
        return {"error": f"Правила для культуры '{crop_name}' не найдены. Доступные: {os.listdir(CROPS_DIR) if os.path.exists(CROPS_DIR) else 'папка пуста'}"}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return {"error": str(e)}


# Схема инструментов для OpenAI API
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_current_metrics",
            "description": "Получает самые свежие, текущие показания датчиков фермы (температура, влажность, температура воды). Вызывай, когда спрашивают 'как дела сейчас'."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_history",
            "description": "Получает историю (тренды) конкретного датчика за указанное количество часов. Данные возвращаются усредненными по часам.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_name": {
                        "type": "string",
                        "enum": ["temperature", "humidity", "water_temp"],
                        "description": "Название метрики для анализа."
                    },
                    "hours": {
                        "type": "integer",
                        "description": "За сколько последних часов выгрузить историю. По умолчанию 24."
                    }
                },
                "required": ["metric_name", "hours"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_crop_rules",
            "description": "Получает справочную информацию (АгроТехКарту) с идеальными показателями для конкретной культуры.",
            "parameters": {
                "type": "object",
                "properties": {
                    "crop_name": {
                        "type": "string",
                        "description": "Название культуры на английском (например: tomatoes, basil)."
                    }
                },
                "required": ["crop_name"]
            }
        }
    }
]
