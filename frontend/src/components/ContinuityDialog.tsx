import { AlertTriangle, Info, Link2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, FixAction, Finding } from "../api";
import { useP } from "../lib";
import { Badge, Button, Dialog } from "../ui";
import { useRun } from "./ConfirmRun";

/** A slim line under the numbers strip: "Continuity: 3 things to check". Click it to read each one and fix it with one click where the fix is mechanical.
 *  The checks are plain rules (no AI, no cost) and run on every change. */
export default function ContinuityBar() {
  const P = useP();
  const [open, setOpen] = useState(false);
  const list = P.view?.summary.continuity || [];
  useEffect(() => {
    const h = () => setOpen(true);
    window.addEventListener("vg-open-continuity", h);
    return () => window.removeEventListener("vg-open-continuity", h);
  }, []);
  if (!list.length) return null;
  const problems = list.filter((f) => f.severity === "problem").length;
  return (
    <>
      <button data-help="continuity-bar" type="button" onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 border-b border-line bg-panel px-4 py-1.5 text-left text-xs hover:bg-sunken">
        {problems ? <AlertTriangle className="h-3.5 w-3.5 text-bad" /> : <Info className="h-3.5 w-3.5 text-info" />}
        <span className="font-medium">Continuity</span>
        <span className="text-muted">{problems ? `${problems} problem${problems > 1 ? "s" : ""}` : ""}{problems && list.length > problems ? " and " : ""}{list.length > problems ? `${list.length - problems} thing${list.length - problems > 1 ? "s" : ""} to look at` : ""} so the clips feel like one video.</span>
        <span className="ml-auto text-brand">Read and fix</span>
      </button>
      <ContinuityDialog open={open} onOpenChange={setOpen} list={list} />
    </>
  );
}

function ContinuityDialog({ open, onOpenChange, list }: { open: boolean; onOpenChange: (o: boolean) => void; list: Finding[] }) {
  const P = useP();
  const run = useRun();
  const [busy, setBusy] = useState("");
  const apply = async (f: Finding, fx: FixAction) => {
    const key = f.code + f.node + fx.action;
    if (fx.action === "remake" && fx.node) { onOpenChange(false); run({ mode: "clip", targets: [fx.node], title: `Make clip ${P.numbers[fx.node]} again` }); return; }
    if (fx.action === "open_actor" && fx.id) { onOpenChange(false); P.select(P.view!.project.root.id); window.setTimeout(() => window.dispatchEvent(new CustomEvent("vg-open-context", { detail: fx.id })), 200); return; }
    setBusy(key);
    await P.act("Fix", () => api.fixContinuity(P.pid, { action: fx.action, node: fx.node, join: fx.join }), "Fixed. Ctrl+Z undoes it.");
    setBusy("");
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide title="Continuity: do the clips fit together?"
      description="Plain rules, no AI, no cost. A problem would show in the video; a note is worth a look. Each fix changes the plan only; nothing is spent."
      footer={<Button variant="ghost" onClick={() => onOpenChange(false)}>Close</Button>}>
      <div className="space-y-2">
        {list.length === 0 && <div className="text-sm text-muted">Everything fits together.</div>}
        {list.map((f, i) => (
          <div key={i} className="rounded-xl border border-line p-3 text-sm">
            <div className="mb-1 flex items-center gap-2">
              <Badge tone={f.severity === "problem" ? "bad" : "info"}>{f.severity === "problem" ? "Problem" : "Note"}</Badge>
              {f.number && <button className="text-xs text-brand hover:underline" onClick={() => { P.select(f.node); onOpenChange(false); }}><Link2 className="mr-1 inline h-3 w-3" />Clip {f.number}</button>}
            </div>
            <div>{f.text}</div>
            {f.fixes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {f.fixes.map((fx, j) => <Button key={j} size="sm" variant={j === 0 ? "outline" : "ghost"} loading={busy === f.code + f.node + fx.action} onClick={() => apply(f, fx)}>{fx.label}</Button>)}
              </div>
            )}
          </div>
        ))}
      </div>
    </Dialog>
  );
}
