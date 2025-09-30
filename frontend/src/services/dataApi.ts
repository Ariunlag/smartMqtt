import axios from "axios";
import type {
  TopicListResponse,
  MeasurementSeriesResponse,
} from "../types/api_models";

import type {MqttMessagesResponse} from "../types/mqtt";

// Base axios instance
const api = axios.create({
  baseURL: "http://localhost:8000/api",
});

// 1. List all measurements
export async function getMeasurements() {
  const res = await api.get<TopicListResponse>("/measurements");
  return res.data;
}

// 2. Get timeseries data (default last 1h)
export async function getTimeseries(names: string[]) {
  const res = await api.get<MeasurementSeriesResponse[]>("/timeseries", {
    params: { names },
  });
  return res.data;
}

// 3. Get last N messages across all topics
export async function getMessages(limit: number = 200) {
  const res = await api.get<MqttMessagesResponse>("/messages", {
    params: { limit },
  });
  return res.data;
}
