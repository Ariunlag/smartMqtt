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
  name: string;
  topics: string[];
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

// ---------------------------
// Diagnostic semantic review
// ---------------------------

export interface CandidateIdentity {
  representation_name: string;
  member_topics: string[];
}

export interface PendingSemanticCandidate extends CandidateIdentity {
  candidate_index?: number | null;
}

export interface SemanticReviewState {
  candidates: PendingSemanticCandidate[];
  available_unknown_topics: string[];
}

export interface SemanticMembershipReviewRequest {
  identity: CandidateIdentity;
  class_id: string;
  semantic_class_name: string;
  kept_topics: string[];
  removed_topics: string[];
  added_topics: string[];
}

export interface NegativeMembershipConstraint {
  topic: string;
  semantic_class_name: string;
}

export interface PrototypeSummary {
  representation_name: string;
  member_topics: string[];
  member_count: number;
}

export interface SemanticReviewResult {
  class_id: string;
  semantic_class_name: string;
  registry_updated: boolean;
  positive_topics: string[];
  removed_topics: string[];
  changed_representations: string[];
  constraints_added: NegativeMembershipConstraint[];
  constraints_removed: NegativeMembershipConstraint[];
  prototypes: PrototypeSummary[];
}

export interface NegativeMembershipConstraintList {
  constraints: NegativeMembershipConstraint[];
}

export interface SemanticClassDefinition {
  class_id: string;
  semantic_class_name: string;
}

export interface SemanticClassList {
  classes: SemanticClassDefinition[];
}

export interface SemanticProcessingStatus {
  running: boolean;
  enabled: boolean;
  queue_size: number;
  queue_capacity: number;
  submitted_count: number;
  processed_count: number;
  failed_count: number;
  dropped_count: number;
  last_processed_topic: string | null;
  last_error_topic: string | null;
  last_error_message: string | null;
}

export interface SemanticDiscoveryStatus {
  running: boolean;
  enabled: boolean;
  request_pending: boolean;
  pool_version: number;
  last_processed_version: number | null;
  run_count: number;
  published_count: number;
  failed_count: number;
  stale_discard_count: number;
  candidate_count: number;
  noise_topic_count: number;
  last_error_message: string | null;
}

export interface SemanticPersistenceStatus {
  enabled: boolean;
  running: boolean;
  restored: boolean;
  degraded: boolean;
  schema_version: number;
  current_generation: number;
  persisted_generation: number | null;
  save_pending: boolean;
  save_count: number;
  restore_count: number;
  failed_save_count: number;
  failed_restore_count: number;
  last_saved_at: string | null;
  last_restored_at: string | null;
  last_error_message: string | null;
  compatibility_error: string | null;
}
