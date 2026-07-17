import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as topicApi from "../services/topicApi";
import * as dataApi from "../services/dataApi";
import type { MqttMessage } from "../types/mqtt";

// Client-side fallback id for messages that arrive without an envelope event_id
// (e.g. REST-loaded history). Guarantees a unique, stable React/dedup key.
let __localSeq = 0;
const withId = (m: MqttMessage): MqttMessage =>
  m.event_id ? m : { ...m, event_id: `local-${(__localSeq += 1)}` };

interface MqttState {
  topics: string[];                // subscribed topics (from backend JSON)
  messages: MqttMessage[];         // recent + live messages

  getTopics: () => Promise<void>;  // fetch subscribed topics
  loadMessages: (limit?: number) => Promise<void>; // fetch last N points
  addTopic: (topic: string) => Promise<void>;      // subscribe new topic
  removeTopic: (topic: string) => Promise<void>;   // unsubscribe topic
  addMessage: (msg: MqttMessage) => void;          // append new WS message
  addMessages: (msgs: MqttMessage[]) => void;      // append a batch of WS messages
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

      // Unsubscribe from topic. Only remove locally once the backend confirms;
      // let failures propagate so the UI can surface them and offer retry.
      removeTopic: async (topic: string) => {
        await topicApi.unsubscribeTopic(topic);
        const { topics } = get();
        set({ topics: topics.filter((t) => t !== topic) });
        console.log("[Store] Unsubscribed:", topic);
      },

      // Add a new message (from WebSocket)
      addMessage: (msg: MqttMessage) => {
        const { messages } = get();
        set({
          messages: [withId(msg), ...messages].slice(0, 300), // keep max 300
        });
      },

      // Add a batch of messages in one update (WebSocket flush).
      // Incoming batch is oldest→newest; store keeps newest-first, capped at 300.
      addMessages: (msgs: MqttMessage[]) => {
        if (msgs.length === 0) return;
        const { messages } = get();
        const withIds = msgs.map(withId).reverse();
        set({
          messages: [...withIds, ...messages].slice(0, 300),
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
      // Persist only the subscription list. Live messages are streamed and must
      // not be serialized to localStorage on every incoming message.
      partialize: (state) => ({ topics: state.topics }),
    }
  )
);
