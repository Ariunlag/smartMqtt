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
        
      }}
    >
      {title && (
        <h5 style={{ margin: "0 0 0.5rem 0", color: "var(--accent)" }}>{title}</h5>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>{children}</div>
    </div>
  );
}
