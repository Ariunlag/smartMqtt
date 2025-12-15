import { useGroupStore } from "../../store/useGroupStore";

export default function GroupTopics() {
  const selectedTopics = useGroupStore((s) => s.selectedTopics);
  const removeTopic = useGroupStore((s) => s.removeTopic);

  return (
    <div>
      <h3 className="panel-header">Topics for the selected set</h3>
      {selectedTopics.length === 0 ? (
        <p style={{ color: "#777" }}>No topics selected</p>
      ) : (
        <ul className="panel-list">
          {selectedTopics.map((t) => (
            <li key={t} className="list-item">
              {t}
              <button onClick={() => removeTopic(t)}>x</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
