import { useEffect, useMemo, useState } from "react";

import SplitLayout from "../layout/SplitLayout";
import RecommendationGraph from "./RecommendationGraph";
import {
  actionNotice,
  type EvidenceMatch,
  type GroupAction,
  type GroupActionValues,
  type RecommendationGroup,
  type RecommendationSource,
} from "./recommendationModel";

const MEMBER_PREVIEW = 8;

/* The whole recommendation surface. This file is identical on every
 * recommendation experiment branch; the algorithm reaches it only through
 * the RecommendationSource it is handed. */
export default function RecommendationsPanel({ source }: { source: RecommendationSource }) {
  const { groups, methods, activeMethodId, loading, error, stats, details } = source;
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    // A refresh can drop the open group; fall back to the first one.
    if (selectedId && !groups.some((group) => group.id === selectedId)) {
      setSelectedId(null);
    }
  }, [groups, selectedId]);

  const selected = groups.find((group) => group.id === selectedId) ?? groups[0] ?? null;
  const activeMethod = methods.find((method) => method.id === activeMethodId) ?? null;

  return (
    <SplitLayout
      left={
        <div className="rec-sidebar">
          <h2 className="panel-header">Recommended Classes</h2>

          <label>
            Recommendation method
            <select
              aria-label="Recommendation method"
              value={activeMethodId ?? ""}
              disabled={loading || methods.length === 0}
              onChange={(event) => void source.refresh(event.target.value)}
            >
              {methods.map((method) => (
                <option key={method.id} value={method.id}>
                  {method.label}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            className="panel-button"
            disabled={loading}
            onClick={() => void source.refresh()}
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>

          <dl className="rec-stats">
            {stats.map((stat) => (
              <div key={stat.label}>
                <dt>{stat.label}</dt>
                <dd>{stat.value}</dd>
              </div>
            ))}
          </dl>

          {error && (
            <p className="rec-error" role="alert">
              {error}
            </p>
          )}

          {groups.length === 0 ? (
            <p className="empty-note">
              No candidate groups in the current evidence snapshot.
            </p>
          ) : (
            <ul className="panel-list" aria-label="Recommended groups">
              {groups.map((group) => (
                <li
                  key={group.id}
                  className={`list-item rec-group-item${group.id === selected?.id ? " active" : ""}`}
                  onClick={() => setSelectedId(group.id)}
                >
                  <div>
                    <span className="rec-group-item__title">{group.title}</span>
                    <span className="score">
                      {group.members.length} topics · {group.status}
                    </span>
                  </div>
                  {group.reviewPending && (
                    <span className="rec-badge rec-badge--pending">Review pending</span>
                  )}
                </li>
              ))}
            </ul>
          )}

          <details className="rec-details">
            <summary>Method details</summary>
            {activeMethod && <p>{activeMethod.description}</p>}
            <div className="rec-channels">
              {source.channels.map((channel) => (
                <div key={channel.id}>
                  <span>{channel.label}</span>
                  <strong>{channel.detail}</strong>
                </div>
              ))}
            </div>
            {details.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
            <p>
              Viewing a graph does not train the model. Add, remove, confirm, save, and
              usefulness actions are explicit feedback.
            </p>
          </details>
        </div>
      }
      right={
        <div className="rec-detail">
          <h3 className="panel-header">Group Details</h3>
          {selected ? (
            <GroupDetail
              key={selected.id}
              group={selected}
              availableTopics={source.availableTopics}
              apply={source.apply}
            />
          ) : (
            <p className="empty-note">Select a recommended group to review it.</p>
          )}
        </div>
      }
    />
  );
}

function GroupDetail({
  group,
  availableTopics,
  apply,
}: {
  group: RecommendationGroup;
  availableTopics: string[];
  apply: RecommendationSource["apply"];
}) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [topic, setTopic] = useState("");
  const [name, setName] = useState("");
  const [openTopic, setOpenTopic] = useState<string | null>(null);

  const act = async (action: GroupAction, values: GroupActionValues = {}) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apply(group.id, action, values);
      setNotice(actionNotice(action, values));
      setAdding(false);
      setSaving(false);
      setTopic("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const members = showAll ? group.members : group.members.slice(0, MEMBER_PREVIEW);
  // Stable identity: the graph keys its fetch effect on this array, so a fresh
  // one on every render would reload in a loop.
  const memberTopics = useMemo(
    () => group.members.map((member) => member.topic),
    [group.members],
  );
  const available = availableTopics.filter((item) => !memberTopics.includes(item));

  return (
    <article className="rec-group" aria-label={group.title}>
      <header className="rec-group__header">
        <div>
          <h4>{group.title}</h4>
          <p className="empty-note">
            {group.members.length} topics · {group.status}
          </p>
        </div>
        <div className="rec-group__badges">
          {group.dismissed && <span className="rec-badge">Dismissed</span>}
          {group.reviewPending && (
            <span className="rec-badge rec-badge--pending">Duplicate review pending</span>
          )}
        </div>
      </header>

      {group.discoveryChannels.length > 0 && (
        <section aria-label="Recommendation reasons">
          <h5 className="panel-header">Recommended because</h5>
          <div className="rec-chips">
            {group.discoveryChannels.map((label) => (
              <span className="rec-chip" key={label}>
                {label}
              </span>
            ))}
          </div>
        </section>
      )}

      {!group.dismissed && (
        <>
          <section aria-label="Group members">
            <h5 className="panel-header">Suggested members</h5>
            <ul className="panel-list" aria-label="Suggested members">
              {members.map((member) => (
                <li className="list-item rec-member" key={member.topic}>
                  <div className="rec-member__row">
                    <div>
                      <span className="rec-member__topic">{member.topic}</span>
                      <span className="score">{member.detail}</span>
                    </div>
                    <div className="rec-actions">
                      <button
                        type="button"
                        aria-expanded={openTopic === member.topic}
                        onClick={() =>
                          setOpenTopic(openTopic === member.topic ? null : member.topic)
                        }
                      >
                        Why?
                      </button>
                      <button
                        type="button"
                        className="success"
                        disabled={busy || member.confirmed}
                        onClick={() => void act("confirm", { topic: member.topic })}
                      >
                        {member.confirmed ? "Confirmed" : "Belongs"}
                      </button>
                      <button
                        type="button"
                        className="danger"
                        disabled={busy}
                        aria-label={`Remove ${member.topic}`}
                        onClick={() => void act("remove", { topic: member.topic })}
                      >
                        Remove
                      </button>
                    </div>
                  </div>

                  {openTopic === member.topic && (
                    <div className="rec-evidence">
                      {member.evidence.map((row) => (
                        <section key={row.channelId}>
                          <div className="rec-evidence__head">
                            <strong>{row.channelLabel}</strong>
                            <span>{row.value}</span>
                          </div>
                          {row.detail && <small>{row.detail}</small>}
                          {row.matches.map((match, index) => (
                            <div className="rec-evidence__match" key={index}>
                              <p>
                                {match.left} ↔ {match.right}
                              </p>
                              {match.detail && <small>{match.detail}</small>}
                              <ShapePreview match={match} />
                            </div>
                          ))}
                        </section>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            {group.members.length > MEMBER_PREVIEW && (
              <button type="button" onClick={() => setShowAll(!showAll)}>
                {showAll ? "Show fewer topics" : `Show all ${group.members.length} topics`}
              </button>
            )}
          </section>

          {group.proposals.length > 0 && (
            <details className="rec-details">
              <summary>Suggested additions ({group.proposals.length})</summary>
              {group.proposals.map((proposal) => (
                <div className="rec-proposal" key={proposal.topic}>
                  <span className="rec-member__topic">
                    {proposal.topic} · {proposal.detail}
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void act("add", { topic: proposal.topic })}
                  >
                    Add
                  </button>
                </div>
              ))}
            </details>
          )}

          <RecommendationGraph topics={memberTopics} />

          <footer className="rec-actions">
            <button
              type="button"
              disabled={busy || available.length === 0}
              onClick={() => {
                setAdding(!adding);
                setSaving(false);
              }}
            >
              Add topic
            </button>
            {!group.savedClass && (
              <button
                type="button"
                className="panel-button"
                disabled={busy || group.members.length === 0}
                onClick={() => {
                  setSaving(!saving);
                  setAdding(false);
                }}
              >
                Save as Class
              </button>
            )}
            <button
              type="button"
              className="success"
              disabled={busy}
              onClick={() => void act("useful")}
            >
              Useful group
            </button>
            {!group.savedClass && (
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={() => void act("dismiss")}
              >
                Not useful
              </button>
            )}
            {group.canUndo && (
              <button type="button" disabled={busy} onClick={() => void act("undo")}>
                Undo last edit
              </button>
            )}
          </footer>

          {adding && (
            <form
              className="rec-form"
              onSubmit={(event) => {
                event.preventDefault();
                void act("add", { topic });
              }}
            >
              <label>
                Topic to add
                <select
                  aria-label="Topic to add"
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  required
                >
                  <option value="">Choose a topic</option>
                  {available.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" className="panel-button" disabled={busy || !topic}>
                Add selected topic
              </button>
            </form>
          )}

          {saving && (
            <form
              className="rec-form"
              onSubmit={(event) => {
                event.preventDefault();
                void act("save", { name: name.trim() });
              }}
            >
              <label>
                Class name
                <input
                  className="panel-input"
                  aria-label="Class name"
                  value={name}
                  maxLength={200}
                  onChange={(event) => setName(event.target.value)}
                  required
                />
              </label>
              <button
                type="submit"
                className="panel-button"
                disabled={busy || !name.trim()}
              >
                Save Class
              </button>
            </form>
          )}
        </>
      )}

      <p className="empty-note" role="status">
        {notice}
      </p>
      {error && (
        <p className="rec-error" role="alert">
          {error}
        </p>
      )}
    </article>
  );
}

/* Only the series-shape channel supplies raw windows; every other channel
 * leaves the values null and renders no chart. */
function ShapePreview({ match }: { match: EvidenceMatch }) {
  if (!match.leftValues || !match.rightValues) return null;

  const paths = (values: (number | null)[]) => {
    const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
    if (finite.length === 0) return [];
    const low = Math.min(...finite);
    const range = Math.max(...finite) - low || 1;
    const segments: string[] = [];
    let segment = "";
    values.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) {
        if (segment) segments.push(segment);
        segment = "";
      } else {
        const x = (index / Math.max(1, values.length - 1)) * 200;
        segment += `${x},${46 - ((value - low) / range) * 42} `;
      }
    });
    if (segment) segments.push(segment);
    return segments;
  };

  return (
    <figure className="rec-shape">
      <svg
        role="img"
        aria-label="Time-series shape comparison, each trace scaled independently; gaps are missing samples"
        viewBox="0 0 200 50"
      >
        {paths(match.leftValues).map((points, index) => (
          <polyline key={`l${index}`} points={points} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
        ))}
        {paths(match.rightValues).map((points, index) => (
          <polyline
            key={`r${index}`}
            points={points}
            fill="none"
            stroke="var(--warning)"
            strokeWidth="1.5"
            strokeDasharray="3 2"
          />
        ))}
      </svg>
      <figcaption>
        <small>
          Compared shapes · solid: member, dashed: reference · each trace scaled
          independently
        </small>
      </figcaption>
    </figure>
  );
}
