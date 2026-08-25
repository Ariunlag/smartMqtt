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
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          <h2 className="panel-header">Saved Classes</h2>

          {classes.length === 0 ? (
            <p className="empty-note">No saved classes yet.</p>
          ) : (
            <ul className="panel-list">
              {classes.map((cls) => (
                <li
                  key={cls.name}
                  className={`list-item ${selectedClass?.name === cls.name ? "active" : ""}`}
                  style={{ cursor: "pointer" }}
                  onClick={() => setSelectedClass(cls)}
                >
                  <span>{cls.name}</span>
                </li>
              ))}
            </ul>
          )}

          {selectedClass && (
            <button
              className="danger"
              onDoubleClick={() => handleDelete(selectedClass.name)}
              title="Double-click to delete this class"
            >
              Delete (double-click)
            </button>
          )}
        </div>
      }
      right={
        <>
          <h3 className="panel-header">Class Graph</h3>

          {savedClassTimeseriesData.length > 0 ? (
            <>
              <GraphBox height="var(--graph-h)" title={`Class name: ${selectedClass?.name}`}>
                <RealtimeGraph
                  topics={selectedClass?.topics || []}
                  initialData={savedClassTimeseriesData}
                />
              </GraphBox>

              {/* Individual topic graphs */}
              {savedClassTimeseriesData.length > 1 && (
                <GraphGrid>
                  {savedClassTimeseriesData.map((ts) => (
                    <GraphBox key={ts.measurement} title={ts.measurement}>
                      <RealtimeGraph topics={[ts.measurement]} initialData={[ts]} />
                    </GraphBox>
                  ))}
                </GraphGrid>
              )}
            </>
          ) : (
            <p className="empty-note">Select a class to preview its graph.</p>
          )}
        </>
      }
    />
  );
}
