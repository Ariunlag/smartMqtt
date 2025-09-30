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

  return (
    <GraphBox>
      <RealtimeGraph
        measurements={selectedPair.topics}
        initialData={series}
        wsTopic="mqtt"
      />
    </GraphBox>
  );
}
