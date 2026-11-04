import { useEffect, useState } from "react";
import { Button } from "../ui";

const STEPS = [
  { title: "Your story", text: "On the left is your video as a tree of parts and clips. Click any one to edit it. Drag to reorder. Use ••• to break a part down with AI." },
  { title: "Edit in place", text: "In the middle, click any text to change it — it saves by itself. Or type in “Ask AI” to change it in plain words." },
  { title: "Context", text: "On the right, add photos, voices, logos and notes — shared by all clips, or just for one. Each length, cost and time updates live." },
  { title: "Make it", text: "At the bottom: Generate next, Continue to end, or Generate entire video. You always see the cost first, and you pick the best take." },
];

export default function Tour() {
  const [i, setI] = useState<number | null>(null);
  useEffect(() => { try { if (!localStorage.getItem("vg-tour")) setI(0); } catch { /* ignore */ } }, []);
  if (i === null) return null;
  const done = () => { try { localStorage.setItem("vg-tour", "1"); } catch { /* ignore */ } setI(null); };
  const s = STEPS[i];
  return (
    <div className="fixed bottom-28 left-1/2 z-[150] w-[min(420px,calc(100vw-32px))] -translate-x-1/2 rounded-2xl border border-brand/30 bg-panel p-4 shadow-pop" role="dialog" aria-label="Quick tour">
      <div className="text-[11px] text-brand">Quick tour · {i + 1} of {STEPS.length}</div>
      <div className="mt-1 font-semibold">{s.title}</div>
      <p className="mt-1 text-xs text-muted">{s.text}</p>
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={done}>Skip</Button>
        <Button size="sm" variant="primary" onClick={() => (i + 1 < STEPS.length ? setI(i + 1) : done())}>{i + 1 < STEPS.length ? "Next" : "Start"}</Button>
      </div>
    </div>
  );
}
