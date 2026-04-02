import json
import random
import time

import paho.mqtt.client as mqtt


BROKER_HOST = "localhost"
BROKER_PORT = 1883
DEVICE_ID = "tray_1"
SENSORS_TOPIC = "farm/tray_1/sensors"
FAN_TOPIC = "farm/tray_1/cmd/fan"


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe(FAN_TOPIC)
    else:
        print(f"[СИМУЛЯТОР] Ошибка подключения: {reason_code}")


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8")
    print(f"[СИМУЛЯТОР] Вентилятор (tray_1) получил команду: {payload}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_ID)
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER_HOST, BROKER_PORT, 60)
client.loop_start()

while True:
    temperature = round(random.uniform(20.0, 25.0), 1)
    payload = json.dumps({"temperature": temperature})
    client.publish(SENSORS_TOPIC, payload)
    print(f"[СИМУЛЯТОР] Отправлены данные: {payload}")
    time.sleep(5)
