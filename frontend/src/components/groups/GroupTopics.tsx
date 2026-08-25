import { useGroupStore } from "../../store/useGroupStore";

export default function GroupTopics() {
  const selectedTopics = useGroupStore((s) => s.selectedTopics);
  const removeTopic = useGroupStore((s) => s.removeTopic);

  return (
    <div>
      <h3 className="panel-header">Topics for the selected set</h3>
      {selectedTopics.length === 0 ? (
        <p className="empty-note">No topics selected</p>
      ) : (
        <ul className="panel-list">
          {selectedTopics.map((t) => (
            <li key={t} className="list-item">
              <span title={t}>{t}</span>
              <button onClick={() => removeTopic(t)} title="Remove topic">
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
