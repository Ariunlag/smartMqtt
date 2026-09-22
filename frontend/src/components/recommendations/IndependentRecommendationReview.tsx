import { useEffect, useMemo, useState } from "react";
import axios from "axios";

import { submitRecommendedClassFeedback } from "../../services/classRecommendationApi";
import { useInfluxStore } from "../../store/useInfluxStore";
import type {
  RecommendedClassCandidate,
  RecommendedClassFeedbackAction,
} from "../../types/api_models";
import RecommendationGraph from "./RecommendationGraph";

function errorText(error: unknown) {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data.detail ?? error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}

export default function IndependentRecommendationReview({
  candidate,
  availableTopics,
  shadowRunId,
  liveRunId,
}: {
  candidate: RecommendedClassCandidate;
  availableTopics: string[];
  shadowRunId: string | null;
  liveRunId: string | null;
}) {
  const originalMembers = useMemo(
    () => new Set(candidate.member_topics),
    [candidate.candidate_id, candidate.candidate_version],
  );
  const [topics, setTopics] = useState<string[]>(candidate.member_topics);
  const [topicToAdd, setTopicToAdd] = useState("");
  const [className, setClassName] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTopics(candidate.member_topics);
    setTopicToAdd("");
    setClassName("");
    setNotice(null);
    setError(null);
  }, [candidate.candidate_id, candidate.candidate_version, candidate.member_topics]);

  const submit = async (action: RecommendedClassFeedbackAction, topic?: string) =>
    submitRecommendedClassFeedback(candidate.candidate_id, {
      action,
      candidate_version: candidate.candidate_version,
      ...(topic ? { topic } : {}),
      ...(shadowRunId ? { shadow_run_id: shadowRunId } : {}),
      ...(liveRunId ? { live_run_id: liveRunId } : {}),
    });

  const removeTopic = async (topic: string) => {
    if (topics.length <= 1) {
      setError("Keep at least one topic in the working group.");
      return;
    }
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await submit("REMOVE_TOPIC", topic);
      setTopics((current) => current.filter((item) => item !== topic));
      setNotice(topic + " removed. The graph and feedback now reflect this choice.");
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setBusy(false);
    }
  };

  const addTopic = async () => {
    if (!topicToAdd || topics.includes(topicToAdd)) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await submit(originalMembers.has(topicToAdd) ? "KEEP_TOPIC" : "ADD_TOPIC", topicToAdd);
      setTopics((current) => [...current, topicToAdd]);
      setNotice(topicToAdd + " added. The graph and feedback now reflect this choice.");
      setTopicToAdd("");
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setBusy(false);
    }
  };

  const saveClass = async () => {
    const name = className.trim();
    if (!name || topics.length === 0) return;

    setBusy(true);
    setNotice(null);
    setError(null);
    let saved = false;
    try {
      const store = useInfluxStore.getState();
      store.setClassNameInput(name);
      await store.setSelectedMeasurements(topics);
      await store.saveClass();
      saved = true;

      for (const topic of topics) {
        await submit(originalMembers.has(topic) ? "KEEP_TOPIC" : "ADD_TOPIC", topic);
      }
      await submit("ACCEPT_CANDIDATE");

      setNotice('Saved "' + name + '" as a Class. Final membership was recorded as explicit feedback.');
      setClassName("");
    } catch (requestError) {
      setError(
        saved
          ? "The Class was saved, but feedback recording failed: " + errorText(requestError)
          : errorText(requestError),
      );
    } finally {
      setBusy(false);
    }
  };

  const choices = availableTopics.filter((topic) => !topics.includes(topic));

  return (
    <section className="recommendations__members" aria-label="Review suggested members">
      <strong>Review suggested members</strong>
      <p className="empty-note">
        Viewing the graph does not train the model. Add, remove, confirm-by-save, and
        usefulness actions are explicit feedback.
      </p>

      {topics.map((topic) => (
        <div key={topic}>
          <span>{topic}</span>{" "}
          <button
            type="button"
            disabled={busy || topics.length <= 1}
            aria-label={"Remove " + topic}
            onClick={() => void removeTopic(topic)}
          >
            Remove
          </button>
        </div>
      ))}

      <div>
        <select
          aria-label="Topic to add"
          value={topicToAdd}
          disabled={busy || choices.length === 0}
          onChange={(event) => setTopicToAdd(event.target.value)}
        >
          <option value="">Choose a topic to add</option>
          {choices.map((topic) => (
            <option key={topic} value={topic}>{topic}</option>
          ))}
        </select>{" "}
        <button
          type="button"
          disabled={busy || !topicToAdd}
          onClick={() => void addTopic()}
        >
          Add topic
        </button>
      </div>

      <RecommendationGraph topics={topics} />

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void saveClass();
        }}
      >
        <label>
          Class name{" "}
          <input
            aria-label="Class name"
            value={className}
            maxLength={200}
            disabled={busy}
            onChange={(event) => setClassName(event.target.value)}
          />
        </label>{" "}
        <button type="submit" disabled={busy || !className.trim() || topics.length === 0}>
          Save as Class
        </button>
      </form>

      {notice && <p role="status">{notice}</p>}
      {error && <p className="recommendations__error" role="alert">{error}</p>}
    </section>
  );
}
