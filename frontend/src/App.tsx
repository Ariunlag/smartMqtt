import React from "react"
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
      <h1>Influx Hub</h1>
      <div className="features">
        <MqttManager />
        <DuplicateManager />
        <ClassBuilder />
        <SavedClasses />
        <GroupManager />
      </div>
    </div>
  );
}