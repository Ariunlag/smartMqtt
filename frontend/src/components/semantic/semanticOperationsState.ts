import type {
  SemanticDiscoveryStatus,
  SemanticPersistenceStatus,
  SemanticProcessingStatus,
} from "../../types/api_models";

export type SemanticDisplayState =
  | "DISABLED"
  | "STARTING"
  | "HEALTHY"
  | "BUSY"
  | "DEGRADED"
  | "STOPPED";

export function deriveProcessingState(
  status: SemanticProcessingStatus | null,
): SemanticDisplayState {
  if (!status) return "STARTING";
  if (!status.enabled) return "DISABLED";
  if (status.last_error_message) return "DEGRADED";
  if (!status.running) return "STOPPED";
  return status.queue_size > 0 ? "BUSY" : "HEALTHY";
}

export function deriveDiscoveryState(
  status: SemanticDiscoveryStatus | null,
): SemanticDisplayState {
  if (!status) return "STARTING";
  if (!status.enabled) return "DISABLED";
  if (status.last_error_message) return "DEGRADED";
  if (!status.running) return "STOPPED";
  return status.request_pending ? "BUSY" : "HEALTHY";
}

export function derivePersistenceState(
  status: SemanticPersistenceStatus | null,
): SemanticDisplayState {
  if (!status) return "STARTING";
  if (!status.enabled) return "DISABLED";
  if (
    status.degraded ||
    status.last_error_message ||
    status.compatibility_error
  ) {
    return "DEGRADED";
  }
  if (!status.running) return "STOPPED";
  return status.save_pending ? "BUSY" : "HEALTHY";
}

export function deriveSummaryState(
  loaded: boolean,
  candidateCount: number,
  hasCurrentError: boolean,
): SemanticDisplayState {
  if (!loaded) return "STARTING";
  if (hasCurrentError) return "DEGRADED";
  return candidateCount > 0 ? "BUSY" : "HEALTHY";
}
