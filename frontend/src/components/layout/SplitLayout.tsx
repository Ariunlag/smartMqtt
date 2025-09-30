import "./SplitLayout.css";

export default function SplitLayout({ left, right }: { left: React.ReactNode, right: React.ReactNode }) {
  return (
    <div className="split-layout">
      <div className="left">{left}</div>
      <div className="right">{right}</div>
    </div>
  );
}