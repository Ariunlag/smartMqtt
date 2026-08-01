import axios from "axios";
import type {
  NegativeMembershipConstraintList,
  SemanticMembershipReviewRequest,
  SemanticClassList,
  SemanticReviewResult,
  SemanticReviewState,
} from "../types/api_models";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
});

export async function getSemanticReviewState(): Promise<SemanticReviewState> {
  const response = await api.get<SemanticReviewState>("/semantic-review/candidates");
  return response.data;
}

export async function submitSemanticReview(
  request: SemanticMembershipReviewRequest,
): Promise<SemanticReviewResult> {
  const response = await api.post<SemanticReviewResult>(
    "/semantic-review/reviews",
    request,
  );
  return response.data;
}

export async function getSemanticReviewConstraints(): Promise<NegativeMembershipConstraintList> {
  const response = await api.get<NegativeMembershipConstraintList>(
    "/semantic-review/constraints",
  );
  return response.data;
}

export async function getSemanticClasses(): Promise<SemanticClassList> {
  const response = await api.get<SemanticClassList>("/semantic-review/classes");
  return response.data;
}
