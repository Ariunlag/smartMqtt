import React, { useEffect, useRef } from "react";
import { Line } from "react-chartjs-2";
import { useMqttStore } from "../../store/useMqttStore";
import { createLineChartConfig } from "../../services/lineChartService";

type Props = {
  topics: string[]; // e.g. ["topicA", "topicB"]
};

export default function RealtimeGraph({ topics }: Props) {
  const chartRef = useRef<any>(null);
  const messages = useMqttStore((s) => s.messages);

  // Start with empty datasets
  const { data, options } = createLineChartConfig([]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    messages.forEach((msg) => {
      // filter: only show if msg.topic in props
      if (!topics.includes(msg.topic)) return;

      Object.entries(msg.fields).forEach(([field, value]) => {
        const label = `${msg.topic}:${field}`;
        let dataset = chart.data.datasets.find((d: any) => d.label === label);

        const point = { x: Date.parse(msg.timestamp), y: Number(value) };

        if (dataset) {
          dataset.data.push(point);
          if (dataset.data.length > 500) dataset.data.shift();
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
    });

    chart.update("none");
  }, [messages, topics]);

  return <Line ref={chartRef} data={data} options={options} />;
}
