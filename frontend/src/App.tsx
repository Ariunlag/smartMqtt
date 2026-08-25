import { useState } from "react"

import { useBootstrap } from "./hooks/useBootstrap"
import { useWebSocket } from "./hooks/useWebSocket"
import { useConnectionStore, type ConnectionStatus } from "./store/useConnectionStore"

import MqttManager from "./components/mqtt/MqttManager";
import DuplicateManager from "./components/duplicates/DuplicateManager";
import ClassBuilder from "./components/classes/ClassBuilder";
import SavedClasses from "./components/savedClasses/SavedClasses";
import GroupManager from "./components/groups/GroupManager";
import RecommendationsManager from "./components/recommendations/RecommendationsManager";


const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  connected: "Connected",
  reconnecting: "Reconnecting…",
  offline: "Offline",
};

type TabId = "mqtt" | "duplicates" | "builder" | "classes" | "groups" | "recommendations";

const TABS: Array<{ id: TabId; label: string; icon: string }> = [
  { id: "mqtt", label: "MQTT", icon: "◉" },
  { id: "duplicates", label: "Duplicates", icon: "⧉" },
  { id: "builder", label: "Class Builder", icon: "◈" },
  { id: "classes", label: "Saved Classes", icon: "▤" },
  { id: "groups", label: "Tag Groups", icon: "⌗" },
  { id: "recommendations", label: "Recommendations", icon: "◍" },
];

export default function App() {
  const { ready, error } = useBootstrap()
  useWebSocket(ready)
  const status = useConnectionStore((s) => s.status)
  const [activeTab, setActiveTab] = useState<TabId>("mqtt")

  if (!ready) {
    return <div className="loading">{error || "Waiting for backend…"}</div>
  }

  // Every panel stays mounted so live sockets, polling and in-progress edits
  // survive tab switches; only the active one is rendered.
  const panel = (id: TabId, children: React.ReactNode, scroll = false) => (
    <div
      key={id}
      id={`panel-${id}`}
      role="tabpanel"
      aria-labelledby={`tab-${id}`}
      className={`workspace__panel${scroll ? " workspace__panel--scroll" : ""}`}
      hidden={activeTab !== id}
    >
      {children}
    </div>
  );

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

      <nav className="app-tabs" role="tablist" aria-label="Dashboard sections">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            id={`tab-${tab.id}`}
            type="button"
            role="tab"
            className="app-tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`panel-${tab.id}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span aria-hidden>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </nav>

      <main className="workspace">
        {panel("mqtt", <MqttManager />)}
        {panel("duplicates", <DuplicateManager />)}
        {panel("builder", <ClassBuilder />)}
        {panel("classes", <SavedClasses />)}
        {panel("groups", <GroupManager />)}
        {panel(
          "recommendations",
          <RecommendationsManager />,
          true,
        )}
      </main>
    </div>
  );
}
