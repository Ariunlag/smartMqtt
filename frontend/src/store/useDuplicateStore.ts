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
          const { data } = await duplicateApi.confirmDuplicate(req);

          set((s) => {
            const samePair = (a: [string, string], b: [string, string]) =>
              JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());

            const updatedDuplicates = s.duplicates.map((d) =>
              samePair(d.topics, req.topics) ? data : d
            );

            // Always clear selection after an action
            return {
              duplicates: updatedDuplicates,
              selectedPair: null,
              series: [],
            };
          });
        } catch (err) {
          console.error("[Duplicates] Confirm failed:", err);
        }
      },


      // === Add new duplicate record via WS ===
      addDuplicate: (dup: DupeRecord) =>
        set((s) => {
          const exists = s.duplicates.some(
            (d) => JSON.stringify(d.topics.sort()) === JSON.stringify(dup.topics.sort())
          );
          if (exists) return {};
          return { duplicates: [...s.duplicates, dup] };
        }),

      // === Remove duplicate record from list ===
      removeDuplicate: (topics: [string, string]) =>
        set((s) => ({
          duplicates: s.duplicates.filter(
            (d) => JSON.stringify(d.topics.sort()) !== JSON.stringify(topics.sort())
          ),
        })),

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
              ? { ...ts, points: [...ts.points, point] }
              : ts
          ),
        })),
    }),
    { name: "duplicate-store" }
  )
);
