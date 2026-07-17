import { useEffect, useMemo, useRef } from "react";
import { Line } from "react-chartjs-2";
import { useMqttStore } from "../../store/useMqttStore";
import { createLineChartConfig } from "../../services/lineChartService";

type Props = {
  topics: string[];
  initialData?: any[];
};

export default function RealtimeGraph({ topics = [], initialData = [] }: Props) {
  const chartRef = useRef<any>(null);
  const messages = useMqttStore((s) => s.messages);

  // Track which messages were already plotted so we only append new points
  // instead of re-pushing the whole buffer on every update (which duplicated
  // points and was O(n) per message).
  const seenRef = useRef<Set<string>>(new Set());

  const { data, options } = useMemo(
    () => createLineChartConfig(initialData),
    [initialData]
  );

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const seen = seenRef.current;

    // Buffer is newest-first; iterate oldest→newest so points append in order.
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (!topics.includes(msg.topic)) continue;

      const key = `${msg.topic}|${msg.timestamp}`;
      if (seen.has(key)) continue;

      const value =
        msg.fields?.value ??
        msg.value ??
        msg.payload ??
        Object.values(msg.fields || {})[0] ??
        null;

      if (value == null) continue; // skip if invalid
      seen.add(key);

      const point = { x: Date.parse(msg.timestamp), y: Number(value) };
      const dataset = chart.data.datasets.find((d: any) => d.label === msg.topic);

      if (dataset) {
        dataset.data.push(point);
        if (dataset.data.length > 500) dataset.data.shift(); // cap data points
      } else {
        chart.data.datasets.push({
          label: msg.topic,
          data: [point],
          borderColor: "#36a2eb",
          borderWidth: 2,
          fill: false,
          pointRadius: 1,
          tension: 0.1,
        });
      }
    }

    // Prune the seen-set so it can't grow unbounded across a long session.
    if (seen.size > 2000) {
      seenRef.current = new Set(Array.from(seen).slice(-1000));
    }

    chart.update("none");
  }, [messages, topics]);

  return <Line ref={chartRef} data={data} options={options} />;
}
