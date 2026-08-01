import { useBootstrap } from "./hooks/useBootstrap"
import { useWebSocket } from "./hooks/useWebSocket"
import { useConnectionStore, type ConnectionStatus } from "./store/useConnectionStore"

import MqttManager from "./components/mqtt/MqttManager";
import DuplicateManager from "./components/duplicates/DuplicateManager";
import ClassBuilder from "./components/classes/ClassBuilder";
import SavedClasses from "./components/savedClasses/SavedClasses";
import GroupManager from "./components/groups/GroupManager";
import SemanticReviewManager from "./components/semantic/SemanticReviewManager";


const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  connected: "Connected",
  reconnecting: "Reconnecting…",
  offline: "Offline",
};

export default function App() {
  const { ready, error } = useBootstrap()
  useWebSocket(ready)
  const status = useConnectionStore((s) => s.status)

  if (!ready) {
    return <div className="loading">{error || "Waiting for backend…"}</div>
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__brand">
          <span className="app-header__logo" aria-hidden>◇</span>
          <div>
            <h1>Influx Hub</h1>
            <p className="app-header__subtitle">Smart MQTT telemetry governance</p>
          </div>
        </div>
        <span className="app-header__status" data-status={status}>
          <span className="status-dot" /> {STATUS_LABEL[status]}
        </span>
      </header>

      <main className="features">
        <MqttManager />
        <DuplicateManager />
        <ClassBuilder />
        <SavedClasses />
        <GroupManager />
        <SemanticReviewManager />
      </main>
    </div>
  );
}
