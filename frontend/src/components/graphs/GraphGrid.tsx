import React from "react";

export default function GraphGrid({
  children,
  rowHeight = 190,
}: {
  children: React.ReactNode;
  rowHeight?: number;
}) {
  return (
    <div className="graph-grid" style={{ gridAutoRows: `${rowHeight}px` }}>
      {children}
    </div>
  );
}
