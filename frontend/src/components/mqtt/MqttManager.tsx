import SplitLayout from "../layout/SplitLayout";
import SubscribeInput from "./SubscribeInput";
import SubscribedTopicsList from "./SubscribedTopicsList";
import MqttMessageLog from "./MqttMessageLog";

export default function MqttManager() {
  return (
    <SplitLayout
      left={
        <>
          <h2 className="panel-header">MQTT Topics</h2>
          <SubscribeInput />
          <SubscribedTopicsList />
        </>
      }
      right={
        <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
          <h3 className="panel-header">Received MQTT Messages</h3>
          <MqttMessageLog />
        </div>
      }
    />
  );
}
