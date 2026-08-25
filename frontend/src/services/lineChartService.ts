import {
  Chart as ChartJS,
  TimeScale,
  LinearScale,
  CategoryScale,
  LineController,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
} from "chart.js";
import "chartjs-adapter-date-fns";

import type { ChartData, ChartOptions } from "chart.js";
import type { MeasurementSeriesResponse, MeasurementPoint } from "../types/api_models";

export type TimeseriesData = MeasurementSeriesResponse;

// --------------------------- One-time registration ---------------------------

function cssVar(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

let __chartsRegistered = false;
function ensureChartRegistration() {
  if (__chartsRegistered) return;
  ChartJS.register(
    LineController,
    LineElement,
    PointElement,
    TimeScale,
    LinearScale,
    CategoryScale,
    Title,
    Tooltip,
    Legend
  );
  __chartsRegistered = true;
}

// --------------------------- Helpers ---------------------------
function toMillis(p: MeasurementPoint): number {
  return Date.parse(p.timestamp); // backend already sends ISO string
}

type TimeUnit = "minute" | "hour" | "day";
function chooseTimeUnit(minX: number, maxX: number): TimeUnit {
  const span = Math.max(1, maxX - minX);
  if (span <= 6 * 60 * 60 * 1000) return "minute";   // ≤ 6h
  if (span <= 14 * 24 * 60 * 60 * 1000) return "hour"; // ≤ 2w
  return "day";
}

// --------------------------- Factory ---------------------------
// Categorical series palette: distinguishable by hue, all readable on a light
// surface. Extend rather than reorder — index N must stay stable per series.
export const SERIES_COLORS = [
  "#0e7490", // teal
  "#c2410c", // orange
  "#4338ca", // indigo
  "#15803d", // green
  "#b91c1c", // red
  "#a16207", // amber
  "#7e22ce", // purple
  "#0369a1", // blue
];

/**
 * MQTT topics are long ("site/floor1/room3/sensor-a/temperature") and blow the
 * legend up to several rows, eating the plot area. Keep the tail segments —
 * they carry the distinguishing part — and let the tooltip show the full name.
 */
export function shortenTopic(topic: string, max = 24): string {
  if (topic.length <= max) return topic;

  const parts = topic.split("/").filter(Boolean);
  for (let take = 2; take >= 1; take -= 1) {
    if (parts.length <= take) break;
    const tail = `…/${parts.slice(-take).join("/")}`;
    if (tail.length <= max) return tail;
  }
  return `…${topic.slice(-(max - 1))}`;
}

export function createLineChartConfig(
  seriesList: MeasurementSeriesResponse[],
  opts: { colors?: string[]; showLegend?: boolean } = {}
): { data: ChartData<"line">; options: ChartOptions<"line"> } {
  ensureChartRegistration();
  const colors = opts.colors ?? SERIES_COLORS;

  // datasets
  const datasets = seriesList
    .filter((s) => s?.points?.length > 0)
    .map((s, idx) => ({
      label: s.measurement,
      data: s.points.map((p) => ({
        x: toMillis(p),
        y: p.value,
      })),
      borderColor: colors[idx % colors.length],
      borderWidth: 2,
      fill: false,
      spanGaps: true,
      pointRadius: 1,
      pointHoverRadius: 4,
      tension: 0.1,
    }));

  // global min/max for axis scaling — computed with a loop, not Math.min(...spread),
  // which throws "Maximum call stack size" on large point sets.
  let minX = Infinity;
  let maxX = -Infinity;
  for (const d of datasets) {
    for (const p of d.data) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
    }
  }
  if (!isFinite(minX)) {
    minX = Date.now() - 60_000;
    maxX = Date.now();
  }
  const unit = chooseTimeUnit(minX, maxX);

  const data: ChartData<"line"> = { datasets };

  const tickColor = cssVar("--muted-text", "#64748b");
  const gridColor = cssVar("--border-color", "#e2e8f0");

  // A single-series box is already labelled by its GraphBox heading, so the
  // legend would only repeat the topic and steal vertical space.
  const showLegend = opts.showLegend ?? datasets.length !== 1;

  const options: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    parsing: false,
    normalized: true,
    layout: { padding: { top: 2, right: 6, bottom: 0, left: 0 } },
    plugins: {
      legend: {
        display: showLegend,
        position: "top",
        align: "start",
        maxHeight: 44, // hard cap: never let labels crowd out the plot
        labels: {
          boxWidth: 8,
          boxHeight: 8,
          padding: 10,
          usePointStyle: true,
          pointStyle: "circle",
          color: tickColor,
          font: { size: 11 },
          generateLabels(chart) {
            const base =
              ChartJS.defaults.plugins.legend.labels.generateLabels(chart);
            return base.map((item) => ({
              ...item,
              text: shortenTopic(item.text ?? ""),
            }));
          },
        },
      },
      tooltip: {
        intersect: false,
        mode: "nearest",
        callbacks: {
          // Full topic name here — the legend only carries the shortened form.
          title(items) {
            return items[0]?.dataset?.label ?? "";
          },
          label(ctx) {
            const iso =
              ctx.parsed.x == null
                ? "unknown"
                : new Date(ctx.parsed.x).toISOString();
            return `Value: ${ctx.parsed.y}, Time: ${iso}`;
          },
        },
      },
    },
    scales: {
      x: {
        type: "time",
        time: { unit },
        border: { display: false },
        grid: { color: gridColor },
        ticks: { color: tickColor, font: { size: 10 }, maxRotation: 0 },
      },
      y: {
        beginAtZero: true,
        border: { display: false },
        grid: { color: gridColor },
        ticks: { color: tickColor, font: { size: 10 } },
      },
    },
  };

  return { data, options };
}
