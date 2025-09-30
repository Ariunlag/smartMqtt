import { useInfluxStore } from "../../store/useInfluxStore";

export default function SelectedMeasurements() {
  const selected = useInfluxStore((s) => s.selectedMeasurements);
  const remove = useInfluxStore((s) => s.removeMeasurement);

  return (
    <div>
      <ul className="panel-list">
        {selected.length === 0 ? (
          <li style={{ color: "#aaa" }}>None selected</li>
        ) : (
          selected.map((m) => (
            <li key={m} className="list-item">
              {m}
              <button onClick={() => remove(m)}>x</button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
