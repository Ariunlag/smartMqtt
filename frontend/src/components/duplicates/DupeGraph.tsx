import { useEffect } from "react";
import { useDuplicateStore } from "../../store/useDuplicateStore";
import GraphBox from "../graphs/GraphBox";
import RealtimeGraph from "../graphs/RealtimeGraph";
import type { DupeRecord } from "../../types/api_models";

export default function DupeGraph({ dupe }: { dupe?: DupeRecord | null }) {
  const { selectedPair, series, loadPairTimeseries } = useDuplicateStore();
  const effectivePair = dupe ?? selectedPair;

  useEffect(() => {
    if (effectivePair) {
      loadPairTimeseries(effectivePair.topics);
    }
  }, [effectivePair, loadPairTimeseries]);

  if (!effectivePair) {
    return <p style={{ color: "#aaa" }}>Select a duplicate to visualize</p>;
  }

  const topics = effectivePair.topics || [];

  return (
    <GraphBox height="260px" >
      <RealtimeGraph topics={topics} initialData={series} />
    </GraphBox>
  );
}
