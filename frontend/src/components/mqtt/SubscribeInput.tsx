import React, { useState } from "react";
import { subscribeTopic } from "../../services/topicApi";
import { useMqttStore } from "../../store/useMqttStore";

const SubscribeInput: React.FC = () => {
  const [topic, setTopic] = useState("");
  const topics = useMqttStore((s) => s.topics);
  const addTopic = useMqttStore((s) => s.addTopic);
  const [alert, setAlert] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!topic.trim()) {
      setAlert("Topic cannot be empty.");
      return;
    }
    if (topics.includes(topic)) {
      setAlert(`Already subscribed to "${topic}".`);
      return;
    }
    try {
      await subscribeTopic(topic);
      addTopic(topic);
      setTopic("");
      setAlert(null);
    } catch {
      setAlert(`Error subscribing to "${topic}".`);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem" }}>
        <input
          type="text"
          placeholder="Enter subscription topic…"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          className="panel-input"
        />
        <button onClick={handleSubmit} className="panel-button" title="Subscribe">
          ✓
        </button>
      </div>
      {alert && (
        <div style={{ color: "var(--danger)", fontSize: "0.78rem" }}>{alert}</div>
      )}
    </div>
  );
};

export default SubscribeInput;
