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

  // === Step 1: Backend health check ===
  useEffect(() => {
    let cancelled = false;
    const checkBackend = async () => {
      try {
        const res = await axios.get(`${import.meta.env.VITE_API_BASE_URL || "/api"}/health`);
        if (cancelled) return;

        const { MQTTClient, InfluxClient } = res.data ?? {};
        if (MQTTClient && InfluxClient) {
          console.log("[Bootstrap] Backend ready ✅");
          setReady(true);
        } else {
          console.warn("[Bootstrap] Services not yet connected");
          setError("Services not yet connected");
        }
      } catch (err) {
        if (cancelled) return;
        console.error("[Bootstrap] Could not reach backend:", err);
        setError("Could not reach backend; retrying…");
        setTimeout(() => window.location.reload(), 3000);
      }
    };

    checkBackend();
    return () => {
      cancelled = true;
    };
  }, []);

  // === Step 2: Run initial data fetch once after everything is ready ===
  useEffect(() => {
    // wait for Influx store to finish hydration before calling its actions
    const influxPersist = (useInfluxStore as any).persist;
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
