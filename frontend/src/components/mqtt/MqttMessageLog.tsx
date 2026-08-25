import React from "react";
import { useMqttStore } from "../../store/useMqttStore";
import type { MqttMessage } from "../../types/mqtt";

// Only render the most recent slice; the store keeps more for the graphs.
const MAX_VISIBLE = 100;

const MessageRow = React.memo(function MessageRow({ msg }: { msg: MqttMessage }) {
  return (
    <li style={{ marginBottom: "6px" }}>
      <b>Topic:</b> {msg.topic}, <b>Field:</b>{" "}
      {Object.entries(msg.fields)
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ")}
      , <b>Time:</b> {new Date(msg.timestamp).toLocaleTimeString()}
    </li>
  );
});

const MqttMessageLog: React.FC = () => {
  const messages = useMqttStore((s) => s.messages);
  const visible = messages.slice(0, MAX_VISIBLE);

  return (
    <div className="message-log-wrapper">
      {visible.length === 0 && <p className="empty-note">No messages yet.</p>}
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {visible.map((msg) => (
          <MessageRow key={msg.event_id} msg={msg} />
        ))}
      </ul>
    </div>
  );
};

export default MqttMessageLog;
