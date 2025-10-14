import { useEffect } from "react";
import SplitLayout from "../layout/SplitLayout";
import { useInfluxStore } from "../../store/useInfluxStore";
import GraphBox from "../graphs/GraphBox";
import GraphGrid from "../graphs/GraphGrid";
import RealtimeGraph from "../graphs/RealtimeGraph";

export default function SavedClasses() {
  const classes = useInfluxStore((s) => s.classes);
  const selectedClass = useInfluxStore((s) => s.selectedClass);
  const setSelectedClass = useInfluxStore((s) => s.setSelectedClass);
  const clearSelectedClass = useInfluxStore((s) => s.clearSelectedClass);
  const deleteClass = useInfluxStore((s) => s.deleteClass);
  const savedClassTimeseriesData = useInfluxStore((s) => s.savedClassTimeseriesData);

 
  const handleDelete = async (cls: string) => {
    const ok = window.confirm(`Delete class "${cls}"?`);
    if (!ok) return;
    await deleteClass(cls);
    if (selectedClass?.name === cls) {
    clearSelectedClass();
  }
  };

  return (
    <SplitLayout
      left={
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <h3 className="panel-header">Saved Classes</h3>

          {classes.length === 0 ? (
            <p style={{ color: "#aaa" }}>No saved classes yet.</p>
          ) : (
            <ul className="panel-list">
              {classes.map((cls) => (
                <li
                  key={cls.name}
                  className="list-item"
                  style={{
                    fontWeight: selectedClass?.name === cls.name ? "bold" : "normal",
                    cursor: "pointer",
                  }}
                  onClick={() => setSelectedClass(cls)}
                >
                  {cls.name}
                  {selectedClass?.name === cls.name && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(cls.name);
                      }}
                    >
                      ✕
                    </button>
                  )}
                </li>
              ))}
            </ul>

          )}

          {selectedClass && (
            <button onClick={clearSelectedClass} style={{ marginTop: "0.5rem" }}>
              Clear Selection
            </button>
          )}
        </div>
      }
      right={
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <h3 className="panel-header">Class Graph</h3>

          {savedClassTimeseriesData.length > 0 ? (
            <>
              <GraphBox height="260px" title={`Class name: ${selectedClass?.name}`}>
                <RealtimeGraph
                  topics={selectedClass?.topics || []}
                  initialData={savedClassTimeseriesData}
                />
              </GraphBox>


              {/* Individual topic graphs */}
              {savedClassTimeseriesData.length > 1 && (
                <GraphGrid rowHeight={220}>
                  {savedClassTimeseriesData.map((ts) => (
                    <GraphBox key={ts.measurement} title={ts.measurement}>
                      <RealtimeGraph topics={[ts.measurement]} />
                    </GraphBox>
                  ))}
                </GraphGrid>
              )}
            </>
          ) : (
            <p style={{ color: "#aaa" }}>Select a class to preview its graph.</p>
          )}
        </div>
      }
    />
  );
}
