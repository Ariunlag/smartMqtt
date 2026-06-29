import { useGroupStore } from "../../store/useGroupStore";

export default function GroupList() {
  const groups = useGroupStore((s) => s.groups);
  const selectedGroupId = useGroupStore((s) => s.selectedGroupId);
  const selectGroup = useGroupStore((s) => s.selectGroup);

  return (
    <div>
      <h2 className="panel-header">Detected tag based sets</h2>
      <ul className="panel-list">
        {groups.length === 0 && (
          <li style={{ color: "#aaa" }}>No tag sets available</li>
        )}

        {groups.map((g) => {
          const isActive = g.id === selectedGroupId;
          return (
            <li
              key={g.id}
              className={`list-item ${isActive ? "active" : ""}`}
              onClick={() => selectGroup(g.id)}
              style={{
                cursor: "pointer",
                background: isActive ? "rgba(0,150,255,0.15)" : "transparent",
                borderLeft: isActive ? "3px solid var(--accent)" : "3px solid transparent",
              }}
            >
              {g.tags.join(", ")}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
