import axios from "axios";
import type {
  ClassListResponse,
  ClassRecord,
  CreateClassRequest,
  UpdateClassRequest,
} from "../types/api_models";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
});


// 1. Get all saved classes
export async function listClasses() {
  const res = await api.get<ClassListResponse>("/classes/");
  return res.data;
}

// 2. Create a new class
export async function saveClass(req: CreateClassRequest) {
  const res = await api.post<ClassRecord>("/classes/", req);
  return res.data;
}

// 3. Update an existing class
export async function updateClass(name: string, req: UpdateClassRequest) {
  const res = await api.put<ClassRecord>(`/classes/${encodeURIComponent(name)}`, req);
  return res.data;
}

// 4. Delete a class
export async function deleteClass(name: string) {
  const res = await api.delete<{ status: string; name: string }>(
    `/classes/${encodeURIComponent(name)}`
  );
  return res.data;
}
