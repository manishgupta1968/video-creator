import { AlertTriangle, ArrowRight, Check, ChevronDown, ChevronUp, Compass, Eye, X } from "lucide-react";
import { useState } from "react";
import { api, Guide, GuideAction } from "../api";
import { finalPlayer, useP } from "../lib";
import { Button, cn } from "../ui";
import { spotlight } from "../ui/help";
import { useRun } from "./ConfirmRun";
import { useJoin } from "./JoinDialog";

/** "Your next step": reads the project as it is now (the plan is computed by the server, with no AI and no cost)
 *  and shows the one thing to do next, with a button that does it. It updates after every click. */
export default function NextStep() {
  const P = useP();
  const run = useRun();
  const join = useJoin();
  const g: Guide | undefined = P.view?.summary.guide;
  const key = `vg-guide-hidden-${P.pid}`;
  const [hidden, setHidden] = useState<boolean>(() => { try { return localStorage.getItem(key) === "1"; } catch { return false; } });
  const [open, setOpen] = useState(false);
  if (!g) return null;
  const root = P.view!.project.root.id;

  const setHide = (v: boolean) => { setHidden(v); try { localStorage.setItem(key, v ? "1" : "0"); } catch { /* private window: fine */ } };
  const later = (fn: () => void, ms = 250) => window.setTimeout(fn, ms);

  const doIt = (a: GuideAction | null) => {
    if (!a) return;
    switch (a.kind) {
      case "settings": P.openSettings("keys"); break;
      case "select": if (a.id) P.select(a.id); break;
      case "context": P.select(root); later(() => window.dispatchEvent(new CustomEvent("vg-open-context", { detail: a.id })), 200); break;
      case "budget": window.dispatchEvent(new Event("vg-open-budget")); break;
      case "run": run({ mode: a.mode || "next", targets: a.targets, title: a.title || a.label }); break;
      case "scripts": P.act("Writing scripts", () => api.writeScripts(P.pid), "Scripts written"); break;
      case "split": if (a.id) P.act("Splitting", () => api.splitClip(P.pid, a.id!), "Clip split into parts"); break;
      case "assemble": join(); break;
      case "unpin": P.act("Choosing the best model", () => api.unpin(P.pid, a.ids), "These clips use the best model again. Make the out-of-date ones again."); break;
      case "final": finalPlayer.open(); break;
      case "resume": P.act("Resume", () => api.resume(P.pid)); break;
      case "show": if (a.node) P.select(a.node); if (a.help) later(() => spotlight(a.help!)); break;
    }
  };
  const showMe = (a: GuideAction | null) => {
    if (!a?.help) return;
    const target = a.id || a.node;
    if (target && ["select", "show"].includes(a.kind)) P.select(target);
    later(() => spotlight(a.help!), target ? 300 : 0);
  };

  if (hidden) {
    return (
      <div className="flex justify-end border-b border-line bg-panel px-4 py-1">
        <button className="flex items-center gap-1 text-[11px] text-muted hover:text-ink" onClick={() => setHide(false)}>
          <Compass className="h-3 w-3" />Show next-step guide
        </button>
      </div>
    );
  }

  const cur = g.steps.find((s) => s.state === "current");
  const done = g.current === null;
  return (
    <section data-help="next-step" aria-label="Your next step" className="border-b border-line bg-brand/5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
        <div className="flex min-w-0 flex-1 items-start gap-2.5">
          <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand text-white"><Compass className="h-3.5 w-3.5" /></span>
          <div className="min-w-0">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted">Your next step · {g.progress.done} of {g.progress.total} done</div>
            <div className="text-sm font-semibold">{done ? "All done. Enjoy your video." : g.headline}</div>
            {g.why && <div className="max-w-3xl text-xs text-muted">{g.why}</div>}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {g.action && <Button variant="primary" size="sm" onClick={() => doIt(g.action)}>{g.action.label}<ArrowRight className="h-3.5 w-3.5" /></Button>}
          {g.action?.help && <Button variant="ghost" size="sm" onClick={() => showMe(g.action)}><Eye className="h-3.5 w-3.5" />Show me where</Button>}
          <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
            All steps{open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </Button>
          <button aria-label="Hide the next-step guide" title="Hide the guide" className="rounded-md p-1 text-muted hover:bg-sunken" onClick={() => setHide(true)}><X className="h-4 w-4" /></button>
        </div>
      </div>
      {open && (
        <div className="grid gap-x-6 gap-y-1 border-t border-line px-4 py-3 text-xs md:grid-cols-2">
          {g.steps.map((s, i) => (
            <div key={s.id} className={cn("flex gap-2 rounded-lg px-2 py-1.5", s.state === "current" && "bg-brand/10")}>
              <span className={cn("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold",
                s.state === "done" ? "bg-ok text-white" : s.state === "current" ? "bg-brand text-white" : s.state === "attention" ? "bg-warn text-white" : "border border-line text-muted")}>
                {s.state === "done" ? <Check className="h-3 w-3" /> : s.state === "attention" ? <AlertTriangle className="h-3 w-3" /> : i + 1}
              </span>
              <div className="min-w-0">
                <div className={cn("font-medium", s.state === "todo" && "text-muted")}>{s.title}</div>
                <div className="text-muted">{s.detail}</div>
                {s.state === "current" && s.also.length > 0 && (
                  <ul className="mt-1 space-y-0.5">
                    {s.also.map((x, k) => (
                      <li key={k} className="flex items-start gap-1">
                        <span className="text-muted">Then:</span><span>{x.text}</span>
                        <button className="ml-1 shrink-0 text-brand hover:underline" onClick={() => doIt(x.action)}>{x.action.label}</button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ))}
          {g.issues.length > 0 && (
            <div className="md:col-span-2">
              <div className="mt-1 font-semibold">Also worth a look (these do not stop you)</div>
              <ul className="mt-1 space-y-1">
                {g.issues.map((x, k) => (
                  <li key={k} className="flex items-start gap-1.5"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-warn" /><span>{x.text}</span>
                    <button className="ml-1 shrink-0 text-brand hover:underline" onClick={() => doIt(x.action)}>{x.action.label}</button></li>
                ))}
              </ul>
            </div>
          )}
          {cur === undefined && !done && null}
        </div>
      )}
    </section>
  );
}
