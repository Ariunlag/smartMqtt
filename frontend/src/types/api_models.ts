// ---------------------------
// Topics
// ---------------------------

export interface TopicListResponse {
  topics: string[];
}

export interface TopicSubscribeRequest {
  topic: string;
}

export interface TopicResponse {
  status: string;
  topic: string;
}

// ---------------------------
// Measurements (time-series)
// ---------------------------

export interface MeasurementPoint {
  timestamp: string;
  value: number;
}

export interface MeasurementSeriesResponse {
  measurement: string;
  points: MeasurementPoint[];
}

// ---------------------------
// Duplicate Detection
// ---------------------------

export type DupeStatus = "PENDING" | "CONFIRMED_DUPLICATE" | "NOT_DUPLICATE";
export const DupeStatus = {
  PENDING: "PENDING" as DupeStatus,
  CONFIRMED_DUPLICATE: "CONFIRMED_DUPLICATE" as DupeStatus,
  NOT_DUPLICATE: "NOT_DUPLICATE" as DupeStatus,
};

export type DupeAction = "KEEP_BOTH" | "UNSUBSCRIBE";
export const DupeAction = {
  KEEP_BOTH: "KEEP_BOTH" as DupeAction,
  UNSUBSCRIBE: "UNSUBSCRIBE" as DupeAction,
};

export interface DupeRecord {
  topics: string[];
  score: number;
  status: DupeStatus;
}

export interface DupeListResponse {
  duplicates: DupeRecord[];
}

export interface ConfirmDupeRequest {
  topics: string[];
  action: DupeAction;
  target?: string | null;
}

// ---------------------------
// Classes (user-owned Saved Classes)
// ---------------------------

export interface ClassRecord {
  class_id: string;
  name: string;
  topics: string[];
  profile_version: number;
}

export interface ClassListResponse {
  classes: ClassRecord[];
}

export interface CreateClassRequest {
  name: string;
  topics: string[];
}

export interface UpdateClassRequest {
  topics: string[];
}

// Legacy Saved-Class recommendation actions are retained for API compatibility.
export type ClassActionType =
  | "RECOMMENDATION_ACCEPT"
  | "RECOMMENDATION_REJECT"
  | "RECOMMENDATION_DISMISS"
  | "MANUAL_ADD"
  | "MANUAL_REMOVE";

export interface PairIdentity {
  source: "tag" | "field";
  normalized_key: string;
  datatype: string;
}

export type EvidenceScope = "pair" | "stream";

export interface EvidenceDefinition {
  evidence_id: string;
  label: string;
  scope: EvidenceScope;
}

export interface EvidenceScore {
  evidence_id: string;
  score: number;
}

export interface EvidenceScores {
  items: EvidenceScore[];
}

export interface MatchedPairEvidence {
  candidate: PairIdentity;
  prototype: PairIdentity;
  prototype_id: string;
  scores: EvidenceScores;
  compatibility_score: number;
}

export interface PairCoverage {
  candidate_pair_count: number;
  class_prototype_count: number;
  matched_pair_count: number;
  candidate_coverage: number;
  prototype_coverage: number;
}

export interface ClassRecommendation {
  recommendation_id: string;
  canonical_topic: string;
  original_topic: string;
  class_id: string;
  class_name: string;
  rank: number;
  overall_score: number;
  channel_scores: EvidenceScores;
  valid_channels: string[];
  coverage: PairCoverage;
  matched_pairs: MatchedPairEvidence[];
  unmatched_candidate_pairs: PairIdentity[];
  unmatched_prototypes: PairIdentity[];
  class_profile_version: number;
  topic_representation_version: number;
  duplicate_pending: boolean;
  algorithm_version: string;
}

export interface ClassActionRequest {
  action: ClassActionType;
  topic: string;
  topic_representation_version?: number;
  class_profile_version?: number;
  recommendation_id?: string;
}

export interface ClassActionResult {
  event_id: string;
  action_type: ClassActionType;
  canonical_topic: string;
  class_id: string;
  class_name: string;
  class_profile_version: number;
}

// ---------------------------
// System-derived Recommended Classes
// ---------------------------

export interface RecommendedClassTopicEvidence {
  topic: string;
  channel_scores: EvidenceScores;
  coverage: PairCoverage;
  matched_pairs: MatchedPairEvidence[];
  duplicate_pending: boolean;
}

export interface RecommendedClassCandidate {
  candidate_id: string;
  rank: number;
  anchor_topic: string;
  member_topics: string[];
  discovery_channels: string[];
  evidence: RecommendedClassTopicEvidence[];
}

export interface RecommendedClassCandidateSet {
  candidates: RecommendedClassCandidate[];
  available_topics: string[];
  evidence_catalog: EvidenceDefinition[];
}

// ---------------------------
// Groups (tag-based)
// ---------------------------

export type TagSetRecord = {
  id: string;
  tags: string[];
};

export type GroupListResponse = {
  sets: TagSetRecord[];
};

export type GroupTopicsResponse = {
  id: string;
  topics: string[];
};
