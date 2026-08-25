import SplitLayout from "../layout/SplitLayout";
import GroupList from "./GroupList";
import GroupTopics from "./GroupTopics";
import GroupGraph from "./GroupGraph";
import SaveAsClass from "./SaveAsClass";

export default function GroupManager() {
  return (
    <SplitLayout
      left={
        <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          {/* Keep the detected-set list short so the editor below stays reachable */}
          <div style={{ maxHeight: "220px", overflowY: "auto" }}>
            <GroupList />
          </div>
          <hr />
          <GroupTopics />
          <SaveAsClass />
        </div>
      }
      right={<GroupGraph />}
    />
  );
}
