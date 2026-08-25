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
  timestamp: string; // ISO datetime string from backend
  value: number;     // numeric field for UI plotting
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
// Classes (user groups)
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

export interface PairViewScores {
  key: number;
  value: number;
  key_value: number;
  schema: number;
  numeric_key: number | null;
}

export interface MatchedPairEvidence {
  candidate: PairIdentity;
  prototype: PairIdentity;
  prototype_id: string;
  scores: PairViewScores;
  compatibility_score: number;
}

export interface ClassRecommendation {
  recommendation_id: string;
  canonical_topic: string;
  original_topic: string;
  class_id: string;
  class_name: string;
  rank: number;
  overall_score: number;
  channel_scores: {
    key: number | null;
    value: number | null;
    key_value: number | null;
    schema: number | null;
    numeric_key: number | null;
    stream_context: number | null;
  };
  valid_channels: string[];
  coverage: {
    candidate_pair_count: number;
    class_prototype_count: number;
    matched_pair_count: number;
    candidate_coverage: number;
    prototype_coverage: number;
  };
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
