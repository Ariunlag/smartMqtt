import { useEffect, useRef } from "react";
import { useInfluxStore } from "../store/useInfluxStore";
import { useDuplicateStore } from "../store/useDuplicateStore";
import { useMqttStore } from "../store/useMqttStore";
import { useConnectionStore } from "../store/useConnectionStore";
import { backoffDelay, parseEnvelope, EventDeduper } from "../services/wsProtocol";
import type { MqttMessage } from "../types/mqtt";

const FLUSH_INTERVAL_MS = 200;
const HEARTBEAT_MS = 15_000;
const STALE_MS = 40_000;
const OFFLINE_AFTER_ATTEMPTS = 4;

function resyncBaseline() {
  void useMqttStore.getState().getTopics();
  void useDuplicateStore.getState().getDuplicates();
  void useInfluxStore.getState().getMeasurements();
  void useInfluxStore.getState().getClasses();
}

export const useWebSocket = (enabled: boolean) => {
  const bufferRef = useRef<MqttMessage[]>([]);

  useEffect(() => {
    if (!enabled) return;

    const setStatus = useConnectionStore.getState().setStatus;
    const deduper = new EventDeduper();

    let ws: WebSocket | null = null;
    let reconnectTimer: number | undefined;
    let heartbeatTimer: number | undefined;
    let attempts = 0;
    let hasConnectedOnce = false;
    let lastPong = 0;
    let disposed = false;

    const clearHeartbeat = () => {
      if (heartbeatTimer) {
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = undefined;
      }
    };

    const startHeartbeat = () => {
      lastPong = Date.now();
      clearHeartbeat();
      heartbeatTimer = window.setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (Date.now() - lastPong > STALE_MS) {
          ws.close();
          return;
        }
        ws.send(JSON.stringify({ type: "ping" }));
      }, HEARTBEAT_MS);
    };

    const dispatch = (raw: string) => {
      if (raw.includes('"pong"')) {
        try {
          if (JSON.parse(raw)?.type === "pong") {
            lastPong = Date.now();
            return;
          }
        } catch {
          /* fall through to envelope parsing */
        }
      }

      const env = parseEnvelope(raw);
      if (!env) {
        console.warn("[WebSocket] Ignoring malformed message");
        return;
      }
      if (!deduper.isNew(env.event_id)) return;

      switch (env.event_type) {
        case "mqtt_message":
          bufferRef.current.push({
            ...(env.data as MqttMessage),
            event_id: env.event_id,
          });
          break;
        case "topic":
          useInfluxStore
            .getState()
            .addDetectedMeasurement((env.data as { measurement: string }).measurement);
          break;
        case "duplicate":
          useDuplicateStore.getState().addDuplicate(env.data as never);
          break;
        default:
          console.warn("[WebSocket] Unknown event:", env.event_type);
      }
    };

    const connect = () => {
      setStatus(
        !hasConnectedOnce
          ? "connecting"
          : attempts >= OFFLINE_AFTER_ATTEMPTS
            ? "offline"
            : "reconnecting"
      );
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/ws`);

      ws.onopen = () => {
        attempts = 0;
        setStatus("connected");
        startHeartbeat();
        if (hasConnectedOnce) resyncBaseline();
        hasConnectedOnce = true;
        console.log("[WebSocket] Connected");
      };

      ws.onmessage = (event) => dispatch(event.data);

      ws.onclose = () => {
        clearHeartbeat();
        if (disposed) return;
        attempts += 1;
        setStatus(attempts >= OFFLINE_AFTER_ATTEMPTS ? "offline" : "reconnecting");
        const delay = backoffDelay(attempts - 1);
        console.warn(`[WebSocket] Disconnected; reconnecting in ${delay}ms`);
        reconnectTimer = window.setTimeout(connect, delay);
      };

      ws.onerror = () => ws?.close();
    };

    connect();

    const flushTimer = window.setInterval(() => {
      if (bufferRef.current.length === 0) return;
      const batch = bufferRef.current;
      bufferRef.current = [];
      useMqttStore.getState().addMessages(batch);
    }, FLUSH_INTERVAL_MS);

    return () => {
      disposed = true;
      window.clearInterval(flushTimer);
      clearHeartbeat();
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [enabled]);
};
