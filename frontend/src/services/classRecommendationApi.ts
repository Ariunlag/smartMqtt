import { api } from "./influxApi";
import type {
  ClassActionRequest,
  ClassActionResult,
  ClassRecommendation,
} from "../types/api_models";

export async function getClassRecommendations(className: string) {
  const response = await api.get<{
    class_name: string;
    recommendations: ClassRecommendation[];
  }>(`/classes/${encodeURIComponent(className)}/recommendations`);
  return response.data;
}

export async function applyClassAction(
  className: string,
  request: ClassActionRequest,
) {
  const response = await api.post<ClassActionResult>(
    `/classes/${encodeURIComponent(className)}/recommendation-actions`,
    request,
  );
  return response.data;
}
