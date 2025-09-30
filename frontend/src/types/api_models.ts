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
  resolution?: string | null;
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
