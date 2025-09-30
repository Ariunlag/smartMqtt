import { useEffect } from "react";
import { useMqttStore } from "../store/useMqttStore";
import { useInfluxStore } from "../store/useInfluxStore";
import { useDuplicateStore } from "../store/useDuplicateStore";
import { useGroupStore } from "../store/useGroupStore";

import type { MqttMessage } from "../types/mqtt";

// Define a type for incoming WS events
interface WsEvent<T = any> {
  event_type: "mqtt_message" | "topic" | "duplicate" | "group";
  data: T;
}

export const useWebSocket = (enabled: boolean) => {
  const addMqttMessage = useMqttStore((s) => s.addMessage);
  const getMeasurements = useInfluxStore((s) => s.getMeasurements);
  const addDuplicate = useDuplicateStore((s) => s.addDuplicate);
  const setGroups = useGroupStore((s) => s.setGroups);

  useEffect(() => {
    if (!enabled) return;

    const ws = new WebSocket("ws://localhost:8000/ws");

    ws.onopen = () => {
      console.log("[WebSocket] Connected");
    };

    ws.onclose = (event) => {
      console.log("[WebSocket] Disconnected", event.reason);
    };

    ws.onerror = (error) => {
      console.error("[WebSocket] Error:", error);
    };

    ws.onmessage = (event) => {
      try {
        const message: WsEvent = JSON.parse(event.data);

        switch (message.event_type) {
          case "mqtt_message":
            addMqttMessage(message.data as MqttMessage);
            break;

          case "topic":
            getMeasurements(); // refresh influx store
            break;

          case "duplicate":
            addDuplicate(message.data);
            break;

          case "group":
            setGroups(message.data.sets);
            break;

          default:
            console.warn("[WebSocket] Unknown event:", message);
        }
      } catch (err) {
        console.error("[WebSocket] Failed to parse:", err, event.data);
      }
    };

    return () => {
      console.log("[WebSocket] Cleaning up");
      ws.close();
    };
  }, [enabled, addMqttMessage, getMeasurements, addDuplicate, setGroups]);
};
