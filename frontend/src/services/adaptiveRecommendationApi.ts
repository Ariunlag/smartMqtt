import axios from "axios";

export interface EvidencePayload {text?: string; key?: string; value?: unknown; values?: (number | null)[]; field?: string; window_end?: number}
export interface AdaptiveEvidence {
  score: number | null;
  status: string;
  coverage: number;
  reference_topic?: string;
  support_count?: number;
  matches: {left: EvidencePayload; right: EvidencePayload; similarity: number}[];
}
export interface AdaptiveGroup {
  group_id: string;
  revision: number;
  name: string | null;
  members: string[];
  saved_class: string | null;
  dismissed: boolean;
  edited: boolean;
  can_undo: boolean;
  confirmed: string[];
  evidence: Record<string, Record<string, AdaptiveEvidence>>;
  proposals: {topic: string; score: number}[];
  member_scores: Record<string, number | null>;
}
export interface AdaptiveResponse {
  environment_id: string;
  catalog: {evidence_id: string; label: string; active: boolean; scope: string; kind: string}[];
  model: {version: number; weights: Record<string, number>; status: string; updated_at: string | null;
    evaluation?: {candidate_loss: number; baseline_loss: number; active_loss: number}; last_update_accepted?: boolean};
  feedback_count: number;
  background_error: string | null;
  available_topics: string[];
  groups: AdaptiveGroup[];
  threshold: number;
  discovery?: {mode: string; algorithm: string; scored_pairs: number; possible_pairs: number; elapsed_seconds: number};
  series?: {enabled: boolean; error: string | null; window_end: number | null};
}
export type GroupAction = "add" | "remove" | "confirm" | "save" | "undo" | "dismiss" | "useful";

export async function getAdaptiveRecommendations(): Promise<AdaptiveResponse> {
  return (await axios.get<AdaptiveResponse>("/api/adaptive-recommendations")).data;
}
export async function editAdaptiveGroup(group: AdaptiveGroup, action: GroupAction, values: {topic?: string; name?: string} = {}): Promise<AdaptiveGroup> {
  return (await axios.post<AdaptiveGroup>(`/api/adaptive-recommendations/${encodeURIComponent(group.group_id)}/actions`,
    {action, revision: group.revision, ...values})).data;
}
