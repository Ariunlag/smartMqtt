import SplitLayout from "../layout/SplitLayout";
import MeasurementsList from "./MeasurementsList";
import SelectedMeasurements from "./SelectedMeasurements";
import ClassNameInput from "./ClassNameInput";
import GraphBox from "../graphs/GraphBox";
import GraphGrid from "../graphs/GraphGrid";   // ✅ import this
import RealtimeGraph from "../graphs/RealtimeGraph";
import { useInfluxStore } from "../../store/useInfluxStore";

export default function ClassBuilder() {
  const selected = useInfluxStore((s) => s.selectedMeasurements);
  const builderTimeseriesData = useInfluxStore((s) => s.builderTimeseriesData);

  return (
    <SplitLayout
      left={
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "1rem",
            height: "100%",
            overflow: "hidden",
          }}
        >
          <h4>Available Measurements</h4>
          <div style={{ flex: 1, overflowY: "auto" }}>
            <MeasurementsList />
          </div>
          <h4>Selected</h4>
          <div style={{ flex: 1, overflowY: "auto" }}>
            <SelectedMeasurements />
          </div>
          <ClassNameInput />
        </div>
      }
      right={
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <h3 className="panel-header">Builder Graph</h3>

          {selected.length > 0 ? (
            <>
              {/* Combined graph */}
              <GraphBox height="260px" title="Combined Graph">
                <RealtimeGraph topics={selected} />
              </GraphBox>

              {/* Individual graphs */}
              {builderTimeseriesData.length > 1 && (
                <GraphGrid rowHeight={220}>
                  {builderTimeseriesData.map((ts) => (
                    <GraphBox key={ts.measurement} title={ts.measurement}>
                      <RealtimeGraph topics={[ts.measurement]} />
                    </GraphBox>
                  ))}
                </GraphGrid>
              )}
            </>
          ) : (
            <p style={{ color: "#aaa" }}>Select measurements to preview graph</p>
          )}
        </div>
      }
    />
  );
}
