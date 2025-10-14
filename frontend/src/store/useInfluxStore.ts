import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as dataApi from "../services/dataApi";
import * as influxApi from "../services/influxApi";
import type {
  MeasurementSeriesResponse,
  ClassRecord,
  ClassListResponse,
} from "../types/api_models";

export type TimeseriesData = MeasurementSeriesResponse;
type Aggregation = "mean" | "max" | "min" | "sum";

interface InfluxStore {
  // === Core data ===
  measurements: string[];
  selectedMeasurements: string[];
  builderTimeseriesData: TimeseriesData[];
  classNameInput: string;

  // === Saved classes ===
  classes: ClassRecord[];
  selectedClass: ClassRecord | null;
  savedClassTimeseriesData: TimeseriesData[];

  selectedAggregation: Aggregation;
  startTime: string;
  endTime: string;

  // === Builder actions ===
  getMeasurements: () => Promise<void>;
  addMeasurement: (m: string) => Promise<void>;
  removeMeasurement: (m: string) => Promise<void>;
  setSelectedMeasurements: (topics: string[]) => Promise<void>;
  fetchBuilderTimeseriesData: () => Promise<void>;

  // === Class actions ===
  setClassNameInput: (name: string) => void;
  saveClass: () => Promise<void>;
  getClasses: () => Promise<void>;
  setSelectedClass: (cls: ClassRecord) => void;
  clearSelectedClass: () => void;
  deleteClass: (name?: string) => Promise<void>;
  fetchSavedClassTimeseriesData: (topics: string[]) => Promise<void>;

  // === Realtime updates ===
  appendRealTimePoint: (topic: string, value: number, timestamp: string) => void;
  addDetectedMeasurement: (m: string) => void;
}

export const useInfluxStore = create<InfluxStore>()(
  persist(
    (set, get) => {
      // === Stable function definitions (no re-creation after set()) ===

      const getMeasurements = async () => {
        const data = await dataApi.getMeasurements();
        set({ measurements: data.topics });
      };

      const addMeasurement = async (m: string) => {
        const current = get().selectedMeasurements;
        if (!current.includes(m)) {
          const updated = [...current, m];
          set({ selectedMeasurements: updated });
          await get().fetchBuilderTimeseriesData();
        }
      };

      const removeMeasurement = async (m: string) => {
        const updated = get().selectedMeasurements.filter((x) => x !== m);
        set({ selectedMeasurements: updated });
        await get().fetchBuilderTimeseriesData();
      };

      const setSelectedMeasurements = async (topics: string[]) => {
        set({ selectedMeasurements: topics });
        await get().fetchBuilderTimeseriesData();
      };

      const fetchBuilderTimeseriesData = async () => {
        const { selectedMeasurements } = get();
        if (selectedMeasurements.length === 0) {
          set({ builderTimeseriesData: [] });
          return;
        }
        const data = await dataApi.getTimeseries(selectedMeasurements);
        set({ builderTimeseriesData: data });
      };

      const setClassNameInput = (name: string) => set({ classNameInput: name });

      const saveClass = async () => {
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
      };

      const getClasses = async () => {
        const data: ClassListResponse = await influxApi.listClasses();
        set({ classes: data.classes });
      };

      const setSelectedClass = (cls: ClassRecord) => {
        set({ selectedClass: cls });
        get().fetchSavedClassTimeseriesData(cls.topics);
      };

      const clearSelectedClass = () => {
        set({ selectedClass: null, savedClassTimeseriesData: [] });
      };

      const deleteClass = async (name?: string) => {
        const target = name || get().selectedClass?.name;
        if (!target) return;

        await influxApi.deleteClass(target);
        set((s) => ({
          classes: s.classes.filter((c) => c.name !== target),
          selectedClass: s.selectedClass?.name === target ? null : s.selectedClass,
          savedClassTimeseriesData:
            s.selectedClass?.name === target ? [] : s.savedClassTimeseriesData,
        }));
      };

      const fetchSavedClassTimeseriesData = async (topics: string[]) => {
        if (!topics || topics.length === 0) {
          set({ savedClassTimeseriesData: [] });
          return;
        }
        const data = await dataApi.getTimeseries(topics);
        set({ savedClassTimeseriesData: data });
      };

      const appendRealTimePoint = (topic: string, value: number, timestamp: string) => {
        const updates: Partial<InfluxStore> = {};

        // Update builder graphs
        if (get().selectedMeasurements.includes(topic)) {
          updates.builderTimeseriesData = get().builderTimeseriesData.map((ts) =>
            ts.measurement === topic
              ? { ...ts, points: [...ts.points, { value, timestamp }] }
              : ts
          );
        }

        // Update saved class graphs
        if (get().selectedClass?.topics.includes(topic)) {
          updates.savedClassTimeseriesData = get().savedClassTimeseriesData.map((ts) =>
            ts.measurement === topic
              ? { ...ts, points: [...ts.points, { value, timestamp }] }
              : ts
          );
        }

        if (Object.keys(updates).length > 0) set(updates);
      };

      const addDetectedMeasurement = (m: string) => {
        set((s) => {
          if (s.measurements.includes(m)) return s; // avoid duplicates
          console.log("[InfluxStore] New measurement detected via WS:", m);
          return { measurements: [...s.measurements, m] };
        });
      };


      // === Initial state ===
      return {
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

        getMeasurements,
        addMeasurement,
        removeMeasurement,
        setSelectedMeasurements,
        fetchBuilderTimeseriesData,

        setClassNameInput,
        saveClass,
        getClasses,
        setSelectedClass,
        clearSelectedClass,
        deleteClass,
        fetchSavedClassTimeseriesData,

        appendRealTimePoint,
        addDetectedMeasurement,
      };
    },
    {
      name: "influx-storage",
      onRehydrateStorage: () => (state) => {
        console.log("[InfluxStore] rehydrated");
      },
    }
  )
);
