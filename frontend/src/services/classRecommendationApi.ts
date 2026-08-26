import { api } from "./influxApi";
import type {
  ClassActionRequest,
  ClassActionResult,
  ClassRecommendation,
  RecommendedClassCandidateSet,
} from "../types/api_models";

// Legacy Saved-Class recommendation API retained for compatibility.
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

export async function getRecommendedClassCandidates() {
  const response = await api.get<RecommendedClassCandidateSet>("/recommended-classes");
  return response.data;
}
