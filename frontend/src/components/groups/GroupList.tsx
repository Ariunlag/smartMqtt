import React from "react";
import { useGroupStore } from "../../store/useGroupStore";

export default function GroupList() {
  const groups = useGroupStore((s) => s.groups);
  const selectGroup = useGroupStore((s) => s.selectGroup);

  
  return (
    <div>
      <h3 className="panel-header">Tag Sets</h3>
      <ul className="panel-list">
        {groups.length === 0 && (
          <li style={{ color: "#aaa" }}>No tag sets available</li>
        )}
        {groups.map((g) => (
          <li
            key={g.id}
            className="list-item"
            onClick={() => selectGroup(g.id)}
            style={{ cursor: "pointer" }}
          >
            {g.tags.join(", ")}
          </li>
        ))}
      </ul>
    </div>
  );
}
