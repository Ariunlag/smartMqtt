import { useEffect, useMemo, useState } from "react";

import SplitLayout from "../layout/SplitLayout";
import RecommendationGraph from "./RecommendationGraph";
import {
  actionNotice,
  percentText,
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

function DiscoveryEvidenceSummary({ group }: { group: RecommendationGroup }) {
  const channels = group.discoveryEvidence ?? [];

  if (channels.length === 0) {
    if (group.discoveryChannels.length === 0) return null;
    return (
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
    );
  }

  return (
    <section aria-label="Recommendation reasons">
      <h5 className="panel-header">Recommended because</h5>
      <div className="rec-evidence">
        {channels.map((channel) => {
          const topicCount = new Set(channel.items.map((item) => item.topic)).size;
          const texts = Array.from(
            new Set(
              channel.items
                .map((item) => item.text?.trim())
                .filter((text): text is string => Boolean(text)),
            ),
          );
          const similarities = channel.items.map((item) => item.similarity);
          const low = Math.min(...similarities);
          const high = Math.max(...similarities);
          const exactSharedText =
            texts.length === 1 && similarities.every((value) => value >= 0.999);
          const similarity =
            exactSharedText
              ? "Exact shared match"
              : low === high
                ? `Similarity ${percentText(low)}`
                : `Similarity ${percentText(low)}–${percentText(high)}`;

          return (
            <section key={channel.channelId}>
              <div className="rec-evidence__head">
                <strong>{channel.channelLabel}</strong>
                <span>{topicCount} topics</span>
              </div>

              {["key", "value", "key_value"].includes(channel.channelId) && texts.length > 0 && (
                <div className="rec-chips">
                  {texts.slice(0, 6).map((text) => (
                    <span className="rec-chip" key={text}>
                      {text}
                    </span>
                  ))}
                  {texts.length > 6 && (
                    <span className="rec-chip">+{texts.length - 6} more</span>
                  )}
                </div>
              )}

              {channel.channelId === "schema" && (
                <p className="empty-note">
                  Similar tag and field structure across these topics.
                </p>
              )}

              {channel.channelId === "stream_context" && (
                <p className="empty-note">
                  Similar whole-stream context across these topics.
                </p>
              )}

              <small>{similarity}</small>
            </section>
          );
        })}
      </div>
    </section>
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

      <DiscoveryEvidenceSummary group={group} />

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
                      {member.detail && <span className="score">{member.detail}</span>}
                    </div>
                    <div className="rec-actions">
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

