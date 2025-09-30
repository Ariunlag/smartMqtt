import paho.mqtt.client as mqtt

def on_connect(client, userdata, flags, rc):
    print("Connected with rc:", rc)
    client.subscribe("test/topic")
    print("Subscribed to topic 'test/topic'")

def on_message(client, userdata, msg):
    print(f"{msg.topic} {msg.payload.decode()}")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect("test.mosquitto.org", 1883, 60)
client.loop_forever()
