import { useEffect } from "react";
import { useInfluxStore } from "../store/useInfluxStore";
import { useDuplicateStore } from "../store/useDuplicateStore";
import { useMqttStore } from "../store/useMqttStore";
import { useGroupStore } from "../store/useGroupStore";

export const useWebSocket = (enabled: boolean) => {
  useEffect(() => {
    if (!enabled) return;

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws`);

    ws.onopen = () => console.log("[WebSocket] Connected");
    ws.onclose = () => console.log("[WebSocket] Disconnected");

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        console.log("[WS EVENT]", msg);

        // 🔥 Access fresh store instances dynamically
        const influx = useInfluxStore.getState();
        const dupes = useDuplicateStore.getState();
        const mqtt = useMqttStore.getState();
        const groups = useGroupStore.getState();

        switch (msg.event_type) {
          case "mqtt_message":
            mqtt.addMessage(msg.data);
            break;
          case "topic":
            influx.addDetectedMeasurement(msg.data.measurement);
            break;
          case "duplicate":
            dupes.addDuplicate(msg.data);
            break;
          case "group":
            groups.setGroups(msg.data.sets);
            break;
          default:
            console.warn("[WebSocket] Unknown event:", msg);
        }
      } catch (err) {
        console.error("[WebSocket] Parse failed:", err, event.data);
      }
    };

    return () => ws.close();
  }, [enabled]);
};
