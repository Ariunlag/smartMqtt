import { create } from "zustand";
import * as groupApi from "../services/groupApi"; // groups endpoints
import type { TagSetRecord } from "../types/api_models";

interface GroupStore {
  // Available groups (tag sets)
  groups: TagSetRecord[];
  selectedGroupId: string | null;
  selectedTopics: string[];

  // Actions
  fetchGroups: () => Promise<void>;
  setGroups: (groups: TagSetRecord[]) => void;  // NEW for WS
  selectGroup: (id: string) => Promise<void>;
  removeTopic: (t: string) => void;
  clearSelection: () => void;
}

export const useGroupStore = create<GroupStore>((set, get) => ({
  groups: [],
  selectedGroupId: null,
  selectedTopics: [],

  fetchGroups: async () => {
    const data = await groupApi.getGroups(); 
    set({ groups: data.sets });
  },

  setGroups: (groups) => set({ groups }), 

  selectGroup: async (id) => {
    set({ selectedGroupId: id, selectedTopics: [] });
    const topics = await groupApi.getGroupTopics(id); 
    set({ selectedTopics: topics });
  },

  removeTopic: (t) => {
    set({
      selectedTopics: get().selectedTopics.filter((x) => x !== t),
    });
  },

  clearSelection: () => {
    set({ selectedGroupId: null, selectedTopics: [] });
  },
}));
