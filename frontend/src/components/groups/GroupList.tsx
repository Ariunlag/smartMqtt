import { useGroupStore } from "../../store/useGroupStore";

export default function GroupList() {
  const groups = useGroupStore((s) => s.groups);
  const selectedGroupId = useGroupStore((s) => s.selectedGroupId);
  const selectGroup = useGroupStore((s) => s.selectGroup);

  return (
    <div>
      <h2 className="panel-header">Detected tag based sets</h2>
      {groups.length === 0 ? (
        <p className="empty-note">No tag sets available</p>
      ) : (
        <ul className="panel-list">
          {groups.map((g) => {
            const isActive = g.id === selectedGroupId;
            return (
              <li
                key={g.id}
                className={`list-item ${isActive ? "active" : ""}`}
                onClick={() => selectGroup(g.id)}
                style={{ cursor: "pointer" }}
              >
                <span title={g.tags.join(", ")}>{g.tags.join(", ")}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
