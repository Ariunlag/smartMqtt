import { api } from "./influxApi";
import type {
  ClassActionRequest,
  ClassActionResult,
  ClassRecommendation,
  RecommendedClassCandidateSet,
  RecommendedClassFeedbackRequest,
  RecommendedClassFeedbackResult,
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

export async function getRecommendedClassCandidates(strategy?: string) {
  const response = await api.get<RecommendedClassCandidateSet>("/recommended-classes", {
    params: strategy ? { strategy } : undefined,
  });
  return response.data;
}

export async function submitRecommendedClassFeedback(
  candidateId: string,
  request: RecommendedClassFeedbackRequest,
) {
  const response = await api.post<RecommendedClassFeedbackResult>(
    `/recommended-classes/${encodeURIComponent(candidateId)}/feedback`,
    request,
  );
  return response.data;
}
