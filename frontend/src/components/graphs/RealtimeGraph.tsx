import { useEffect, useMemo, useRef } from "react";
import { Line } from "react-chartjs-2";
import type { Chart as ChartJS, ChartDataset } from "chart.js";
import { useMqttStore } from "../../store/useMqttStore";
import { createLineChartConfig, SERIES_COLORS } from "../../services/lineChartService";
import { collectNewPoints } from "../../services/chartPoints";
import type { MeasurementSeriesResponse } from "../../types/api_models";

type Props = {
  topics: string[];
  initialData?: MeasurementSeriesResponse[];
  maxPoints?: number;
};

export default function RealtimeGraph({
  topics = [],
  initialData = [],
  maxPoints = 500,
}: Props) {
  const chartRef = useRef<ChartJS<"line"> | null>(null);
  const messages = useMqttStore((s) => s.messages);

  // Ids of messages already plotted. Reset whenever the selected topics or the
  // historical baseline change, so stale identifiers never suppress new points.
  const seenRef = useRef<Set<string>>(new Set());

  // A one-topic chart is labelled by its GraphBox heading; skip the legend.
  const showLegend = topics.length !== 1;

  const { data, options } = useMemo(
    () => createLineChartConfig(initialData, { showLegend }),
    [initialData, showLegend]
  );

  useEffect(() => {
    seenRef.current = new Set();
  }, [topics, initialData]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const perTopic = collectNewPoints(messages, topics, seenRef.current);

    for (const [topic, points] of Object.entries(perTopic)) {
      if (points.length === 0) continue;

      let dataset = chart.data.datasets.find((d) => d.label === topic);
      if (!dataset) {
        const created: ChartDataset<"line"> = {
          label: topic,
          data: [],
          borderColor:
            SERIES_COLORS[chart.data.datasets.length % SERIES_COLORS.length],
          borderWidth: 2,
          fill: false,
          pointRadius: 1,
          pointHoverRadius: 4,
          tension: 0.1,
        };
        chart.data.datasets.push(created);
        dataset = created;
      }

      for (const point of points) {
        dataset.data.push(point);
        if (dataset.data.length > maxPoints) dataset.data.shift(); // bounded
      }
    }

    chart.update("none");
  }, [messages, topics, maxPoints]);

  return <Line ref={chartRef} data={data} options={options} />;
}
