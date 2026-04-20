import json
import random
import time

import paho.mqtt.client as mqtt


BROKER_HOST = "31.56.208.196"
BROKER_PORT = 1883
DEVICE_ID = "tray_1"
COMMANDS_TOPIC = "farm/tray_1/cmd/#"
CLIMATE_TOPIC = "farm/tray_1/sensors/climate"
WATER_TOPIC = "farm/tray_1/sensors/water"


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe(COMMANDS_TOPIC)
    else:
        print(f"[СИМУЛЯТОР] Ошибка подключения: {reason_code}")


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8")
    print(f"[СИМУЛЯТОР] Получена команда {msg.topic}: {payload}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_ID)
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER_HOST, BROKER_PORT, 60)
client.loop_start()

iteration = 0

while True:
    iteration += 1
    air_temp = round(random.uniform(22.0, 27.5), 1)

    if iteration % 20 == 0:
        air_temp = 33.0

    climate_payload = json.dumps(
        {
            "air_temp": air_temp,
            "humidity": round(random.uniform(42.0, 62.0), 1),
        }
    )
    water_payload = json.dumps(
        {
            "water_temp": round(random.uniform(17.0, 22.0), 1),
        }
    )

    client.publish(CLIMATE_TOPIC, climate_payload, retain=True)
    client.publish(WATER_TOPIC, water_payload, retain=True)

    print(f"[СИМУЛЯТОР] Отправлены climate: {climate_payload}")
    print(f"[СИМУЛЯТОР] Отправлены water: {water_payload}")
    time.sleep(1)
