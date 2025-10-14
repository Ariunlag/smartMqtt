import { useState } from "react";
import { useGroupStore } from "../../store/useGroupStore";
import { useInfluxStore } from "../../store/useInfluxStore";

export default function SaveAsClass() {
  const [name, setName] = useState("");
  const topics = useGroupStore((s) => s.selectedTopics);

  // Influx store actions
  const setClassNameInput = useInfluxStore((s) => s.setClassNameInput);
  const setSelectedMeasurements = useInfluxStore((s) => s.setSelectedMeasurements);
  const saveClass = useInfluxStore((s) => s.saveClass);

  const handleSave = async () => {
    if (!name || topics.length === 0) {
      alert("Class name and topics are required");
      return;
    }

    // Sync class name + topics into Influx store
    setClassNameInput(name);
    await setSelectedMeasurements(topics);

    // Save the class
    await saveClass();
    setName("");
  };

  return (
    <div>
      <h3 className="panel-header">Save as Class</h3>
      <input
        className="panel-input"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Enter class name"
      />
      <button onClick={handleSave}>Save</button>
    </div>
  );
}
