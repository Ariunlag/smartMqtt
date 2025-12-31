import React, { useEffect, useRef } from "react";
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

  const { data, options } = createLineChartConfig(initialData);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    messages.forEach((msg) => {
      if (!topics.includes(msg.topic)) return;

      const value =
        msg.fields?.value ??
        msg.value ??
        msg.payload ??
        Object.values(msg.fields || {})[0] ??
        null;

      if (value == null) return; // skip if invalid

      const label = msg.topic;
      const point = { x: Date.parse(msg.timestamp), y: Number(value) };

      // Find or create dataset for this topic
      let dataset = chart.data.datasets.find((d: any) => d.label === label);

      if (dataset) {
        dataset.data.push(point);
        if (dataset.data.length > 500) dataset.data.shift(); // cap data points
      } else {
        chart.data.datasets.push({
          label,
          data: [point],
          borderColor: "#36a2eb",
          borderWidth: 2,
          fill: false,
          pointRadius: 1,
          tension: 0.1,
        });
      }
    });

    chart.update("none");
  }, [messages, topics]);

  return <Line ref={chartRef} data={data} options={options} />;
}
