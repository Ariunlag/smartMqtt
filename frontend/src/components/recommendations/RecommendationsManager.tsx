import { useEffect, useMemo, useState } from "react";
import axios from "axios";

import { getRecommendedClassCandidates } from "../../services/classRecommendationApi";
import type {
  MatchedPairEvidence,
  RecommendationDiscoveryChannel,
  RecommendedClassCandidate,
  RecommendedClassTopicEvidence,
} from "../../types/api_models";

const percent = (value: number | null) =>
  value === null ? "N/A" : `${(value * 100).toFixed(1)}%`;

const CHANNEL_LABELS: Record<RecommendationDiscoveryChannel, string> = {
  key: "Similar keys",
  value: "Similar values",
  key_value: "Similar key + value meaning",
  schema: "Similar structure",
  numeric_key: "Similar numeric measurement key",
  stream_context: "Similar whole-stream context",
};

function errorMessage(error: unknown) {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data.detail || error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}

export default function RecommendationsManager() {
  const [candidates, setCandidates] = useState<RecommendedClassCandidate[]>([]);
  const [availableTopicCount, setAvailableTopicCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getRecommendedClassCandidates();
      setCandidates(result.candidates);
      setAvailableTopicCount(result.available_topics.length);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <section className="recommendations" aria-labelledby="recommendations-title">
      <header className="recommendations__header">
        <div>
          <h2 id="recommendations-title">Recommended classes</h2>
          <p>
            System-derived topic groups. Your manually saved classes remain separate.
          </p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <p className="empty-note">
        Discovery evidence available for {availableTopicCount} active topics.
      </p>
      {error && <p className="recommendations__error" role="alert">{error}</p>}
      {!loading && candidates.length === 0 && (
        <p className="empty-note">No current system-recommended class candidates.</p>
      )}

      <div className="recommendations__list">
        {candidates.map((candidate) => (
          <RecommendedClassCard key={candidate.candidate_id} candidate={candidate} />
        ))}
      </div>
    </section>
  );
}

function RecommendedClassCard({ candidate }: { candidate: RecommendedClassCandidate }) {
  const [expanded, setExpanded] = useState(false);
  const summary = useMemo(() => summarizeEvidence(candidate.evidence), [candidate.evidence]);

  return (
    <article className="recommendation-card">
      <div className="recommendation-card__heading">
        <div>
          <h3>Recommended class #{candidate.rank}</h3>
          <p>
            {candidate.member_topics.length} suggested members · anchor {candidate.anchor_topic}
          </p>
        </div>
        {summary.pendingDuplicateCount > 0 && (
          <span className="recommendation-card__pending">Duplicate review pending</span>
        )}
      </div>

      <section aria-label="Recommendation reasons">
        <strong>Recommended because</strong>
        <div className="recommendation-card__channels">
          {candidate.discovery_channels.map((channel) => (
            <span key={channel}>{CHANNEL_LABELS[channel]}</span>
          ))}
        </div>
      </section>

      <section className="recommendations__members" aria-label="Suggested members">
        <strong>Suggested members</strong>
        {candidate.member_topics.map((topic) => <span key={topic}>{topic}</span>)}
      </section>

      <dl className="recommendation-card__channels">
        <div><dt>Matched pair evidence</dt><dd>{summary.matchedPairCount}</dd></div>
        <div><dt>Tag evidence</dt><dd>{summary.tagEvidenceCount}</dd></div>
        <div><dt>Field evidence</dt><dd>{summary.fieldEvidenceCount}</dd></div>
        <div><dt>Whole-stream context</dt><dd>{percent(summary.streamContext)}</dd></div>
      </dl>

      <button
        type="button"
        className="recommendation-card__evidence-toggle"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        {expanded ? "Hide evidence" : "Show evidence"}
      </button>

      {expanded && (
        <div className="recommendation-card__evidence">
          {candidate.evidence.map((evidence) => (
            <TopicEvidence key={evidence.topic} evidence={evidence} anchor={candidate.anchor_topic} />
          ))}
        </div>
      )}
    </article>
  );
}

function TopicEvidence({
  evidence,
  anchor,
}: {
  evidence: RecommendedClassTopicEvidence;
  anchor: string;
}) {
  const tags = evidence.matched_pairs.filter((match) => match.candidate.source === "tag");
  const fields = evidence.matched_pairs.filter((match) => match.candidate.source === "field");

  return (
    <section aria-label={`Evidence for ${evidence.topic}`}>
      <h4>{evidence.topic} ↔ {anchor}</h4>
      <p>
        Matched {evidence.coverage.matched_pair_count} / {evidence.coverage.candidate_pair_count} candidate pairs · whole-stream context {percent(evidence.channel_scores.stream_context)}
      </p>
      {tags.length > 0 && <PairEvidenceGroup title="Tag evidence" matches={tags} />}
      {fields.length > 0 && <PairEvidenceGroup title="Field evidence" matches={fields} />}
    </section>
  );
}

function PairEvidenceGroup({ title, matches }: { title: string; matches: MatchedPairEvidence[] }) {
  return (
    <div>
      <strong>{title}</strong>
      {matches.map((match) => (
        <div
          key={`${match.candidate.source}:${match.candidate.normalized_key}:${match.prototype_id}`}
        >
          <strong>
            {match.candidate.normalized_key}:{match.candidate.datatype} ↔ {match.prototype.normalized_key}:{match.prototype.datatype}
          </strong>
          <small>
            Key {percent(match.scores.key)} · Value {percent(match.scores.value)} · Key + Value {percent(match.scores.key_value)} · Schema {percent(match.scores.schema)} · Numeric Key {percent(match.scores.numeric_key)}
          </small>
        </div>
      ))}
    </div>
  );
}

function summarizeEvidence(evidence: RecommendedClassTopicEvidence[]) {
  let matchedPairCount = 0;
  let tagEvidenceCount = 0;
  let fieldEvidenceCount = 0;
  let pendingDuplicateCount = 0;
  const streamContexts: number[] = [];

  for (const topicEvidence of evidence) {
    matchedPairCount += topicEvidence.matched_pairs.length;
    if (topicEvidence.duplicate_pending) pendingDuplicateCount += 1;
    for (const match of topicEvidence.matched_pairs) {
      if (match.candidate.source === "tag") tagEvidenceCount += 1;
      else fieldEvidenceCount += 1;
    }
    if (topicEvidence.channel_scores.stream_context !== null) {
      streamContexts.push(topicEvidence.channel_scores.stream_context);
    }
  }

  return {
    matchedPairCount,
    tagEvidenceCount,
    fieldEvidenceCount,
    pendingDuplicateCount,
    streamContext:
      streamContexts.length > 0
        ? Math.min(...streamContexts)
        : null,
  };
}
