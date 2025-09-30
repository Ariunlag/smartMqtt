import { useInfluxStore } from "../../store/useInfluxStore";

export default function ClassNameInput() {
  const name = useInfluxStore((s) => s.classNameInput);
  const setName = useInfluxStore((s) => s.setClassNameInput);
  const save = useInfluxStore((s) => s.saveClass);

  return (
    <div>
      <h4>Save as Class</h4>
      <input
        className="panel-input"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Enter class name"
      />
      <button onClick={save}>Save</button>
    </div>
  );
}
