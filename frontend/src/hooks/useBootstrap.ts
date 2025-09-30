import { useEffect, useRef, useState } from "react"
import axios from "axios"
import { useDuplicateStore } from "../store/useDuplicateStore"
import { useMqttStore } from "../store/useMqttStore"
import { useInfluxStore } from "../store/useInfluxStore"
import { useGroupStore } from "../store/useGroupStore"

export function useBootstrap() {
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bootRef = useRef(false)

  const getDuplicates = useDuplicateStore((s) => s.getDuplicates)
                            const getTopics = useMqttStore((s) => s.getTopics)
  const getClasses = useInfluxStore((s) => s.getClasses)
  const getGroups = useGroupStore((s) => s.fetchGroups)
  const getMeasurements = useInfluxStore((s) => s.getMeasurements)

  // Health check
  useEffect(() => {
    let cancelled = false
    axios
      .get("http://localhost:8000/api/health")
      .then((res) => {
        const { MQTTClient, InfluxClient } = res.data ?? {}
        if (MQTTClient && InfluxClient) {
          setReady(true)
        } else {
          setError("Services not yet connected")
        }
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not reach backend; retrying…")
        setTimeout(() => window.location.reload(), 3000)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Bootstrap Zustand stores once
  useEffect(() => {
    if (!ready || bootRef.current) return
    bootRef.current = true
    ;(async () => {
      try {
        await Promise.all([
          getDuplicates(),
          getTopics(),
          getClasses(),
          getGroups(),
          getMeasurements(),
        ])
      } catch (e) {
        console.error("[Bootstrap] failed:", e)
      }
    })()
  }, [ready])

  return { ready, error }
}
