import SplitLayout from "../layout/SplitLayout";
import GroupList from "./GroupList";
import GroupTopics from "./GroupTopics";
import GroupGraph from "./GroupGraph";
import SaveAsClass from "./SaveAsClass";

export default function GroupManager() {
  return (
    <SplitLayout
      left={
        <>
          <GroupList />
          <GroupTopics />
          <SaveAsClass />
        </>
      }
      right={<GroupGraph />}
    />
  );
}
