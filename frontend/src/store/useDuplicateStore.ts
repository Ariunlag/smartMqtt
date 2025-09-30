import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as duplicateApi from "../services/duplicateApi";
import * as dataApi from "../services/dataApi";
import type { DupeRecord, ConfirmDupeRequest } from "../types/api_models";
import type { TimeseriesData } from "../services/lineChartService";

type DuplicateState = {
  duplicates: DupeRecord[];
  selectedPair: DupeRecord | null;
  series: TimeseriesData[];

  // API actions
  getDuplicates: () => Promise<void>;
  confirmDuplicate: (req: ConfirmDupeRequest) => Promise<void>;

  // WS updates
  addDuplicate: (dup: DupeRecord) => void;

  // UI helpers
  removeDuplicate: (topics: [string, string]) => void;
  selectPair: (pair: DupeRecord) => void;
  clearSelection: () => void;

  // Timeseries handling
  loadPairTimeseries: (topics: string[]) => Promise<void>;
  appendPoint: (measurement: string, point: { time: string | number; value: number }) => void;
};

export const useDuplicateStore = create<DuplicateState>()(
  persist(
    (set, get) => ({
      duplicates: [],
      selectedPair: null,
      series: [],

      getDuplicates: async () => {
        try {
          const { data } = await duplicateApi.getDuplicates();
          set({ duplicates: data.duplicates });
        } catch (err) {
          console.error("[Duplicates] Failed to fetch:", err);
        }
      },

      confirmDuplicate: async (req: ConfirmDupeRequest) => {
        try {
          const { data } = await duplicateApi.confirmDuplicate(req);
          set((s) => ({
            duplicates: s.duplicates.map((d) =>
              JSON.stringify(d.topics.sort()) === JSON.stringify(req.topics.sort()) ? data : d
            ),
          }));
        } catch (err) {
          console.error("[Duplicates] Confirm failed:", err);
        }
      },

      addDuplicate: (dup: DupeRecord) =>
        set((s) => {
          const exists = s.duplicates.some(
            (d) => JSON.stringify(d.topics.sort()) === JSON.stringify(dup.topics.sort())
          );
          if (exists) return {};
          return { duplicates: [...s.duplicates, dup] };
        }),

      removeDuplicate: (topics: [string, string]) =>
        set((s) => ({
          duplicates: s.duplicates.filter(
            (d) => JSON.stringify(d.topics.sort()) !== JSON.stringify(topics.sort())
          ),
        })),

      selectPair: (pair) => set({ selectedPair: pair }),

      clearSelection: () => set({ selectedPair: null, series: [] }),

      // New: fetch backend history
      loadPairTimeseries: async (topics) => {
        try {
          const res = await dataApi.getTimeseries(topics);
          const formatted: TimeseriesData[] = res.map((m) => ({
            measurement: m.measurement,
            points: m.points.map((p) => ({
              time: p.timestamp,
              value: p.value,
            })),
          }));
          set({ series: formatted });
        } catch (err) {
          console.error("[Duplicates] Failed to fetch timeseries:", err);
          set({ series: [] });
        }
      },

      // New: append live WS points
      appendPoint: (measurement, point) =>
        set((s) => ({
          series: s.series.map((ts) =>
            ts.measurement === measurement
              ? { ...ts, points: [...ts.points, point] }
              : ts
          ),
        })),
    }),
    { name: "duplicate-store" }
  )
);
