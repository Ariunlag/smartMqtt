import React from "react";

export default function GraphGrid({
  children,
  rowHeight = 220,
}: {
  children: React.ReactNode;
  rowHeight?: number;
}) {
  return (
    <div
      className="graph-grid"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
        gridAutoRows: `${rowHeight}px`,
        gap: "1rem",
        width: "100%",
      }}
    >
      {children}
    </div>
  );
}
