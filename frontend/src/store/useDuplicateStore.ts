import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as duplicateApi from "../services/duplicateApi";
import * as dataApi from "../services/dataApi";
import type { DupeRecord, ConfirmDupeRequest } from "../types/api_models";
import type { TimeseriesData } from "../services/lineChartService";
import { pairKey, samePair } from "../utils/pairKey";

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
  removeDuplicate: (topics: string[]) => void;
  selectPair: (pair: DupeRecord) => Promise<void>;
  clearSelection: () => void;

  // Timeseries handling
  loadPairTimeseries: (topics: string[]) => Promise<void>;
  appendPoint: (measurement: string, point: { timestamp: string | number; value: number }) => void;
};

export const useDuplicateStore = create<DuplicateState>()(
  persist(
    (set, get) => ({
      duplicates: [],
      selectedPair: null,
      series: [],

      // === Fetch duplicates ===
      getDuplicates: async () => {
        try {
          const { data } = await duplicateApi.getDuplicates();
          set({ duplicates: data.duplicates });
        } catch (err) {
          console.error("[Duplicates] Failed to fetch:", err);
        }
      },

      // === Confirm duplicate pair ===
      confirmDuplicate: async (req) => {
        try {
          await duplicateApi.confirmDuplicate(req);
          set((state) => ({
            duplicates: state.duplicates.filter(
              (duplicate) => !samePair(duplicate.topics, req.topics)
            ),
            selectedPair: null,
            series: [],
          }));
          try {
            const { data } = await duplicateApi.getDuplicates();
            set({ duplicates: data.duplicates });
          } catch (err) {
            console.error("[Duplicates] Refresh after resolution failed:", err);
          }
        } catch (err) {
          console.error("[Duplicates] Confirm failed:", err);
        }
      },


      // === Add new duplicate record via WS (idempotent, no state mutation) ===
      addDuplicate: (dup: DupeRecord) =>
        set((s) => {
          const key = pairKey(dup.topics);
          const exists = s.duplicates.some((d) => pairKey(d.topics) === key);
          if (exists) return {};
          return { duplicates: [...s.duplicates, dup] };
        }),

      // === Remove duplicate record from list (no state mutation) ===
      removeDuplicate: (topics: string[]) =>
        set((s) => {
          const key = pairKey(topics);
          return {
            duplicates: s.duplicates.filter((d) => pairKey(d.topics) !== key),
          };
        }),

      // === Select a pair and auto-load data ===
      selectPair: async (pair) => {
        set({ selectedPair: pair, series: [] });
        await get().loadPairTimeseries(pair.topics);
      },

      // === Clear selection ===
      clearSelection: () => set({ selectedPair: null, series: [] }),

      // === Fetch historical timeseries for selected pair ===
      loadPairTimeseries: async (topics) => {
        try {
          const data = await dataApi.getTimeseries(topics);
          // ⚡ No reformatting — backend already returns usable structure
          set({ series: data });
        } catch (err) {
          console.error("[Duplicates] Failed to fetch timeseries:", err);
          set({ series: [] });
        }
      },

      // === Append live points (via WS) ===
      appendPoint: (measurement, point) =>
        set((s) => ({
          series: s.series.map((ts) =>
            ts.measurement === measurement
              ? {
                  ...ts,
                  points: [...ts.points, { timestamp: String(point.timestamp), value: point.value }],
                }
              : ts
          ),
        })),
    }),
    {
      name: "duplicate-store",
      // Persist only the pending list; live time-series and selection are
      // transient and re-fetched on demand.
      partialize: (state) => ({ duplicates: state.duplicates }),
    }
  )
);
