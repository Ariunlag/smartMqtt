import SplitLayout from "../layout/SplitLayout";
import MeasurementsList from "./MeasurementsList";
import SelectedMeasurements from "./SelectedMeasurements";
import ClassNameInput from "./ClassNameInput";
import GraphBox from "../graphs/GraphBox";
import GraphGrid from "../graphs/GraphGrid";
import RealtimeGraph from "../graphs/RealtimeGraph";
import { useInfluxStore } from "../../store/useInfluxStore";

export default function ClassBuilder() {
  const selected = useInfluxStore((s) => s.selectedMeasurements);
  const builderTimeseriesData = useInfluxStore((s) => s.builderTimeseriesData);

  return (
    <SplitLayout
      left={
        <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <h2 className="panel-header">Class Builder</h2>
          <div style={{ maxHeight: "240px", overflowY: "auto" }}>
            <MeasurementsList />
          </div>
          <hr />
          <SelectedMeasurements />
          <ClassNameInput />
        </div>
      }
      right={
        <>
          <h3 className="panel-header">Builder Graph</h3>

          {selected.length > 0 ? (
            <>
              {/* Combined graph */}
              <GraphBox height="var(--graph-h)" title="Combined Graph">
                <RealtimeGraph topics={selected} initialData={builderTimeseriesData} />
              </GraphBox>

              {/* Individual graphs */}
              {builderTimeseriesData.length > 1 && (
                <GraphGrid>
                  {builderTimeseriesData.map((ts) => (
                    <GraphBox key={ts.measurement} title={ts.measurement}>
                      <RealtimeGraph topics={[ts.measurement]} initialData={[ts]} />
                    </GraphBox>
                  ))}
                </GraphGrid>
              )}
            </>
          ) : (
            <p className="empty-note">Select measurements to preview graph</p>
          )}
        </>
      }
    />
  );
}
