import React from "react";
import { useMqttStore } from "../../store/useMqttStore";

const MqttMessageLog: React.FC = () => {
  const messages = useMqttStore((s) => s.messages);

  return (
    <div className="message-log-wrapper">
      {messages.length === 0 && (
        <p style={{ color: "#aaa" }}>No messages yet.</p>
      )}
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {messages.map((msg, i) => (
          <li key={i} style={{ marginBottom: "6px" }}>
            <b>Topic:</b> {msg.topic},{" "}
            <b>Field:</b>{" "}
            {Object.entries(msg.fields)
              .map(([k, v]) => `${k}: ${v}`)
              .join(", ")}
            ,{" "}
            <b>Time:</b> {new Date(msg.timestamp).toLocaleTimeString()}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default MqttMessageLog;
