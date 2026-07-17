import { useBootstrap } from "./hooks/useBootstrap"
import { useWebSocket } from "./hooks/useWebSocket"

import MqttManager from "./components/mqtt/MqttManager";
import DuplicateManager from "./components/duplicates/DuplicateManager";
import ClassBuilder from "./components/classes/ClassBuilder";
import SavedClasses from "./components/savedClasses/SavedClasses";
import GroupManager from "./components/groups/GroupManager";


export default function App() {
  const { ready, error } = useBootstrap()
  useWebSocket(ready)

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
        <span className="app-header__status">
          <span className="status-dot" /> Connected
        </span>
      </header>

      <main className="features">
        <MqttManager />
        <DuplicateManager />
        <ClassBuilder />
        <SavedClasses />
        <GroupManager />
      </main>
    </div>
  );
}