import { AlertTriangle, CheckCircle2, Loader2, MousePointerClick, Pause, Play, Square, WifiOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fmtTime, leaves, useP } from "../lib";
import { Button, cn } from "../ui";

const clock = (s: number) => {
  const v = Math.max(0, Math.round(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
};

/** One place that answers: "is the tool working right now, and on what?" */
export function useWork() {
  const P = useP();
  const v = P.view;
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  if (!v) return null;
  const p = v.project;
  const acts = v.engine.activity || [];
  const clipActs = acts.filter((a) => a.node !== "final");
  const finalAct = acts.find((a) => a.node === "final");
  const runStatus = p.run.status;
  const running = runStatus === "running" || v.engine.active || acts.length > 0;
  const paused = runStatus === "paused";
  const aiJobs = P.busy.filter((b) => b);
  const targets = p.run.targets.length ? p.run.targets : leaves(p).map((l) => l.id);
  const all = leaves(p).filter((l) => targets.includes(l.id));
  const done = all.filter((l) => l.status === "done").length;
  // seconds since the step began = what the server said at the last update + time passed since then
  const sinceUpdate = (Date.now() - P.fetchedAt) / 1000;
  const elapsedOf = (a: { started: number; now: number }) => Math.max(0, a.now - a.started + sinceUpdate);
  const partial = clipActs.reduce((sum, a) => sum + (a.expected_s > 0 ? Math.min(0.9, elapsedOf(a) / a.expected_s) : 0.3), 0);
  const pct = all.length ? Math.min(99, Math.round(((done + Math.min(partial, all.length - done)) / all.length) * 100)) : 0;
  const waitingPicks = v.summary.waiting_picks;
  return { v, p, acts, clipActs, finalAct, running, paused, aiJobs, done, total: all.length, pct, elapsedOf, waitingPicks };
}

export default function ActivityBar() {
  const P = useP();
  const w = useWork();
  if (!w) return null;
  const { p, v, clipActs, finalAct, running, paused, aiJobs, done, total, pct, elapsedOf } = w;
  const nothing = !running && !paused && aiJobs.length === 0 && !finalAct;
  if (nothing && P.online) return null;

  const first = clipActs[0];
  const num = (id: string) => P.numbers[id] || "";
  const slow = (a: typeof first) => a && a.expected_s > 0 && a.step_elapsed_s > Math.max(90, a.expected_s * 2);

  let title = "Working…";
  let detail = "";
  if (first) {
    title = clipActs.length > 1 ? `Making ${clipActs.length} clips at the same time` : `Making clip ${num(first.node)}`;
    detail = clipActs.length > 1 ? clipActs.map((a) => `${num(a.node)}: ${a.step}`).join("  ·  ") : first.step;
  } else if (finalAct) {
    title = "Making the final video";
    detail = finalAct.step;
  } else if (aiJobs.length) {
    title = `AI is working: ${aiJobs[aiJobs.length - 1]}`;
    detail = "Planning and writing take a few seconds.";
  } else if (running) {
    title = "Working…";
    detail = p.run.message || "";
  } else if (paused) {
    title = "Paused";
    detail = p.run.message || "";
  } else if (!P.online) {
    title = "Reconnecting to the app…";
    detail = "Your work is saved. The page updates again once the connection is back.";
  }
  const indeterminate = !first && !finalAct;
  const isSlow = slow(first);

  return (
    <div role="status" aria-live="polite" className={cn("border-b border-line px-4 py-2", paused ? "bg-warn/10" : isSlow ? "bg-warn/10" : "bg-brand/5")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {paused ? <Pause className="h-4 w-4 text-warn" /> : !P.online && !running ? <WifiOff className="h-4 w-4 text-warn" /> : <Loader2 className="h-4 w-4 animate-spin text-brand" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-[13px] font-semibold">{title}</span>
            {first && <span className="text-xs tabular-nums text-muted">{clock(elapsedOf(first))}{first.expected_s > 0 && ` of about ${clock(first.expected_s)}`}</span>}
            {total > 0 && (running || paused) && <span className="text-xs text-muted">· {done} of {total} clips done</span>}
            {running && v.summary.time_s > 0 && <span className="text-xs text-muted">· about {fmtTime(v.summary.time_s)} left</span>}
          </div>
          {detail && <div className="truncate text-xs text-muted" title={detail}>{detail}</div>}
          {isSlow && (
            <div className="mt-0.5 flex items-center gap-1 text-xs text-warn">
              <AlertTriangle className="h-3 w-3" />Taking longer than usual (expected about {clock(first.expected_s)}). Video services can be slow. It is still working.
            </div>
          )}
        </div>
        {!P.online && running && <span className="inline-flex items-center gap-1 rounded-md bg-warn/15 px-2 py-0.5 text-[11px] text-warn"><WifiOff className="h-3 w-3" />Reconnecting…</span>}
        {w.waitingPicks > 0 && (
          <span className="inline-flex items-center gap-1 rounded-md bg-warn/15 px-2 py-0.5 text-[11px] font-medium text-warn"><MousePointerClick className="h-3 w-3" />{w.waitingPicks} waiting for your pick</span>
        )}
        {(running || paused) && (
          <div className="flex gap-1.5">
            {running && !paused && <Button size="sm" variant="outline" onClick={() => P.act("Pause", () => api.pause(P.pid))}><Pause className="h-3.5 w-3.5" />Pause</Button>}
            {paused && <Button size="sm" variant="primary" onClick={() => P.act("Resume", () => api.resume(P.pid))}><Play className="h-3.5 w-3.5" />Resume</Button>}
            <Button size="sm" variant="ghost" onClick={() => P.act("Stop", () => api.stop(P.pid))}><Square className="h-3.5 w-3.5" />Stop</Button>
          </div>
        )}
      </div>
      <div className={cn("mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-sunken", indeterminate && !paused && "indeterminate")} aria-hidden>
        {!indeterminate && <div className="h-full rounded-full bg-brand transition-all duration-700" style={{ width: `${pct}%` }} />}
      </div>
    </div>
  );
}

/** Thin moving line at the very top of the window while anything is busy. */
export function TopLine() {
  const P = useP();
  const active = P.busy.length > 0 || P.view?.engine.active || (P.view?.engine.activity.length || 0) > 0;
  if (!active) return <div className="h-0.5 shrink-0" />;
  return <div className="indeterminate h-0.5 shrink-0 bg-brand/15" aria-hidden />;
}

/** Browser tab title + notifications, so you can leave the tab and still know what is going on. */
export function useTabStatus() {
  const P = useP();
  const w = useWork();
  const prev = useRef<{ running: boolean; picks: number; failed: number; final: boolean } | null>(null);
  const name = w?.p.name || "video-generator";
  useEffect(() => {
    if (!w) return;
    let title = name;
    if (w.running || w.aiJobs.length) title = `⏳ ${w.total ? `${w.done}/${w.total} · ` : ""}${name}`;
    else if (w.waitingPicks > 0) title = `👆 Pick a take · ${name}`;
    else if (w.v.summary.final_ready && !w.v.summary.final_stale) title = `✅ ${name}`;
    document.title = title;
    return () => { document.title = "video-generator"; };
  });
  useEffect(() => {
    if (!w) return;
    const failed = leaves(w.p).filter((l) => l.status === "failed").length;
    const cur = { running: w.running, picks: w.waitingPicks, failed, final: w.v.summary.final_ready && !w.v.summary.final_stale };
    const before = prev.current;
    prev.current = cur;
    if (!before || typeof Notification === "undefined" || Notification.permission !== "granted" || !document.hidden) return;
    const notify = (text: string) => { try { new Notification(name, { body: text }); } catch { /* ignore */ } };
    if (cur.picks > before.picks) notify(`${cur.picks} take(s) are waiting for your pick.`);
    else if (cur.failed > before.failed) notify("A clip failed. Open the app to see why.");
    else if (cur.final && !before.final) notify("Your final video is ready.");
  });
  return P;
}

export function askNotificationPermission() {
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission();
  } catch { /* ignore */ }
}

export const DoneIcon = CheckCircle2;
