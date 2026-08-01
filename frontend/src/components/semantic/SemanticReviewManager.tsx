import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import {
  getSemanticReviewState,
  submitSemanticReview,
} from "../../services/semanticReviewApi";
import type {
  PendingSemanticCandidate,
  SemanticReviewResult,
} from "../../types/api_models";

function errorMessage(error: unknown): string {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data?.detail || error.message;
  }
  return error instanceof Error ? error.message : "Semantic review failed";
}

export default function SemanticReviewManager() {
  const [candidates, setCandidates] = useState<PendingSemanticCandidate[]>([]);
  const [unknownTopics, setUnknownTopics] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [classId, setClassId] = useState("");
  const [className, setClassName] = useState("");
  const [removedTopics, setRemovedTopics] = useState<Set<string>>(new Set());
  const [addedTopics, setAddedTopics] = useState<string[]>([]);
  const [selectedUnknown, setSelectedUnknown] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SemanticReviewResult | null>(null);

  const candidate = candidates[0];
  const candidateKey = candidate
    ? `${candidate.representation_name}\u0000${candidate.member_topics.join("\u0000")}`
    : "";
  const keptTopics = useMemo(
    () => candidate?.member_topics.filter((topic) => !removedTopics.has(topic)) ?? [],
    [candidate, removedTopics],
  );
  const addableTopics = useMemo(() => {
    const original = new Set(candidate?.member_topics ?? []);
    const added = new Set(addedTopics);
    return unknownTopics.filter((topic) => !original.has(topic) && !added.has(topic));
  }, [candidate, unknownTopics, addedTopics]);

  useEffect(() => {
    let active = true;
    getSemanticReviewState()
      .then((state) => {
        if (active) {
          setCandidates(state.candidates);
          setUnknownTopics(state.available_unknown_topics);
        }
      })
      .catch((requestError: unknown) => {
        if (active) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setClassId("");
    setClassName("");
    setRemovedTopics(new Set());
    setAddedTopics([]);
    setSelectedUnknown("");
  }, [candidateKey]);

  if (loading) {
    return <section className="semantic-review semantic-review--state">Loading semantic candidates…</section>;
  }

  if (error && !candidate) {
    return <section className="semantic-review semantic-review--error">{error}</section>;
  }

  if (!candidate) {
    return (
      <section className="semantic-review semantic-review--state">
        <h2>Semantic candidate review</h2>
        {result && <ResultSummary result={result} />}
        <p>No pending semantic candidates.</p>
      </section>
    );
  }

  const precision = candidate.member_topics.length
    ? keptTopics.length / candidate.member_topics.length
    : 0;
  const finalPositiveCount = keptTopics.length + addedTopics.length;
  const coverage = finalPositiveCount ? keptTopics.length / finalPositiveCount : 0;
  const partitionValid =
    keptTopics.length + removedTopics.size === candidate.member_topics.length;
  const submitDisabled =
    !classId.trim() ||
    !className.trim() ||
    !partitionValid ||
    finalPositiveCount === 0 ||
    submitting;

  const toggleTopic = (topic: string, remove: boolean) => {
    setRemovedTopics((current) => {
      const next = new Set(current);
      if (remove) next.add(topic);
      else next.delete(topic);
      return next;
    });
  };

  const addTopic = () => {
    if (!selectedUnknown) return;
    setAddedTopics((current) => [...current, selectedUnknown].sort());
    setSelectedUnknown("");
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const reviewResult = await submitSemanticReview({
        identity: {
          representation_name: candidate.representation_name,
          member_topics: candidate.member_topics,
        },
        class_id: classId.trim(),
        semantic_class_name: className.trim(),
        kept_topics: keptTopics,
        removed_topics: [...removedTopics].sort(),
        added_topics: addedTopics,
      });
      setResult(reviewResult);
      setCandidates((current) => current.slice(1));
      try {
        const refreshed = await getSemanticReviewState();
        setUnknownTopics(refreshed.available_unknown_topics);
      } catch {
        // The submitted result remains valid if the diagnostic refresh fails.
      }
    } catch (requestError: unknown) {
      setError(errorMessage(requestError));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="semantic-review" aria-labelledby="semantic-review-title">
      <h2 id="semantic-review-title">Semantic candidate review</h2>
      {result && <ResultSummary result={result} />}
      {error && <p className="semantic-review__error" role="alert">{error}</p>}

      <article className="semantic-review__card">
        <p><strong>Discovery representation:</strong> {candidate.representation_name}</p>
        <p><strong>Suggested count:</strong> {candidate.member_topics.length}</p>
        <label>
          Semantic class ID
          <input
            className="panel-input"
            value={classId}
            onChange={(event) => setClassId(event.target.value)}
          />
        </label>
        <label>
          Semantic class name
          <input
            className="panel-input"
            value={className}
            onChange={(event) => setClassName(event.target.value)}
          />
        </label>

        <div className="semantic-review__topics">
          {candidate.member_topics.map((topic) => {
            const removed = removedTopics.has(topic);
            return (
              <div className="semantic-review__topic" key={topic}>
                <span>{topic}</span>
                <div role="group" aria-label={`Membership for ${topic}`}>
                  <button
                    type="button"
                    aria-pressed={!removed}
                    onClick={() => toggleTopic(topic, false)}
                  >Keep</button>
                  <button
                    type="button"
                    aria-pressed={removed}
                    onClick={() => toggleTopic(topic, true)}
                  >Remove</button>
                </div>
              </div>
            );
          })}
        </div>

        <div className="semantic-review__add">
          <label>
            Add UNKNOWN topic
            <select
              value={selectedUnknown}
              onChange={(event) => setSelectedUnknown(event.target.value)}
            >
              <option value="">Select a topic</option>
              {addableTopics.map((topic) => <option key={topic}>{topic}</option>)}
            </select>
          </label>
          <button type="button" onClick={addTopic} disabled={!selectedUnknown}>Add topic</button>
        </div>

        <div className="semantic-review__chips">
          {addedTopics.map((topic) => (
            <span key={topic}>{topic}
              <button
                type="button"
                aria-label={`Remove added topic ${topic}`}
                onClick={() => setAddedTopics((current) => current.filter((item) => item !== topic))}
              >×</button>
            </span>
          ))}
        </div>

        <dl className="semantic-review__diagnostics">
          <div><dt>Kept</dt><dd>{keptTopics.length}</dd></div>
          <div><dt>Removed</dt><dd>{removedTopics.size}</dd></div>
          <div><dt>Added</dt><dd>{addedTopics.length}</dd></div>
          <div><dt>Suggestion precision</dt><dd>{precision.toFixed(2)}</dd></div>
          <div><dt>Suggestion coverage proxy</dt><dd>{coverage.toFixed(2)}</dd></div>
        </dl>

        <button type="button" disabled={submitDisabled} onClick={submit}>
          {submitting ? "Applying review…" : "Apply review"}
        </button>
      </article>
    </section>
  );
}

function ResultSummary({ result }: { result: SemanticReviewResult }) {
  return (
    <div className="semantic-review__success" role="status">
      <strong>Applied review for {result.semantic_class_name}</strong>
      <span>Class ID: {result.class_id}</span>
      <span>Registry updated: {result.registry_updated ? "yes" : "no"}</span>
      <span>Changed representations: {result.changed_representations.join(", ")}</span>
      <span>Constraints added: {result.constraints_added.length}</span>
      <span>Constraints removed: {result.constraints_removed.length}</span>
      <span>Prototype members: {result.prototypes[0]?.member_topics.join(", ") || "none"}</span>
    </div>
  );
}
