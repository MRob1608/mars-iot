import time
import json
import threading
import requests
import pika
from sseclient import SSEClient

from sensor_normalizer import normalize_sensor_reading

# --- Configuration ---
GET_TOPICS = [
    "http://mars-simulator:8080/api/sensors/greenhouse_temperature",
    "http://mars-simulator:8080/api/sensors/entrance_humidity",
    "http://mars-simulator:8080/api/sensors/co2_hall",
    "http://mars-simulator:8080/api/sensors/hydroponic_ph",
    "http://mars-simulator:8080/api/sensors/water_tank_level",
    "http://mars-simulator:8080/api/sensors/corridor_pressure",
    "http://mars-simulator:8080/api/sensors/air_quality_pm25",
    "http://mars-simulator:8080/api/sensors/air_quality_voc"
]

SSE_TOPICS = [
    "http://mars-simulator:8080/api/telemetry/stream/mars/telemetry/solar_array",
    "http://mars-simulator:8080/api/telemetry/stream/mars/telemetry/radiation",
    "http://mars-simulator:8080/api/telemetry/stream/mars/telemetry/life_support",
    "http://mars-simulator:8080/api/telemetry/stream/mars/telemetry/thermal_loop",
    "http://mars-simulator:8080/api/telemetry/stream/mars/telemetry/power_bus",
    "http://mars-simulator:8080/api/telemetry/stream/mars/telemetry/power_consumption",
    "http://mars-simulator:8080/api/telemetry/stream/mars/telemetry/airlock"
]

RABBITMQ_HOST = "message-broker"
RABBITMQ_QUEUE = "telemetry_queue"
EXCHANGE_NAME = 'exchange_data'

# Lock used to publish to RabbitMQ (channel is not thread-safe)
_publish_lock = threading.Lock()

# --- Normalization helper to the unified schema ---
def normalize_message(msg):
    """
    Normalize a REST or telemetry payload into the unified schema.
    The source is inferred: if there is "topic" it is telemetry, otherwise rest.
    Adds "topic" so it can be used as RabbitMQ routing_key (same as "id").
    """
    source = "telemetry" if "topic" in msg and "sensor_id" not in msg else "rest"
    try:
        normalized = normalize_sensor_reading(msg, source)
        normalized["topic"] = normalized["id"]
        return normalized
    except ValueError as e:
        print(f"[INGEST][WARN] Normalization failed, message kept as is | error={e}")
        return msg

# --- Create a persistent RabbitMQ connection ---
def create_connection():
    while True:
        try:
            connection = pika.BlockingConnection(
                    pika.ConnectionParameters(host=RABBITMQ_HOST, heartbeat=600)
            )
            channel = connection.channel()
            channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='topic')
            return connection, channel
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[INGEST][ERROR] Cannot create connection with RabbitMQ, retrying in 5 seconds | error={e}")
            time.sleep(5)

# --- Send messages to RabbitMQ ---
def send_to_rabbitmq(message, connection, channel):
    try:
        with _publish_lock:
            channel.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key=message["topic"],
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2  # make the message persistent
                )
            )
        # Do not close the connection here: it is shared between threads
        print(f"[INGEST][INFO] Message published to RabbitMQ | topic={message.get('topic', message.get('id', ''))}")
    except Exception as e:
        print(f"[INGEST][ERROR] RabbitMQ publish failed | error={e}")

# --- SSE listener thread for telemetry topics ---
def listen_sse(url, connection, channel):
    while True:
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            client = SSEClient(response)
            for msg in client.events():
                if msg.data:
                    try:
                        data = json.loads(msg.data)
                        normalized = normalize_message(data)
                        print(f"[INGEST][DEBUG] SSE message normalized | topic={normalized.get('topic')} | source={normalized.get('source')}")
                        send_to_rabbitmq(normalized, connection, channel)
                    except json.JSONDecodeError:
                        print(f"[INGEST][WARN] Invalid SSE payload, skipping message | url={url}")
        except Exception as e:
            print(f"[INGEST][ERROR] SSE stream error, retrying | url={url} | error={e}")
            time.sleep(5)  # retry after 5 seconds

# --- Polling thread for periodic REST GET calls ---
def poll_get(url, connection, channel, interval=5):
    while True:
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            normalized = normalize_message(data)
            print(f"[INGEST][DEBUG] REST payload normalized | topic={normalized.get('topic')} | source={normalized.get('source')}")
            send_to_rabbitmq(normalized, connection, channel)
        except requests.RequestException as e:
            print(f"[INGEST][ERROR] REST GET failed | url={url} | error={e}")
        time.sleep(interval)

# --- Main entrypoint ---
if __name__ == "__main__":
    connection, channel = create_connection()
    threads = []

    # Start SSE threads
    for sse_url in SSE_TOPICS:
        t = threading.Thread(target=listen_sse, args=(sse_url, connection, channel), daemon=True)
        t.start()
        threads.append(t)

    # Start periodic GET threads
    for get_url in GET_TOPICS:
        t = threading.Thread(target=poll_get, args=(get_url, connection, channel), daemon=True)
        t.start()
        threads.append(t)

    # Main loop to keep the process alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[INGEST][INFO] Ingestion service interrupted manually")
