import React from "react";

export default function GraphGrid({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="graph-grid"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
        gridAutoRows: "220px",
        gap: "1rem",
        width: "100%",
      }}
    >
      {children}
    </div>
  );
}
