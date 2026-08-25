import { useEffect, useMemo, useState } from "react";
import axios from "axios";

import {
  applyClassAction,
  getClassRecommendations,
} from "../../services/classRecommendationApi";
import { useInfluxStore } from "../../store/useInfluxStore";
import type {
  ClassActionType,
  ClassRecommendation,
} from "../../types/api_models";

const percent = (value: number | null) =>
  value === null ? "N/A" : `${(value * 100).toFixed(1)}%`;

function errorMessage(error: unknown) {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data.detail || error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}

export default function RecommendationsManager() {
  const classes = useInfluxStore((state) => state.classes);
  const getClasses = useInfluxStore((state) => state.getClasses);
  const [className, setClassName] = useState("");
  const [recommendations, setRecommendations] = useState<ClassRecommendation[]>([]);
  const [manualTopic, setManualTopic] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => classes.find((item) => item.name === className) ?? null,
    [classes, className],
  );

  useEffect(() => {
    if (!className && classes[0]) setClassName(classes[0].name);
  }, [className, classes]);

  const refresh = async () => {
    if (!className) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getClassRecommendations(className);
      setRecommendations(result.recommendations);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // refresh is intentionally keyed by the selected source-of-truth class.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [className]);

  const act = async (action: ClassActionType, row: ClassRecommendation) => {
    setError(null);
    try {
      await applyClassAction(className, {
        action,
        topic: row.canonical_topic,
        topic_representation_version: row.topic_representation_version,
        class_profile_version: row.class_profile_version,
        recommendation_id: row.recommendation_id,
      });
      await getClasses();
      await refresh();
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  };

  const manual = async (action: "MANUAL_ADD" | "MANUAL_REMOVE", topic: string) => {
    if (!topic.trim()) return;
    setError(null);
    try {
      await applyClassAction(className, { action, topic: topic.trim() });
      setManualTopic("");
      await getClasses();
      await refresh();
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  };

  return (
    <section className="recommendations" aria-labelledby="recommendations-title">
      <header className="recommendations__header">
        <div>
          <h2 id="recommendations-title">Class recommendations</h2>
          <p>Pair-level comparison evidence against your saved classes.</p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={!className || loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <div className="recommendations__class-controls">
        <label>
          Saved class
          <select value={className} onChange={(event) => setClassName(event.target.value)}>
            {classes.length === 0 && <option value="">No saved classes</option>}
            {classes.map((item) => <option key={item.class_id} value={item.name}>{item.name}</option>)}
          </select>
        </label>
        <label>
          Manual topic membership
          <span className="recommendations__manual">
            <input
              className="panel-input"
              value={manualTopic}
              onChange={(event) => setManualTopic(event.target.value)}
              placeholder="topic/path"
            />
            <button type="button" onClick={() => void manual("MANUAL_ADD", manualTopic)} disabled={!className || !manualTopic.trim()}>
              Manual Add
            </button>
          </span>
        </label>
      </div>

      {selected && (
        <div className="recommendations__members">
          <strong>Current members</strong>
          {selected.topics.length === 0 ? <span>None</span> : selected.topics.map((topic) => (
            <span key={topic} className="recommendations__member">
              {topic}
              <button type="button" onClick={() => void manual("MANUAL_REMOVE", topic)} aria-label={`Remove member ${topic}`}>
                Remove Member
              </button>
            </span>
          ))}
        </div>
      )}

      {error && <p className="recommendations__error" role="alert">{error}</p>}
      {!loading && className && recommendations.length === 0 && (
        <p className="empty-note">No current recommendations for this class.</p>
      )}

      <div className="recommendations__list">
        {recommendations.map((row) => <RecommendationCard key={row.recommendation_id} row={row} act={act} />)}
      </div>
    </section>
  );
}

function RecommendationCard({
  row,
  act,
}: {
  row: ClassRecommendation;
  act: (action: ClassActionType, row: ClassRecommendation) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const channels = [
    ["Key", row.channel_scores.key],
    ["Value", row.channel_scores.value],
    ["Key + Value", row.channel_scores.key_value],
    ["Schema", row.channel_scores.schema],
    ["Numeric Key", row.channel_scores.numeric_key],
    ["Stream Context", row.channel_scores.stream_context],
  ] as const;
  return (
    <article className="recommendation-card">
      <div className="recommendation-card__heading">
        <div>
          <h3>#{row.rank} {row.canonical_topic}</h3>
          <p>
            Overall similarity <strong>{percent(row.overall_score)}</strong> · Coverage {row.coverage.matched_pair_count} / {row.coverage.candidate_pair_count} pairs
          </p>
        </div>
        {row.duplicate_pending && <span className="recommendation-card__pending">Duplicate review pending</span>}
      </div>
      <dl className="recommendation-card__channels">
        {channels.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{percent(value)}</dd></div>)}
      </dl>
      <button type="button" className="recommendation-card__evidence-toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
        {expanded ? "Hide pair evidence" : "Show pair evidence"}
      </button>
      {expanded && (
        <div className="recommendation-card__evidence">
          {row.matched_pairs.map((match) => (
            <div key={`${match.candidate.source}:${match.candidate.normalized_key}:${match.prototype_id}`}>
              <strong>{match.candidate.source}/{match.candidate.normalized_key}:{match.candidate.datatype}</strong>
              <span aria-hidden>→</span>
              <strong>{match.prototype.source}/{match.prototype.normalized_key}:{match.prototype.datatype}</strong>
              <small>
                Key {percent(match.scores.key)} · Value {percent(match.scores.value)} · Key + Value {percent(match.scores.key_value)} · Schema {percent(match.scores.schema)} · Numeric Key {percent(match.scores.numeric_key)}
              </small>
            </div>
          ))}
          {row.unmatched_candidate_pairs.length > 0 && (
            <p>Unmatched candidate pairs: {row.unmatched_candidate_pairs.map((pair) => `${pair.source}/${pair.normalized_key}:${pair.datatype}`).join(", ")}</p>
          )}
        </div>
      )}
      <div className="recommendation-card__actions">
        <button type="button" className="success" onClick={() => void act("RECOMMENDATION_ACCEPT", row)}>Accept Recommendation</button>
        <button type="button" className="danger" onClick={() => void act("RECOMMENDATION_REJECT", row)}>Reject Recommendation</button>
        <button type="button" onClick={() => void act("RECOMMENDATION_DISMISS", row)}>Dismiss</button>
      </div>
    </article>
  );
}
