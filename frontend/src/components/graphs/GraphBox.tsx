import React from "react";

export default function GraphBox({
  title,
  children,
  height = "100%",
}: {
  title?: string;
  children: React.ReactNode;
  height?: string | number;
}) {
  return (
    <div className="graph-box" style={{ height }}>
      {title && <h5 title={title}>{title}</h5>}
      <div style={{ flex: 1, minHeight: 0 }}>{children}</div>
    </div>
  );
}
