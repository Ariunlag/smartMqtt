import GraphBox from "../graphs/GraphBox";
import GraphGrid from "../graphs/GraphGrid";
import RealtimeGraph from "../graphs/RealtimeGraph";
import { useGroupStore } from "../../store/useGroupStore";

export default function GroupGraph() {
  const topics = useGroupStore((s) => s.selectedTopics);

  if (topics.length === 0) {
    return <p style={{ color: "#aaa" }}>Select a tag set to view topics</p>;
  }

  return (
    <>
      {/* Big combined graph */}
      <GraphBox height="260px" title="Combined Graph">
        <RealtimeGraph topics={topics} />
      </GraphBox>

      {/* Individual graphs */}
      {topics.length > 1 && (
        <GraphGrid rowHeight={220}>
          {topics.map((topic) => (
            <GraphBox key={topic} title={topic}>
              <RealtimeGraph topics={[topic]} />
            </GraphBox>
          ))}
        </GraphGrid>
      )}
    </>
  );
}
