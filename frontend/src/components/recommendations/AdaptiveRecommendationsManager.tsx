import { useEffect, useState } from "react";
import axios from "axios";
import { getAdaptiveRecommendations, editAdaptiveGroup } from "../../services/adaptiveRecommendationApi";
import type { AdaptiveGroup, AdaptiveResponse, GroupAction } from "../../services/adaptiveRecommendationApi";
import { useInfluxStore } from "../../store/useInfluxStore";

const errorText = (error: unknown) => axios.isAxiosError<{detail?: string}>(error)
  ? error.response?.data.detail ?? error.message : error instanceof Error ? error.message : "Request failed";
const similarity = (value: number | null | undefined) => value == null ? "Insufficient evidence" : value.toFixed(3);

export default function AdaptiveRecommendationsManager() {
  const [result, setResult] = useState<AdaptiveResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = async () => {
    setBusy(true); setError(null);
    try { setResult(await getAdaptiveRecommendations()); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  useEffect(() => { void refresh(); }, []);
  const changed = (group: AdaptiveGroup) => {
    setResult(previous => previous ? {...previous, groups: previous.groups.map(g => g.group_id === group.group_id ? group : g)} : previous);
    void useInfluxStore.getState().getClasses();
  };
  return <section className="adaptive" aria-label="Adaptive recommendations">
    <header className="adaptive__header">
      <div><h2>Recommended classes</h2><p>Review similar topics, edit a group, and save it as a Class.</p></div>
      <button onClick={() => void refresh()} disabled={busy}>{busy ? "Refreshing…" : "Refresh"}</button>
    </header>
    {error && <p role="alert" className="recommendations__error">{error}</p>}
    {result && <>
      <p className="adaptive__status">Environment: <strong>{result.environment_id}</strong> · {result.available_topics.length} topics · {result.model.status === "learned" ? "Using learned weights" : "Using baseline weights"}</p>
      <details className="adaptive__learning"><summary>Learning details</summary>
        <p>{result.feedback_count} distinct membership labels. Updates run in the background when there is enough diverse positive and negative feedback.</p>
        <div className="adaptive__weights">{result.catalog.map(channel => <div key={channel.evidence_id}>
          <span>{channel.label}</span><strong>{channel.active ? `${((result.model.weights[channel.evidence_id] ?? 0) * 100).toFixed(1)}%` : "Shadow"}</strong><small>{channel.kind}</small>
        </div>)}</div>
        <p>Model version {result.model.version} · {result.model.updated_at ? `Last evaluation: ${new Date(result.model.updated_at).toLocaleString()}` : "No learned update yet"}</p>
        {result.model.evaluation && <p>Held-out log loss: candidate {result.model.evaluation.candidate_loss.toFixed(3)}, baseline {result.model.evaluation.baseline_loss.toFixed(3)}. {result.model.last_update_accepted ? "Update accepted." : "Previous weights retained."}</p>}
        {result.background_error && <p role="status">Learning is temporarily unavailable. Existing weights are retained.</p>}
        <p>Membership similarity includes matched-tag coverage. It is not a probability of correctness.</p>
        {result.discovery && <p>{result.discovery.mode === "approximate" ? "Approximate search" : "Exact search"}: {result.discovery.scored_pairs.toLocaleString()} of {result.discovery.possible_pairs.toLocaleString()} topic pairs checked · {result.discovery.elapsed_seconds.toFixed(2)}s. Approximate search can miss matching topics.</p>}
        {result.series?.enabled && <p>Time-series compares synchronized changes in shape, independent of scale or units. {result.series.error ? "Window refresh unavailable; stale windows are excluded." : result.series.window_end ? `Window ending ${new Date(result.series.window_end * 1000).toLocaleString()}.` : "Waiting for numeric windows."}</p>}
      </details>
      {!result.groups.length && <p className="empty-note">No groups yet. Receive tagged MQTT messages or create a Class to start reviewing recommendations.</p>}
      <div className="adaptive__groups">{result.groups.map(group => <GroupCard key={group.group_id} group={group} result={result} onChange={changed} />)}</div>
    </>}
  </section>;
}

function GroupCard({group, result, onChange}: {group: AdaptiveGroup; result: AdaptiveResponse; onChange: (group: AdaptiveGroup) => void}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [topic, setTopic] = useState("");
  const [name, setName] = useState("");
  const [detailTopic, setDetailTopic] = useState<string | null>(null);
  const act = async (action: GroupAction, values: {topic?: string; name?: string} = {}) => {
    setBusy(true); setError(null); setNotice(null);
    try {
      onChange(await editAdaptiveGroup(group, action, values));
      setNotice(action === "undo" ? "Edit undone." : action === "save" ? "Class saved." : action === "remove" ? `${values.topic} removed.` : action === "add" ? `${values.topic} added.` : "Feedback recorded.");
      setAdding(false); setSaving(false); setTopic("");
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const members = all ? group.members : group.members.slice(0, 8);
  const available = result.available_topics.filter(t => !group.members.includes(t));
  return <article className="adaptive__card" aria-label={group.name ?? "Suggested group"}>
    <header className="adaptive__header"><div><h3>{group.name ?? "Suggested group"}</h3><p>{group.members.length} topics · {group.saved_class ? "Saved Class" : group.edited ? "Your edited group" : "System suggestion"}</p></div>{group.dismissed && <span>Dismissed</span>}</header>
    {!group.dismissed && <>
      <div className="adaptive__members" role="list" aria-label="Group members">
        {members.map(member => <div className="adaptive__member" role="listitem" key={member}>
          <div><strong className="adaptive__topic">{member}</strong><small>Similarity: {similarity(group.member_scores[member])}</small></div>
          <div className="adaptive__actions">
            <button onClick={() => setDetailTopic(detailTopic === member ? null : member)} aria-expanded={detailTopic === member}>Why?</button>
            <button disabled={busy || group.confirmed?.includes(member)} onClick={() => void act("confirm", {topic: member})}>{group.confirmed?.includes(member) ? "Confirmed" : "Belongs"}</button>
            <button disabled={busy} aria-label={`Remove ${member}`} onClick={() => void act("remove", {topic: member})}>Remove</button>
          </div>
          {detailTopic === member && <div className="adaptive__evidence">{result.catalog.map(channel => {
            const row = group.evidence[member]?.[channel.evidence_id];
            return <section key={channel.evidence_id}><strong>{channel.label}</strong><span>{row?.status === "available" ? similarity(row.score) : row?.status ?? "missing"}</span>
              {row?.status === "available" && <small>Coverage {(row.coverage * 100).toFixed(0)}% · {row.support_count ?? 0} reference topics</small>}
              {row?.matches.map((pair, i) => <div key={i}><p>{pair.left.text ?? JSON.stringify(pair.left)} ↔ {pair.right.text ?? JSON.stringify(pair.right)}</p>
                {pair.left.values && pair.right.values && <ShapePreview left={pair.left.values} right={pair.right.values} />}
              </div>)}
            </section>;
          })}</div>}
        </div>)}
      </div>
      {group.members.length > 8 && <button onClick={() => setAll(!all)}>{all ? "Show fewer topics" : `Show all ${group.members.length} topics`}</button>}
      {!!group.proposals.length && <details><summary>Suggested additions ({group.proposals.length})</summary>{group.proposals.map(proposal => <div className="adaptive__proposal" key={proposal.topic}><span className="adaptive__topic">{proposal.topic} · {similarity(proposal.score)}</span><button disabled={busy} onClick={() => void act("add", {topic: proposal.topic})}>Add</button></div>)}</details>}
      <footer className="adaptive__actions">
        <button disabled={busy || !available.length} onClick={() => {setAdding(!adding); setSaving(false);}}>Add topic</button>
        {!group.saved_class && <button disabled={busy || !group.members.length} onClick={() => {setSaving(!saving); setAdding(false);}}>Save as Class</button>}
        <button disabled={busy} onClick={() => void act("useful")}>Useful group</button>
        {!group.saved_class && <button disabled={busy} onClick={() => void act("dismiss")}>Not useful</button>}
      </footer>
      {adding && <form className="adaptive__form" onSubmit={e => {e.preventDefault(); void act("add", {topic});}}>
        <label>Topic to add<select value={topic} onChange={e => setTopic(e.target.value)} required><option value="">Choose a topic</option>{available.map(t => <option key={t} value={t}>{t}</option>)}</select></label><button disabled={busy || !topic}>Add selected topic</button>
      </form>}
      {saving && <form className="adaptive__form" onSubmit={e => {e.preventDefault(); void act("save", {name: name.trim()});}}>
        <label>Class name<input value={name} maxLength={200} onChange={e => setName(e.target.value)} required /></label><button disabled={busy || !name.trim()}>Save Class</button>
      </form>}
    </>}
    <div className="adaptive__actions"><span role="status">{notice}</span>{group.can_undo && <button disabled={busy} onClick={() => void act("undo")}>Undo last edit</button>}</div>
    {error && <p className="recommendations__error" role="alert">{error}</p>}
  </article>;
}

function ShapePreview({left, right}: {left: (number | null)[]; right: (number | null)[]}) {
  const paths = (values: (number | null)[]) => {
    const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
    if (!finite.length) return [];
    const low = Math.min(...finite), range = Math.max(...finite) - low || 1;
    const segments: string[] = []; let segment = "";
    values.forEach((value, i) => {
      if (value === null || !Number.isFinite(value)) {if (segment) segments.push(segment); segment = "";}
      else segment += `${i / Math.max(1, values.length - 1) * 200},${46 - (value - low) / range * 42} `;
    });
    if (segment) segments.push(segment);
    return segments;
  };
  return <figure style={{margin: "8px 0"}}><svg role="img" aria-label="Time-series shape comparison, each trace scaled independently; gaps are missing samples" viewBox="0 0 200 50" style={{width: "100%", maxWidth: 320, height: 80}}>
    {paths(left).map((points, i) => <polyline key={`l${i}`} points={points} fill="none" stroke="#087f8c" strokeWidth="1.5" />)}
    {paths(right).map((points, i) => <polyline key={`r${i}`} points={points} fill="none" stroke="#a55418" strokeWidth="1.5" strokeDasharray="3 2" />)}
  </svg><figcaption><small>Compared shapes · teal: member, dashed: reference · each trace scaled independently</small></figcaption></figure>;
}
