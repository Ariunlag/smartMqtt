import { create } from "zustand";
import * as groupApi from "../services/groupApi";
import { useInfluxStore } from "./useInfluxStore"; // cross-store sync
import type { TagSetRecord } from "../types/api_models";

interface GroupStore {
  // Available groups (tag sets)
  groups: TagSetRecord[];
  selectedGroupId: string | null;
  selectedTopics: string[];

  // Actions
  fetchGroups: () => Promise<void>;
  setGroups: (groups: TagSetRecord[]) => void; // for WebSocket live update
  selectGroup: (id: string) => Promise<void>;
  removeTopic: (t: string) => Promise<void>;
  clearSelection: () => void;
}

export const useGroupStore = create<GroupStore>((set, get) => ({
  groups: [],
  selectedGroupId: null,
  selectedTopics: [],

  // Fetch available tag-based groups
  fetchGroups: async () => {
    const data = await groupApi.getGroups();
    set({ groups: data.sets });
  },

  // Replace all groups (used by WebSocket event)
  setGroups: (groups) => set({ groups }),

  // When user selects a group → fetch its topics + sync with Influx
  selectGroup: async (id) => {
    set({ selectedGroupId: id, selectedTopics: [] });
    const data = await groupApi.getGroupTopics(id); // { set_id, topics }
    set({ selectedTopics: data.topics });

    // Sync with Influx store (for graphs)
    const influx = useInfluxStore.getState();
    if (influx.setSelectedMeasurements) {
      influx.setSelectedMeasurements(data.topics);
    }
    if (influx.fetchBuilderTimeseriesData) {
      await influx.fetchBuilderTimeseriesData();
    }
  },

  // Remove one topic from selection + refresh graph
  removeTopic: async (t) => {
    const updated = get().selectedTopics.filter((x) => x !== t);
    set({ selectedTopics: updated });

    // ✅ Reflect in Influx graphs
    const influx = useInfluxStore.getState();
    if (influx.setSelectedMeasurements) {
      influx.setSelectedMeasurements(updated);
    }
    if (influx.fetchBuilderTimeseriesData) {
      await influx.fetchBuilderTimeseriesData();
    }
  },

  // Clear group + clear graph
  clearSelection: () => {
    set({ selectedGroupId: null, selectedTopics: [] });

    const influx = useInfluxStore.getState();
    if (influx.setSelectedMeasurements) {
      influx.setSelectedMeasurements([]);
    }
    if (influx.fetchBuilderTimeseriesData) {
      influx.fetchBuilderTimeseriesData();
    }
  },
}));
