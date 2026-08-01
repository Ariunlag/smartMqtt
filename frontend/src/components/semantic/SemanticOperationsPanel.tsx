import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getSemanticClasses,
  getSemanticDiscoveryStatus,
  getSemanticPersistenceStatus,
  getSemanticProcessingStatus,
  getSemanticReviewConstraints,
  getSemanticReviewState,
} from "../../services/semanticReviewApi";
import type {
  NegativeMembershipConstraintList,
  SemanticClassList,
  SemanticDiscoveryStatus,
  SemanticPersistenceStatus,
  SemanticProcessingStatus,
  SemanticReviewState,
} from "../../types/api_models";
import {
  deriveDiscoveryState,
  derivePersistenceState,
  deriveProcessingState,
  deriveSummaryState,
  type SemanticDisplayState,
} from "./semanticOperationsState";

type EndpointName =
  | "processing"
  | "discovery"
  | "persistence"
  | "candidates"
  | "classes"
  | "constraints";

type EndpointErrors = Partial<Record<EndpointName, string>>;

const ENDPOINT_LABELS: Record<EndpointName, string> = {
  processing: "Processing status",
  discovery: "Discovery status",
  persistence: "Persistence status",
  candidates: "Candidate state",
  classes: "Semantic classes",
  constraints: "Membership constraints",
};

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return "Request failed";
}

export default function SemanticOperationsPanel() {
  const [processing, setProcessing] =
    useState<SemanticProcessingStatus | null>(null);
  const [discovery, setDiscovery] =
    useState<SemanticDiscoveryStatus | null>(null);
  const [persistence, setPersistence] =
    useState<SemanticPersistenceStatus | null>(null);
  const [reviewState, setReviewState] = useState<SemanticReviewState | null>(null);
  const [classes, setClasses] = useState<SemanticClassList | null>(null);
  const [constraints, setConstraints] =
    useState<NegativeMembershipConstraintList | null>(null);
  const [errors, setErrors] = useState<EndpointErrors>({});
  const [refreshing, setRefreshing] = useState(false);
  const mounted = useRef(false);
  const requestInFlight = useRef(false);

  const load = useCallback(async () => {
    if (requestInFlight.current) return false;
    requestInFlight.current = true;
    if (mounted.current) setRefreshing(true);

    const results = await Promise.allSettled([
      getSemanticProcessingStatus(),
      getSemanticDiscoveryStatus(),
      getSemanticPersistenceStatus(),
      getSemanticReviewState(),
      getSemanticClasses(),
      getSemanticReviewConstraints(),
    ]);

    if (mounted.current) {
      const nextErrors: EndpointErrors = {};
      const apply = <T,>(
        index: number,
        endpoint: EndpointName,
        setter: (value: T) => void,
      ) => {
        const result = results[index] as PromiseSettledResult<T>;
        if (result.status === "fulfilled") setter(result.value);
        else nextErrors[endpoint] = errorMessage(result.reason);
      };

      apply(0, "processing", setProcessing);
      apply(1, "discovery", setDiscovery);
      apply(2, "persistence", setPersistence);
      apply(3, "candidates", setReviewState);
      apply(4, "classes", setClasses);
      apply(5, "constraints", setConstraints);
      setErrors(nextErrors);
      setRefreshing(false);
    }
    requestInFlight.current = false;
    return true;
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    const pollTimer = window.setInterval(() => {
      void load();
    }, 5_000);
    return () => {
      mounted.current = false;
      window.clearInterval(pollTimer);
    };
  }, [load]);

  const summaryState = useMemo(
    () =>
      deriveSummaryState(
        reviewState !== null || classes !== null || constraints !== null,
        reviewState?.candidates.length ?? 0,
        Boolean(errors.candidates || errors.classes || errors.constraints),
      ),
    [classes, constraints, errors, reviewState],
  );

  return (
    <section
      className="semantic-operations"
      aria-labelledby="semantic-operations-title"
    >
      <div className="semantic-operations__header">
        <div>
          <h2 id="semantic-operations-title">Semantic operations</h2>
          <p>Live operational health and vector-free state diagnostics.</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="semantic-operations__grid">
        <StatusCard
          title="Processing"
          state={errors.processing ? "DEGRADED" : deriveProcessingState(processing)}
          error={errors.processing}
          values={[
            ["Queue", processing ? `${processing.queue_size} / ${processing.queue_capacity}` : "—"],
            ["Processed", processing?.processed_count ?? "—"],
            ["Failed", processing?.failed_count ?? "—"],
            ["Dropped", processing?.dropped_count ?? "—"],
          ]}
        />
        <StatusCard
          title="Discovery"
          state={errors.discovery ? "DEGRADED" : deriveDiscoveryState(discovery)}
          error={errors.discovery}
          values={[
            ["Pool version", discovery?.pool_version ?? "—"],
            ["Candidates", discovery?.candidate_count ?? "—"],
            ["Runs", discovery?.run_count ?? "—"],
            ["Stale discarded", discovery?.stale_discard_count ?? "—"],
          ]}
        />
        <StatusCard
          title="Persistence and recovery"
          state={
            errors.persistence ? "DEGRADED" : derivePersistenceState(persistence)
          }
          error={errors.persistence}
          values={[
            ["Schema", persistence?.schema_version ?? "—"],
            ["Generation", persistence?.current_generation ?? "—"],
            ["Persisted", persistence?.persisted_generation ?? "—"],
            ["Restored", persistence ? (persistence.restored ? "yes" : "no") : "—"],
          ]}
        />
        <StatusCard
          title="Semantic state summary"
          state={summaryState}
          error={errors.candidates || errors.classes || errors.constraints}
          values={[
            ["Pending candidates", reviewState?.candidates.length ?? "—"],
            ["UNKNOWN topics", reviewState?.available_unknown_topics.length ?? "—"],
            ["Known classes", classes?.classes.length ?? "—"],
            ["Constraints", constraints?.constraints.length ?? "—"],
          ]}
        />
      </div>

      {Object.entries(errors).length > 0 && (
        <div className="semantic-operations__errors" aria-label="Endpoint errors">
          {Object.entries(errors).map(([endpoint, message]) => (
            <p key={endpoint} role="alert">
              <strong>{ENDPOINT_LABELS[endpoint as EndpointName]}:</strong>{" "}
              {message}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

function StatusCard({
  title,
  state,
  values,
  error,
}: {
  title: string;
  state: SemanticDisplayState;
  values: Array<[string, string | number]>;
  error?: string;
}) {
  return (
    <article className="semantic-operations__card" aria-label={title}>
      <div className="semantic-operations__card-heading">
        <h3>{title}</h3>
        <span className="semantic-operations__state" data-state={state}>
          {state}
        </span>
      </div>
      <dl>
        {values.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {error && <span className="semantic-operations__card-error">Unavailable</span>}
    </article>
  );
}
