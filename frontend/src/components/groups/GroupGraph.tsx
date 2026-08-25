import { useEffect, useState } from "react";
import GraphBox from "../graphs/GraphBox";
import GraphGrid from "../graphs/GraphGrid";
import RealtimeGraph from "../graphs/RealtimeGraph";
import { useGroupStore } from "../../store/useGroupStore";
import * as dataApi from "../../services/dataApi"; // 
import type { TimeseriesData } from "../../services/lineChartService";

export default function GroupGraph() {
  const topics = useGroupStore((s) => s.selectedTopics);
  const [series, setSeries] = useState<TimeseriesData[]>([]);

  // Fetch history when topics change
  useEffect(() => {
    const fetchData = async () => {
      if (topics.length === 0) {
        setSeries([]);
        return;
      }

      try {
        const res = await dataApi.getTimeseries(topics);
        const formatted: TimeseriesData[] = res.map((m) => ({
          measurement: m.measurement,
          points: m.points.map((p) => ({
            timestamp: p.timestamp,
            value: p.value,
          })),
        }));
        setSeries(formatted);
      } catch (err) {
        console.error("[GroupGraph] Failed to fetch timeseries:", err);
        setSeries([]);
      }
    };

    fetchData();
  }, [topics]);

  if (topics.length === 0) {
    return <p className="empty-note">Select a tag set to view topics</p>;
  }

  return (
    <>
      <h3 className="panel-header">Tag Set Graph</h3>

      {/* Big combined graph */}
      <GraphBox height="var(--graph-h)" title="Combined Graph">
        <RealtimeGraph topics={topics} initialData={series} />
      </GraphBox>

      {/* Individual graphs */}
      {topics.length > 1 && (
        <GraphGrid>
          {series.map((ts) => (
            <GraphBox key={ts.measurement} title={ts.measurement}>
              <RealtimeGraph topics={[ts.measurement]} initialData={[ts]} />
            </GraphBox>
          ))}
        </GraphGrid>
      )}
    </>
  );
}
