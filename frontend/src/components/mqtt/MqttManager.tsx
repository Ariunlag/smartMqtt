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
        height: "100%",       
        overflow: "hidden", 
        minHeight: 0,  
      }}
    > 
      <h2 className="panel-header">MQTT Topics</h2>
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
