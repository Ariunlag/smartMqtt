import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useDuplicateStore } from "../store/useDuplicateStore";
import { useMqttStore } from "../store/useMqttStore";
import { useInfluxStore } from "../store/useInfluxStore";
import { useGroupStore } from "../store/useGroupStore";

export function useBootstrap() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bootRef = useRef(false);

  const getDuplicates = useDuplicateStore((s) => s.getDuplicates);
  const getTopics = useMqttStore((s) => s.getTopics);
  const getClasses = useInfluxStore((s) => s.getClasses);
  const getGroups = useGroupStore((s) => s.fetchGroups);
  const getMeasurements = useInfluxStore((s) => s.getMeasurements);

  // === Step 1: Backend health check (retry with backoff, no page reload) ===
  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    let timer: number | undefined;

    const schedule = () => {
      const delay = Math.min(10_000, 1000 * 2 ** attempts);
      attempts += 1;
      timer = window.setTimeout(checkBackend, delay);
    };

    const checkBackend = async () => {
      try {
        const res = await axios.get(`${import.meta.env.VITE_API_BASE_URL || "/api"}/health`);
        if (cancelled) return;

        const { MQTTClient, InfluxClient } = res.data ?? {};
        if (MQTTClient && InfluxClient) {
          console.log("[Bootstrap] Backend ready ✅");
          setError(null);
          setReady(true);
        } else {
          console.warn("[Bootstrap] Services not yet connected");
          setError("Services not yet connected; retrying…");
          schedule();
        }
      } catch (err) {
        if (cancelled) return;
        console.error("[Bootstrap] Could not reach backend:", err);
        setError("Could not reach backend; retrying…");
        schedule();
      }
    };

    checkBackend();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  // === Step 2: Run initial data fetch once after everything is ready ===
  useEffect(() => {
    // wait for Influx store to finish hydration before calling its actions
    const influxPersist = (
      useInfluxStore as unknown as {
        persist?: { hasHydrated?: () => boolean };
      }
    ).persist;
    const hydrated = influxPersist?.hasHydrated?.() ?? true;

    if (!ready || !hydrated || bootRef.current) return;
    bootRef.current = true;

    (async () => {
      try {
        console.log("[Bootstrap] Fetching initial data…");
        await Promise.all([
          getDuplicates(),
          getTopics(),
          getClasses(),
          getGroups(),
          getMeasurements(),
        ]);
        console.log("[Bootstrap] All initial data loaded ✅");
      } catch (err) {
        console.error("[Bootstrap] Failed to bootstrap:", err);
      }
    })();
  }, [ready]);

  return { ready, error };
}
