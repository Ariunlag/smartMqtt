import axios from "axios";
import type { TopicListResponse, TopicResponse } from "../types/api_models";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

// 1. List subscribed topics
export const getSubscribedTopics = async () => {
  const res = await axios.get<TopicListResponse>(`${BASE_URL}/topics`);
  return res.data;
};

// 2. Subscribe to new topic
export const subscribeTopic = async (topic: string) => {
  const res = await axios.post<TopicResponse>(`${BASE_URL}/subscribe`, { topic });
  return res.data;
};

// 3. Unsubscribe topic
export const unsubscribeTopic = async (topic: string) => {
  const res = await axios.post<TopicResponse>(`${BASE_URL}/unsubscribe`, { topic });
  return res.data;
};

