import { useInfluxStore } from "../../store/useInfluxStore";

export default function MeasurementsList() {
  const measurements = useInfluxStore((s) => s.measurements);
  const selected = useInfluxStore((s) => s.selectedMeasurements);
  const addMeasurement = useInfluxStore((s) => s.addMeasurement);

  if (!measurements) return <p>Loading measurements...</p>;

  const available = measurements.filter((m) => !selected.includes(m));

  return (
    <div>
      <h4>Available Measurements</h4>
      {available.length === 0 ? (
        <p style={{ color: "#aaa" }}>No more measurements</p>
      ) : (
        <ul className="panel-list">
          {available.map((m) => (
            <li key={m} className="narrow-list-item" onClick={() => addMeasurement(m)}>
              {m}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
