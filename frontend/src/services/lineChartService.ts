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
export function createLineChartConfig(
  seriesList: MeasurementSeriesResponse[],
  colors: string[] = [
  cssVar("--accent", "#2fa4c7"),
  cssVar("--accent-dark", "#1f6f8b"),
  cssVar("--accent-soft", "#9fd3e2"),
  cssVar("--primary-text", "#1f2933"),
  cssVar("--border-color", "#d9e1e8"),
]
): { data: ChartData<"line">; options: ChartOptions<"line"> } {
  ensureChartRegistration();

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

  // global min/max for axis scaling
  const allX = datasets.flatMap((d: any) => d.data.map((p: any) => p.x));
  const minX = allX.length ? Math.min(...allX) : Date.now() - 60_000;
  const maxX = allX.length ? Math.max(...allX) : Date.now();
  const unit = chooseTimeUnit(minX, maxX);

  const data: ChartData<"line"> = { datasets };

  const options: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    parsing: false,
    normalized: true,
    plugins: {
      legend: { display: true, position: "top" },
      tooltip: {
        intersect: false,
        mode: "nearest",
        callbacks: {
          label(ctx) {
            const iso = new Date(ctx.parsed.x).toISOString();
            return `Value: ${ctx.parsed.y}, Time: ${iso}`;
          },
        },
      },
    },
    scales: {
      x: {
        type: "time",
        time: { unit },
        ticks: { color: "#bbb" },
      },
      y: {
        beginAtZero: true,
        ticks: { color: "#bbb" },
      },
    },
  };

  return { data, options };
}
