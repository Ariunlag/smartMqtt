import SplitLayout from "../layout/SplitLayout";
import SubscribeInput from "./SubscribeInput";
import SubscribedTopicsList from "./SubscribedTopicsList";
import MqttMessageLog from "./MqttMessageLog";

export default function MqttManager() {
  return (
    <SplitLayout
  left={
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",       // fill full height of the left panel
        overflow: "hidden",   // prevent spilling
      }}
    >
      <SubscribeInput />

      {/* make the topics list scrollable */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        <SubscribedTopicsList />
      </div>
    </div>
  }
  right={
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <h3 className="panel-header">Received MQTT Messages</h3>
      <MqttMessageLog />
    </div>
  }
/>

  );
}
