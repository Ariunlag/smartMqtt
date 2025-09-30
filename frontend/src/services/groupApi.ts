import axios from "axios";
import type { GroupListResponse } from "../types/api_models";

const api = axios.create({
  baseURL: "http://localhost:8000/api",
});

// 1. List all groups (id + tags)
export async function getGroups() {
  const res = await api.get<GroupListResponse>("/groups");
  return res.data;
}

// 2. Get topics for a given group set_id
export async function getGroupTopics(setId: string) {
  const res = await api.get<string[]>(`/groups/${setId}/topics`);
  return res.data;
}
