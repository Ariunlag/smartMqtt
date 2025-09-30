import React from "react";

export default function GraphBox({
  title,
  children,
  height = "100%",   // 🔧 was "300px"
}: {
  title?: string;
  children: React.ReactNode;
  height?: string | number;
}) {
  return (
    <div
      className="graph-box"
      style={{
        height,
        background: "#181818",
        border: "1px solid #333",
        borderRadius: "8px",
        padding: "0.5rem",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {title && (
        <h5 style={{ margin: "0 0 0.5rem 0", color: "var(--accent)" }}>{title}</h5>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>{children}</div>
    </div>
  );
}
