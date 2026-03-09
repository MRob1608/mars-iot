import pika
import json
import time
import requests

STATE= None

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


# 3. PIPELINE DI CONSUMO (Callback)
def callback(ch, method, properties, body):
    try:
        # Quando arriva un messaggio, lo decodifichiamo
        data = json.loads(body)
        print(body)
        
        response = requests.post(
            "http://presentation-service:5050/update_sensor", 
            json={"topic": data['topic'], "measurements": data['measurements']}
        )
        
        # Opzionale: stampa di controllo per sapere che è andato tutto a buon fine
        print(f"Messaggio inoltrato con status code: {response.status_code}")

    except Exception as e:
        # Cattura in un colpo solo qualsiasi errore e lo stampa
        print(f"Si è verificato un errore durante l'elaborazione: {e}")


def create_state():
    print(" [*] Attesa di masr-simulator...",flush=True)
    
    # 1. Ciclo di retry finché il simulatore non risponde
    while True:
        try:
            print("provo",flush=True)
            sensors_req = requests.get("http://mars-simulator:8080/api/sensors", timeout=5)
            telemetry_req = requests.get("http://mars-simulator:8080/api/telemetry/topics", timeout=5)
            actuators_req = requests.get("http://mars-simulator:8080/api/actuators", timeout=5)
            
            # Assicuriamoci che tutte le risposte siano 200 OK prima di procedere
            #sensors_req.raise_for_status()
            #telemetry_req.raise_for_status()
            #actuators_req.raise_for_status()
            
            # Se siamo arrivati fin qui, significa che le chiamate sono andate a buon fine
            sensors = sensors_req.json().get('sensors', [])
            
            telemetry = [
                t.split('/')[-1] 
                for t in telemetry_req.json().get('topics', [])
            ]
            
            actuators = list(actuators_req.json().get('actuators', {}).keys())
            
            print(" [V] masr-simulator è pronto! Dati recuperati con successo.")
            break  # Usciamo dal ciclo infinito
            
        except requests.exceptions.RequestException as e:
            # Cattura errori di connessione, timeout, o errori HTTP (es. 500/404)
            print(" [X] masr-simulator non ancora pronto, riprovo in 3 secondi...")
            time.sleep(3)

    # 2. Creazione della variabile STATE
    STATE = {
        **{sensor: 0 for sensor in sensors},
        **{tel: 0 for tel in telemetry},
        **{actuator: "OFF" for actuator in actuators}
    }
    print(STATE)

    return STATE



if __name__ == "__main__":
    print("ciao", flush=True)
    time.sleep(5)
    create_state()
    print("state creato")

    connection = connect_to_rabbitmq()
    channel = connection.channel()

    # 2. PIPELINE DI DICHIARAZIONE E BINDING
    exchange_name = 'exchange_data'
    channel.exchange_declare(exchange=exchange_name, exchange_type='topic')

    # Creiamo una coda unica per questo subscriber
    result = channel.queue_declare(queue='', exclusive=True)
    queue_name = result.method.queue

    channel.queue_bind(
    exchange=exchange_name, 
    queue=queue_name, 
    routing_key='#'
    )

    print(f" [*] In attesa di messaggi di tutti i topic")

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