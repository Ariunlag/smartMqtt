import React, { useState } from "react";
import { useMqttStore } from "../../store/useMqttStore";

const SubscribedTopicsList: React.FC = () => {
  const topics = useMqttStore((s) => s.topics);
  const removeTopic = useMqttStore((s) => s.removeTopic);

  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  const handleUnsubscribe = async (topic: string) => {
    setBusy(topic);
    setFailed((f) => ({ ...f, [topic]: false }));
    try {
      await removeTopic(topic);
      // success: topic removed from state by the store; nothing else to do
    } catch (error) {
      // Do NOT remove locally — keep state consistent with the backend and
      // surface the failure so the user can retry.
      console.error(`Failed to unsubscribe from ${topic}:`, error);
      setFailed((f) => ({ ...f, [topic]: true }));
    } finally {
      setBusy(null);
    }
  };

  if (topics.length === 0) {
    return <p style={{ color: "#aaa" }}>No subscribed topics yet.</p>;
  }

  return (
    <div>
      <h4 className="panel-header">Subscribed Topics</h4>
      <div className="panel-list">
        {topics.map((topic) => (
          <div key={topic} className="list-item">
            <span>{topic}</span>
            {failed[topic] && (
              <span role="alert" style={{ color: "var(--danger)", fontSize: "0.75rem" }}>
                Unsubscribe failed.
                <button
                  onClick={() => handleUnsubscribe(topic)}
                  disabled={busy === topic}
                  style={{ marginLeft: 6 }}
                >
                  Retry
                </button>
              </span>
            )}
            <button
              onClick={() => handleUnsubscribe(topic)}
              disabled={busy === topic}
              title="Unsubscribe"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};

export default SubscribedTopicsList;
