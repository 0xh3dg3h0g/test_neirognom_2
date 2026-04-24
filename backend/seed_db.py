import sqlite3
import random
from datetime import datetime, timedelta
import os
import json

DB_PATH = os.getenv("DB_PATH", "farm.db")

def seed_database():
    print(f"Подключаемся к базе {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Правильная структура таблицы, как в main.py!
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            payload TEXT,
            timestamp DATETIME
        )
    ''')

    now = datetime.now()
    cursor.execute("DELETE FROM telemetry")

    print("Генерируем данные за 7 дней (168 часов)...")
    
    for i in range(168, -1, -1):
        record_time = now - timedelta(hours=i)
        ts_str = record_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Базовые показатели
        temp = round(random.uniform(22.0, 25.0), 1)
        hum = round(random.uniform(60.0, 75.0), 1)
        w_temp = round(random.uniform(18.0, 21.0), 1)
        
        # Аномалия 1: Жара
        if 48 <= i <= 72:
            temp = round(random.uniform(29.0, 33.0), 1)
            hum = round(random.uniform(40.0, 45.0), 1)
        
        # Аномалия 2: Холодная вода
        if 12 <= i <= 24:
            w_temp = round(random.uniform(14.0, 16.0), 1)
        
        # Пакуем данные в JSON (payload) и разбиваем по топикам, как работает реальная ферма
        climate_payload = json.dumps({"air_temp": temp, "humidity": hum})
        water_payload = json.dumps({"water_temp": w_temp})
        
        cursor.execute(
            "INSERT INTO telemetry (topic, payload, timestamp) VALUES (?, ?, ?)",
            ("farm/tray_1/sensors/climate", climate_payload, ts_str)
        )
        cursor.execute(
            "INSERT INTO telemetry (topic, payload, timestamp) VALUES (?, ?, ?)",
            ("farm/tray_1/sensors/water", water_payload, ts_str)
        )
        
    conn.commit()
    conn.close()
    print("Успех! База данных заполнена правильными данными.")

if __name__ == '__main__':
    seed_database()