import SplitLayout from "../layout/SplitLayout";
import GroupList from "./GroupList";
import GroupTopics from "./GroupTopics";
import GroupGraph from "./GroupGraph";
import SaveAsClass from "./SaveAsClass";

export default function GroupManager() {
  return (
    <SplitLayout
      left={
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          {/* Scrollable shorter GroupList */}
          <div
            style={{
              flex: "0 0 240px", // fixed height (~shorter)
              overflowY: "auto",
              borderBottom: "1px solid #333",
              marginBottom: "0.5rem",
              paddingRight: "0.3rem",
            }}
          >
            <GroupList />
          </div>

          {/* Non-scrolling below */}
          <div style={{ flex: "1 1 auto", display: "flex", flexDirection: "column", gap: "1rem" }}>
            <GroupTopics />
            <SaveAsClass />
          </div>
        </div>
      }
      right={<GroupGraph />}
    />
  );
}