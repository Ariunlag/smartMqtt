import { useInfluxStore } from "../../store/useInfluxStore";

export default function SelectedMeasurements() {
  const selected = useInfluxStore((s) => s.selectedMeasurements);
  const remove = useInfluxStore((s) => s.removeMeasurement);

  return (
    <div>
      <h4>Selected Measurements</h4>
      <ul className="panel-list">
        {selected.length === 0 ? (
          <li className="empty-note">None selected</li>
        ) : (
          selected.map((m) => (
            <li key={m} className="list-item">
              <span title={m}>{m}</span>
              <button onClick={() => remove(m)} title="Remove measurement">
                ×
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
