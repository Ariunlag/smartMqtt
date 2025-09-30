import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as topicApi from "../services/topicApi";
import * as dataApi from "../services/dataApi";
import type { MqttMessage } from "../types/mqtt";

interface MqttState {
  topics: string[];                // subscribed topics (from backend JSON)
  messages: MqttMessage[];         // recent + live messages

  getTopics: () => Promise<void>;  // fetch subscribed topics
  loadMessages: (limit?: number) => Promise<void>; // fetch last N points
  addTopic: (topic: string) => Promise<void>;      // subscribe new topic
  removeTopic: (topic: string) => Promise<void>;   // unsubscribe topic
  addMessage: (msg: MqttMessage) => void;          // append new WS message
  clear: () => void;               // reset store
}

export const useMqttStore = create<MqttState>()(
  persist(
    (set, get) => ({
      topics: [],
      messages: [],

      // Get currently subscribed topics (from backend subscriptions.json)
      getTopics: async () => {
        try {
          const response = await topicApi.getSubscribedTopics();
          const topics = response.topics?? [];
          console.log("[Store] Fetched topics:", topics);
          set({ topics });
        } catch (error) {
          console.error("[Zustand] Failed to fetch topics:", error);
          set({ topics: [] });
        }
      },

      // Load last N messages from Influx (via API)
      loadMessages: async (limit: number = 200) => {
        try {
          const { messages } = await dataApi.getMessages(limit);
          console.log("[Store] Loaded messages:", messages.length);
          set({ messages });
        } catch (error) {
          console.error("[Zustand] Failed to load messages:", error);
          set({ messages: [] });
        }
      },

      // Subscribe to new topic
      addTopic: async (topic: string) => {
        try {
          await topicApi.subscribeTopic(topic);
          const { topics } = get();
          if (!topics.includes(topic)) {
            set({ topics: [...topics, topic] });
          }
          console.log("[Store] Subscribed to:", topic);
        } catch (error) {
          console.error("[Zustand] Failed to subscribe:", error);
        }
      },

      // Unsubscribe from topic
      removeTopic: async (topic: string) => {
        try {
          await topicApi.unsubscribeTopic(topic); // backend call
        } catch (error) {
          console.warn("[Zustand] Backend unsubscribe error, but removing locally:", error);
        }
        // always remove locally
        const { topics } = get();
        set({ topics: topics.filter((t) => t !== topic) });
        console.log("[Store] Removed from UI:", topic);
      },

      // Add a new message (from WebSocket)
      addMessage: (msg: MqttMessage) => {
        const { messages } = get();
        set({
          messages: [msg, ...messages].slice(0, 300), // keep max 300
        });
      },

      // Reset store
      clear: () => {
        set({
          topics: [],
          messages: [],
        });
      },
    }),
    {
      name: "mqtt-store", 
    }
  )
);
