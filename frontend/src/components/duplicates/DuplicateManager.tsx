import SplitLayout from "../layout/SplitLayout";
import DupeList from "./DupeList";
import DupeGraph from "./DupeGraph";
import { useDuplicateStore } from "../../store/useDuplicateStore";
import { DupeAction } from "../../types/api_models";

export default function DupeManager() {
  const { selectedPair, confirmDuplicate } = useDuplicateStore();

  const handleAction = async (action: DupeAction, target?: string) => {
    if (!selectedPair) return;

    await confirmDuplicate({
      topics: selectedPair.topics,
      action,
      target: target ?? null, // needed for UNSUBSCRIBE
    });
  };

  return (
    <SplitLayout

      left={
        <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
          <h2 className="panel-header">Detected Duplicate Pairs</h2>
          <DupeList />
        </div>
      }
      right={
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <h3 className="panel-header">Duplicate Pair Details</h3>
          <DupeGraph dupe={selectedPair} />

          {selectedPair && (
            <div className="dupe-actions">
              <button
                className="danger"
                onClick={() => handleAction(DupeAction.UNSUBSCRIBE, selectedPair.topics[0])}
              >
                Unsubscribe A
              </button>
              <button
                className="danger"
                onClick={() => handleAction(DupeAction.UNSUBSCRIBE, selectedPair.topics[1])}
              >
                Unsubscribe B
              </button>
              <button
                className="success"
                onClick={() => handleAction(DupeAction.KEEP_BOTH)}
              >
                Keep Both
              </button>
            </div>
          )}
        </div>
      }
    />
  );
}
