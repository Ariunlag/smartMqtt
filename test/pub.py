import time
import json
import paho.mqtt.client as mqtt

def on_connect(client, userdata, flags, rc):
    print("Connected with rc:", rc)

client = mqtt.Client()
client.on_connect = on_connect
client.connect("test.mosquitto.org", 1883, 60)
client.loop_start()

# Publish 5 test messages
for i in range(5):
    payload = json.dumps({"msg": f"hello {i}"})
    client.publish("test/topic", payload, qos=1, retain=True)
    print("Published:", payload)
    time.sleep(1)

client.loop_stop()
client.disconnect()
