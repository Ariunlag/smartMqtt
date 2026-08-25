import { useDuplicateStore } from "../../store/useDuplicateStore";
import { pairKey, samePair } from "../../utils/pairKey";

export default function DupeList() {
  const { duplicates, selectPair, selectedPair } = useDuplicateStore();

  if (duplicates.length === 0) {
    return <p className="empty-note">No duplicates detected.</p>;
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
            title={`${d.topics[0]} ↔ ${d.topics[1]}`}
          >
            {/* Each topic on its own line: pair labels are long and must stay
                fully readable inside the narrow sidebar. */}
            <div className="dupe-item__topics">
              <span className="dupe-item__topic">{d.topics[0]}</span>
              <span className="dupe-item__topic">
                <span className="dupe-item__arrow" aria-hidden>
                  ↔
                </span>
                {d.topics[1]}
              </span>
            </div>
            <div className="score">Confidence score: {d.score.toFixed(2)}</div>
          </div>
        );
      })}
    </div>
  );
}
