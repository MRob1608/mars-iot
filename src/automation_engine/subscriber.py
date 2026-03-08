import pika
import json
import time

# 1. PIPELINE DI CONNESSIONE (Stesso meccanismo di retry)
def connect_to_rabbitmq():
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('message-broker'))
            print(" [V] Connesso a RabbitMQ!")
            return connection
        except pika.exceptions.AMQPConnectionError:
            print(" [X] RabbitMQ non ancora pronto, riprovo in 3 secondi...")
            time.sleep(3)

connection = connect_to_rabbitmq()
channel = connection.channel()

# 2. PIPELINE DI DICHIARAZIONE E BINDING
exchange_name = 'exchange_data'
channel.exchange_declare(exchange=exchange_name, exchange_type='topic')

# Creiamo una coda unica per questo subscriber
result = channel.queue_declare(queue='', exclusive=True)
queue_name = result.method.queue

# ECCO IL FILTRO: Vogliamo solo il sensore 07
binding_key = "mars/telemetry/airlock"

channel.queue_bind(
    exchange=exchange_name, 
    queue=queue_name, 
    routing_key=binding_key
)

print(f" [*] In attesa di messaggi SOLO per il topic: {binding_key}")

# 3. PIPELINE DI CONSUMO (Callback)
def callback(ch, method, properties, body):
    # Quando arriva un messaggio, lo decodifichiamo
    data = json.loads(body)
    
    # Stampiamo un feedback visivo per confermare che è il sensore giusto
    print(f"messaggio arrivato: {data}")

# Avviamo l'ascolto continuo
channel.basic_consume(
    queue=queue_name, 
    on_message_callback=callback, 
    auto_ack=True
)

try:
    channel.start_consuming()
except KeyboardInterrupt:
    print(" [!] Chiusura subscriber...")
finally:
    connection.close()