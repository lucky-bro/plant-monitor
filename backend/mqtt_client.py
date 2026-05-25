import json
import logging
import os
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MQTT_HOST     = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT     = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER     = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_TOPIC    = "plant/#"

# Will be set from main.py
on_telemetry_received = None

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("[MQTT] Connected to broker.")
        client.subscribe(MQTT_TOPIC)
        logger.info(f"[MQTT] Subscribed to {MQTT_TOPIC}")
    else:
        logger.error(f"[MQTT] Connection failed, rc={rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        logger.info(f"[MQTT] Received: {payload}")
        if on_telemetry_received:
            on_telemetry_received(payload)
    except json.JSONDecodeError as e:
        logger.error(f"[MQTT] Invalid JSON: {e}")
    except Exception as e:
        logger.error(f"[MQTT] Error processing message: {e}")

def create_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    return client

def start_mqtt(client: mqtt.Client):
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

def stop_mqtt(client: mqtt.Client):
    client.loop_stop()
    client.disconnect()
