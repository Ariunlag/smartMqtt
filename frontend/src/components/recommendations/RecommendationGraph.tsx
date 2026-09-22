import { useEffect, useState } from "react";

import GraphBox from "../graphs/GraphBox";
import GraphGrid from "../graphs/GraphGrid";
import RealtimeGraph from "../graphs/RealtimeGraph";
import * as dataApi from "../../services/dataApi";
import type { TimeseriesData } from "../../services/lineChartService";

export default function RecommendationGraph({ topics }: { topics: string[] }) {
  const [series, setSeries] = useState<TimeseriesData[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      if (topics.length === 0) {
        setSeries([]);
        setError(null);
        return;
      }

      try {
        const response = await dataApi.getTimeseries(topics);
        if (!cancelled) {
          setSeries(
            response.map((measurement) => ({
              measurement: measurement.measurement,
              points: measurement.points.map((point) => ({
                timestamp: point.timestamp,
                value: point.value,
              })),
            })),
          );
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setSeries([]);
          setError("Time-series data is not available for this selection yet.");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [topics]);

  if (topics.length === 0) {
    return <p className="empty-note">Add at least one topic to preview the graph.</p>;
  }

  return (
    <section aria-label="Recommendation graph">
      <GraphBox height="260px" title="Selected topics">
        <RealtimeGraph topics={topics} initialData={series} />
      </GraphBox>

      {error && <p className="empty-note">{error}</p>}

      {topics.length > 1 && series.length > 1 && (
        <GraphGrid rowHeight={220}>
          {series.map((item) => (
            <GraphBox key={item.measurement} title={item.measurement}>
              <RealtimeGraph topics={[item.measurement]} initialData={[item]} />
            </GraphBox>
          ))}
        </GraphGrid>
      )}
    </section>
  );
}
