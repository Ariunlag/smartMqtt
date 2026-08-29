import { useEffect, useMemo, useState } from "react";
import axios from "axios";

import {
  getRecommendedClassCandidates,
  submitRecommendedClassFeedback,
} from "../../services/classRecommendationApi";
import type {
  EvidenceDefinition,
  EvidenceScores,
  MatchedPairEvidence,
  RecommendationStrategyDefinition,
  RecommendedClassCandidate,
  RecommendedClassFeedbackAction,
  RecommendedClassTopicEvidence,
} from "../../types/api_models";

const percent = (value: number | null) =>
  value === null ? "N/A" : `${(value * 100).toFixed(1)}%`;

const scoreFor = (scores: EvidenceScores, evidenceId: string) =>
  scores.items.find((item) => item.evidence_id === evidenceId)?.score ?? null;

function errorMessage(error: unknown) {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data.detail || error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}

export default function RecommendationsManager() {
  const [candidates, setCandidates] = useState<RecommendedClassCandidate[]>([]);
  const [evidenceCatalog, setEvidenceCatalog] = useState<EvidenceDefinition[]>([]);
  const [strategyCatalog, setStrategyCatalog] = useState<RecommendationStrategyDefinition[]>([]);
  const [activeStrategy, setActiveStrategy] = useState<RecommendationStrategyDefinition | null>(null);
  const [availableTopicCount, setAvailableTopicCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async (strategyId?: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getRecommendedClassCandidates(
        strategyId ?? activeStrategy?.strategy_id,
      );
      setCandidates(result.candidates);
      setEvidenceCatalog(result.evidence_catalog);
      setStrategyCatalog(result.strategy_catalog);
      setActiveStrategy(result.strategy);
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

      {activeStrategy && strategyCatalog.length <= 1 && (
        <p className="empty-note">
          Method: {activeStrategy.label}. {activeStrategy.description}
        </p>
      )}
      {activeStrategy && strategyCatalog.length > 1 && (
        <label className="empty-note">
          Recommendation method{" "}
          <select
            aria-label="Recommendation method"
            value={activeStrategy.strategy_id}
            disabled={loading}
            onChange={(event) => void refresh(event.target.value)}
          >
            {strategyCatalog.map((strategy) => (
              <option key={strategy.strategy_id} value={strategy.strategy_id}>
                {strategy.label}
              </option>
            ))}
          </select>
        </label>
      )}

      <p className="empty-note">
        Discovery evidence available for {availableTopicCount} active topics.
      </p>
      {error && <p className="recommendations__error" role="alert">{error}</p>}
      {!loading && candidates.length === 0 && (
        <p className="empty-note">No current system-recommended class candidates.</p>
      )}

      <div className="recommendations__list">
        {candidates.map((candidate) => (
          <RecommendedClassCard
            key={candidate.candidate_id}
            candidate={candidate}
            evidenceCatalog={evidenceCatalog}
          />
        ))}
      </div>
    </section>
  );
}

function RecommendedClassCard({
  candidate,
  evidenceCatalog,
}: {
  candidate: RecommendedClassCandidate;
  evidenceCatalog: EvidenceDefinition[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [feedbackKey, setFeedbackKey] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const definitions = useMemo(
    () => new Map(evidenceCatalog.map((item) => [item.evidence_id, item])),
    [evidenceCatalog],
  );
  const summary = useMemo(
    () => summarizeEvidence(candidate.evidence, evidenceCatalog),
    [candidate.evidence, evidenceCatalog],
  );

  const sendFeedback = async (
    action: RecommendedClassFeedbackAction,
    topic?: string,
  ) => {
    const key = `${action}:${topic ?? "candidate"}`;
    setFeedbackKey(key);
    setFeedbackMessage(null);
    setFeedbackError(null);
    try {
      await submitRecommendedClassFeedback(candidate.candidate_id, {
        action,
        candidate_version: candidate.candidate_version,
        ...(topic ? { topic } : {}),
      });
      setFeedbackMessage(
        topic
          ? `Recorded feedback for ${topic}.`
          : "Recorded feedback for this recommended group.",
      );
    } catch (requestError) {
      setFeedbackError(errorMessage(requestError));
    } finally {
      setFeedbackKey(null);
    }
  };

  return (
    <article className="recommendation-card">
      <div className="recommendation-card__heading">
        <div>
          <h3>Recommended class #{candidate.rank}</h3>
          <p>
            {candidate.member_topics.length} suggested members · anchor {candidate.anchor_topic}
          </p>
          <small>Candidate version {candidate.candidate_version}</small>
        </div>
        {summary.pendingDuplicateCount > 0 && (
          <span className="recommendation-card__pending">Duplicate review pending</span>
        )}
      </div>

      <section aria-label="Recommendation reasons">
        <strong>Recommended because</strong>
        <div className="recommendation-card__channels">
          {candidate.discovery_channels.map((evidenceId) => (
            <span key={evidenceId}>
              {definitions.get(evidenceId)?.label ?? evidenceId}
            </span>
          ))}
        </div>
      </section>

      <section className="recommendations__members" aria-label="Suggested members">
        <strong>Suggested members</strong>
        {candidate.member_topics.map((topic) => (
          <div key={topic}>
            <span>{topic}</span>{" "}
            <button
              type="button"
              disabled={feedbackKey !== null}
              onClick={() => void sendFeedback("KEEP_TOPIC", topic)}
            >
              Belongs
            </button>{" "}
            <button
              type="button"
              disabled={feedbackKey !== null}
              onClick={() => void sendFeedback("REMOVE_TOPIC", topic)}
            >
              Doesn't belong
            </button>
          </div>
        ))}
      </section>

      <section aria-label="Recommendation feedback">
        <strong>Is this group useful?</strong>{" "}
        <button
          type="button"
          disabled={feedbackKey !== null}
          onClick={() => void sendFeedback("ACCEPT_CANDIDATE")}
        >
          Useful group
        </button>{" "}
        <button
          type="button"
          disabled={feedbackKey !== null}
          onClick={() => void sendFeedback("DISMISS_CANDIDATE")}
        >
          Not useful
        </button>
        {feedbackMessage && <p role="status">{feedbackMessage}</p>}
        {feedbackError && <p className="recommendations__error" role="alert">{feedbackError}</p>}
      </section>

      <dl className="recommendation-card__channels">
        <div><dt>Matched pair evidence</dt><dd>{summary.matchedPairCount}</dd></div>
        <div><dt>Tag evidence</dt><dd>{summary.tagEvidenceCount}</dd></div>
        <div><dt>Field evidence</dt><dd>{summary.fieldEvidenceCount}</dd></div>
        {summary.streamEvidence.map(({ definition, score }) => (
          <div key={definition.evidence_id}>
            <dt>{definition.label}</dt>
            <dd>{percent(score)}</dd>
          </div>
        ))}
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
            <TopicEvidence
              key={evidence.topic}
              evidence={evidence}
              anchor={candidate.anchor_topic}
              evidenceCatalog={evidenceCatalog}
            />
          ))}
        </div>
      )}
    </article>
  );
}

function TopicEvidence({
  evidence,
  anchor,
  evidenceCatalog,
}: {
  evidence: RecommendedClassTopicEvidence;
  anchor: string;
  evidenceCatalog: EvidenceDefinition[];
}) {
  const tags = evidence.matched_pairs.filter((match) => match.candidate.source === "tag");
  const fields = evidence.matched_pairs.filter((match) => match.candidate.source === "field");
  const streamEvidence = evidenceCatalog
    .filter((definition) => definition.scope === "stream")
    .map((definition) => ({
      definition,
      score: scoreFor(evidence.channel_scores, definition.evidence_id),
    }));

  return (
    <section aria-label={`Evidence for ${evidence.topic}`}>
      <h4>{evidence.topic} ↔ {anchor}</h4>
      <p>
        Matched {evidence.coverage.matched_pair_count} / {evidence.coverage.candidate_pair_count} candidate pairs
        {streamEvidence.map(({ definition, score }) => (
          <span key={definition.evidence_id}> · {definition.label} {percent(score)}</span>
        ))}
      </p>
      {tags.length > 0 && (
        <PairEvidenceGroup title="Tag evidence" matches={tags} evidenceCatalog={evidenceCatalog} />
      )}
      {fields.length > 0 && (
        <PairEvidenceGroup title="Field evidence" matches={fields} evidenceCatalog={evidenceCatalog} />
      )}
    </section>
  );
}

function PairEvidenceGroup({
  title,
  matches,
  evidenceCatalog,
}: {
  title: string;
  matches: MatchedPairEvidence[];
  evidenceCatalog: EvidenceDefinition[];
}) {
  const pairDefinitions = new Map(
    evidenceCatalog
      .filter((definition) => definition.scope === "pair")
      .map((definition) => [definition.evidence_id, definition]),
  );

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
            {match.scores.items.map((item, index) => (
              <span key={item.evidence_id}>
                {index > 0 ? " · " : ""}
                {pairDefinitions.get(item.evidence_id)?.label ?? item.evidence_id} {percent(item.score)}
              </span>
            ))}
          </small>
        </div>
      ))}
    </div>
  );
}

function summarizeEvidence(
  evidence: RecommendedClassTopicEvidence[],
  evidenceCatalog: EvidenceDefinition[],
) {
  let matchedPairCount = 0;
  let tagEvidenceCount = 0;
  let fieldEvidenceCount = 0;
  let pendingDuplicateCount = 0;

  for (const topicEvidence of evidence) {
    matchedPairCount += topicEvidence.matched_pairs.length;
    if (topicEvidence.duplicate_pending) pendingDuplicateCount += 1;
    for (const match of topicEvidence.matched_pairs) {
      if (match.candidate.source === "tag") tagEvidenceCount += 1;
      else fieldEvidenceCount += 1;
    }
  }

  const streamEvidence = evidenceCatalog
    .filter((definition) => definition.scope === "stream")
    .map((definition) => {
      const values = evidence
        .map((topicEvidence) => scoreFor(topicEvidence.channel_scores, definition.evidence_id))
        .filter((value): value is number => value !== null);
      return {
        definition,
        score: values.length > 0 ? Math.min(...values) : null,
      };
    });

  return {
    matchedPairCount,
    tagEvidenceCount,
    fieldEvidenceCount,
    pendingDuplicateCount,
    streamEvidence,
  };
}