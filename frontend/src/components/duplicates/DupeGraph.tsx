import { useEffect } from "react";
import { useDuplicateStore } from "../../store/useDuplicateStore";
import GraphBox from "../graphs/GraphBox";
import RealtimeGraph from "../graphs/RealtimeGraph";

export default function DupeGraph() {
  const { selectedPair, series, loadPairTimeseries } = useDuplicateStore();

  useEffect(() => {
    if (selectedPair) {
      loadPairTimeseries(selectedPair.topics);
    }
  }, [selectedPair, loadPairTimeseries]);

  if (!selectedPair) {
    return <p style={{ color: "#aaa" }}>Select a duplicate to visualize</p>;
  }

  const topics = selectedPair.topics || [];

  return (
    <GraphBox height="260px" >
      <RealtimeGraph topics={topics} initialData={series} />
    </GraphBox>
  );
}
