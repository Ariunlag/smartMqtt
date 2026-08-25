import { useDuplicateStore } from "../../store/useDuplicateStore";
import { pairKey, samePair } from "../../utils/pairKey";

export default function DupeList() {
  const { duplicates, selectPair, selectedPair } = useDuplicateStore();

  if (duplicates.length === 0) {
    return <p style={{ color: "#aaa" }}>No duplicates detected.</p>;
  }

  return (
    <div className="panel-list">
      {duplicates.map((d) => {
        const isSelected = selectedPair && samePair(selectedPair.topics, d.topics);

        return (
          <div
            key={pairKey(d.topics)}
            className={`list-item dupe-item ${isSelected ? "selected" : ""}`}
            onClick={() => selectPair(d)}
          >
            <div>
              {d.topics[0]} ↔ {d.topics[1]}
            </div>
            <div className="score">
              Confidence score: {d.score.toFixed(2)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
