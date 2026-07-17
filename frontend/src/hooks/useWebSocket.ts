import { useEffect, useRef } from "react";
import { useInfluxStore } from "../store/useInfluxStore";
import { useDuplicateStore } from "../store/useDuplicateStore";
import { useMqttStore } from "../store/useMqttStore";
import { useGroupStore } from "../store/useGroupStore";
import type { MqttMessage } from "../types/mqtt";

const FLUSH_INTERVAL_MS = 200;
const MAX_RECONNECT_DELAY_MS = 30_000;

export const useWebSocket = (enabled: boolean) => {
  // Buffer high-frequency mqtt messages between flushes (see flush timer below).
  const bufferRef = useRef<MqttMessage[]>([]);

  useEffect(() => {
    if (!enabled) return;

    let ws: WebSocket | null = null;
    let reconnectTimer: number | undefined;
    let attempts = 0;
    let disposed = false;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/ws`);

      ws.onopen = () => {
        attempts = 0;
        console.log("[WebSocket] Connected");
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (import.meta.env.DEV) console.log("[WS EVENT]", msg);

          switch (msg.event_type) {
            case "mqtt_message":
              // Buffered and flushed as one batched store update.
              bufferRef.current.push(msg.data);
              break;
            case "topic":
              useInfluxStore.getState().addDetectedMeasurement(msg.data.measurement);
              break;
            case "duplicate":
              useDuplicateStore.getState().addDuplicate(msg.data);
              break;
            case "group":
              useGroupStore.getState().setGroups(msg.data.sets);
              break;
            default:
              console.warn("[WebSocket] Unknown event:", msg);
          }
        } catch (err) {
          console.error("[WebSocket] Parse failed:", err, event.data);
        }
      };

      ws.onclose = () => {
        if (disposed) return;
        // Exponential backoff, capped, so a backend restart or network blip
        // self-heals instead of leaving the UI silently frozen.
        const delay = Math.min(MAX_RECONNECT_DELAY_MS, 1000 * 2 ** attempts);
        attempts += 1;
        console.warn(`[WebSocket] Disconnected; reconnecting in ${delay}ms`);
        reconnectTimer = window.setTimeout(connect, delay);
      };

      ws.onerror = () => ws?.close();
    };

    connect();

    // Flush buffered mqtt messages in a single batched store update to avoid a
    // re-render per message under high throughput.
    const flushTimer = window.setInterval(() => {
      if (bufferRef.current.length === 0) return;
      const batch = bufferRef.current;
      bufferRef.current = [];
      useMqttStore.getState().addMessages(batch);
    }, FLUSH_INTERVAL_MS);

    return () => {
      disposed = true;
      window.clearInterval(flushTimer);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [enabled]);
};
