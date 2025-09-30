import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as dataApi from "../services/dataApi";     // for measurements + timeseries
import * as influxApi from "../services/influxApi"; // for classes
import type {
  MeasurementSeriesResponse,
  ClassRecord,
  ClassListResponse,
} from "../types/api_models";

// ---- Types ----
export type TimeseriesData = MeasurementSeriesResponse;
type Aggregation = "mean" | "max" | "min" | "sum";

interface InfluxStore {
  // Builder state
  measurements: string[];
  selectedMeasurements: string[];
  builderTimeseriesData: TimeseriesData[];
  classNameInput: string;

  // Saved classes
  classes: ClassRecord[];
  selectedClass: ClassRecord | null;
  savedClassTimeseriesData: TimeseriesData[];

  // Settings
  selectedAggregation: Aggregation;
  startTime: string;
  endTime: string;

  // Builder actions
  getMeasurements: () => Promise<void>;
  addMeasurement: (m: string) => Promise<void>;
  removeMeasurement: (m: string) => Promise<void>;
  fetchBuilderTimeseriesData: () => Promise<void>;
  setClassNameInput: (name: string) => void;
  saveClass: () => Promise<void>;

  // Saved class actions
  getClasses: () => Promise<void>;
  setSelectedClass: (cls: ClassRecord) => void;
  fetchSavedClassTimeseriesData: () => Promise<void>;
  clearSelectedClass: () => void;
  deleteClass: (name?: string) => Promise<void>;

  // Realtime append
  appendRealTimePoint: (topic: string, value: number, timestamp: string) => void;
}

export const useInfluxStore = create<InfluxStore>()(
  persist(
    (set, get) => ({
      // ---- Initial state ----
      measurements: [],
      selectedMeasurements: [],
      builderTimeseriesData: [],
      classNameInput: "",

      classes: [],
      selectedClass: null,
      savedClassTimeseriesData: [],

      selectedAggregation: "mean",
      startTime: "-6h",
      endTime: "now()",

      // ---- Builder ----
      getMeasurements: async () => {
        const data = await dataApi.getMeasurements();
        set({ measurements: data.topics }); 
      },

      addMeasurement: async (m) => {
        const current = get().selectedMeasurements;
        if (!current.includes(m)) {
          set({ selectedMeasurements: [...current, m] });
          await get().fetchBuilderTimeseriesData();
        }
      },

      removeMeasurement: async (m) => {
        set({
          selectedMeasurements: get().selectedMeasurements.filter((x) => x !== m),
        });
        await get().fetchBuilderTimeseriesData();
      },

      fetchBuilderTimeseriesData: async () => {
        const { selectedMeasurements } = get();
        if (selectedMeasurements.length === 0) {
          set({ builderTimeseriesData: [] });
          return;
        }
        const data = await dataApi.getTimeseries(selectedMeasurements);
        set({ builderTimeseriesData: data });
      },

      setClassNameInput: (name) => set({ classNameInput: name }),

      saveClass: async () => {
        const { classNameInput, selectedMeasurements, classes } = get();
        if (!classNameInput || selectedMeasurements.length === 0) return;

        const newClass = await influxApi.saveClass({
          name: classNameInput,
          topics: selectedMeasurements,
        });

        set({
          classes: [...classes, newClass],
          classNameInput: "",
          selectedMeasurements: [],
          builderTimeseriesData: [],
        });
      },

      // ---- Saved Classes ----
      getClasses: async () => {
        const data: ClassListResponse = await influxApi.listClasses();
        set({ classes: data.classes });
      },

      setSelectedClass: (cls) => {
        set({ selectedClass: cls });
        get().fetchSavedClassTimeseriesData();
      },

      fetchSavedClassTimeseriesData: async () => {
        const { selectedClass } = get();
        if (!selectedClass) {
          set({ savedClassTimeseriesData: [] });
          return;
        }
        const data = await dataApi.getTimeseries(selectedClass.topics);
        set({ savedClassTimeseriesData: data });
      },

      clearSelectedClass: () => set({ selectedClass: null, savedClassTimeseriesData: [] }),

      deleteClass: async (name) => {
        const target = name || get().selectedClass?.name;
        if (!target) return;

        await influxApi.deleteClass(target);
        set((s) => ({
          classes: s.classes.filter((c) => c.name !== target),
          selectedClass: s.selectedClass?.name === target ? null : s.selectedClass,
          savedClassTimeseriesData:
            s.selectedClass?.name === target ? [] : s.savedClassTimeseriesData,
        }));
      },

      // ---- Realtime append ----
      appendRealTimePoint: (topic, value, timestamp) => {
        const updates: Partial<InfluxStore> = {};

        if (get().selectedMeasurements.includes(topic)) {
          updates.builderTimeseriesData = get().builderTimeseriesData.map((ts) =>
            ts.measurement === topic
              ? { ...ts, points: [...ts.points, { value, timestamp }] }
              : ts
          );
        }

        if (get().selectedClass?.topics.includes(topic)) {
          updates.savedClassTimeseriesData = get().savedClassTimeseriesData.map((ts) =>
            ts.measurement === topic
              ? { ...ts, points: [...ts.points, { value, timestamp }] }
              : ts
          );
        }

        if (Object.keys(updates).length > 0) {
          set(updates);
        }
      },
    }),
    { name: "influx-storage" }
  )
);
