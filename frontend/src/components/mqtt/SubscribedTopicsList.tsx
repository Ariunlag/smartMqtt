import React from "react";
import { useMqttStore } from "../../store/useMqttStore";

const SubscribedTopicsList: React.FC = () => {
  const topics = useMqttStore((s) => s.topics);
  const removeTopic = useMqttStore((s) => s.removeTopic);

  const handleUnsubscribe = async (topic: string) => {
    try {
      await removeTopic(topic);
    } catch (error) {
      console.error(`Failed to unsubscribe from ${topic}:`, error);
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
            <button onClick={() => handleUnsubscribe(topic)} title="Unsubscribe">
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};

export default SubscribedTopicsList;
