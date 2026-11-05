import { Clapperboard, Download, FastForward, Link2, Loader2, MousePointerClick, Pause, Play, SkipForward, Square } from "lucide-react";
import { api } from "../api";
import { finalPlayer, fmtSec, fmtTime, fmtUsd, leaves, STATUS, useP } from "../lib";
import { Badge, Button, cn, Tip } from "../ui";
import { useRun } from "./ConfirmRun";
import { fileUrl } from "../api";

export default function Timeline() {
  const P = useP();
  const run = useRun();
  const p = P.view!.project;
  const s = P.view!.summary;
  const clips = leaves(p);
  const total = Math.max(clips.reduce((a, c) => a + c.duration.likely_s, 0), 1);
  const running = p.run.status === "running" || P.view!.engine.active;
  const paused = p.run.status === "paused";
  const remaining = clips.filter((c) => c.status !== "done").length;
  const doneSome = clips.some((c) => c.status === "done");
  const allDone = clips.length > 0 && remaining === 0;
  const continues = new Set(p.dependencies.filter((d) => d.type === "continues_from").map((d) => d.to_id));
  const over = s.target_seconds ? (s.seconds - s.target_seconds) / s.target_seconds : 0;
  const working = new Set((P.view!.engine.activity || []).map((a) => a.node));
  const finalReady = s.final_ready && !s.final_stale;
  const joining = working.has("final");

  return (
    <footer className="shrink-0 border-t border-line bg-panel">
      {/* timeline */}
      <div className="flex h-12 items-stretch gap-0.5 overflow-x-auto scroll-thin px-3 pt-2" aria-label="Timeline">
        {clips.map((c) => {
          const st = STATUS[c.status];
          return (
            <Tip key={c.id} content={<span>{P.numbers[c.id]} {c.title}<br />~{fmtSec(c.duration.likely_s)} · {fmtUsd(c.cost.likely_usd)} · {st.label}</span>}>
              <button onClick={() => P.select(c.id)} style={{ flexGrow: c.duration.likely_s, minWidth: 34 }}
                className={cn("relative flex items-center gap-1 overflow-hidden rounded-md border px-1.5 text-[10px] font-medium transition-colors",
                  P.selected === c.id ? "border-brand bg-brand/10" : "border-line bg-sunken hover:border-brand/40",
                  c.status === "done" && "bg-ok/10", c.status === "needs_pick" && "bg-warn/15", c.status === "failed" && "bg-bad/10",
                  (working.has(c.id) || c.status === "generating") && "working")}>
                <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", st.dot)} />
                {continues.has(c.id) && <Link2 className="h-2.5 w-2.5 shrink-0 text-info" aria-label="continues from the previous clip" />}
                <span className="truncate">{P.numbers[c.id]} {c.title}</span>
              </button>
            </Tip>
          );
        })}
        {clips.length === 0 && <div className="flex items-center text-xs text-muted">No clips yet.</div>}
      </div>

      {/* run bar */}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        {!running && !paused && !joining && (
          <>
            {finalReady ? (
              <>
                <Button variant="primary" onClick={() => finalPlayer.open()}><Play className="h-3.5 w-3.5" />Play final video</Button>
                <a href={fileUrl(P.pid, p.final_output)} download><Button><Download className="h-3.5 w-3.5" />Download</Button></a>
              </>
            ) : allDone ? (
              <Tip content={s.final_stale ? "Something changed since your final video was made. This makes a new one from the current clips." : "All clips are made. This joins them into ONE video: same size and speed, transitions, music and subtitles."}>
                <Button variant="primary" onClick={() => P.act("Joining", () => api.assemble(P.pid))}>
                  <Clapperboard className="h-3.5 w-3.5" />{s.final_stale ? "Update final video" : "Join clips into final video"}
                </Button>
              </Tip>
            ) : (
              <>
                <Button variant="primary" disabled={!clips.length} onClick={() => run({ mode: "all", title: "Generate the entire video" })}>
                  <Clapperboard className="h-3.5 w-3.5" />{doneSome ? "Generate the rest" : "Generate entire video"}
                </Button>
                <Button onClick={() => run({ mode: "next", title: "Generate the next clip" })}><SkipForward className="h-3.5 w-3.5" />Generate next</Button>
                {doneSome && <Button onClick={() => run({ mode: "continue", title: "Continue to the end" })}><FastForward className="h-3.5 w-3.5" />Continue to end</Button>}
              </>
            )}
          </>
        )}
        {running && <Button onClick={() => P.act("Pause", () => api.pause(P.pid))}><Pause className="h-3.5 w-3.5" />Pause</Button>}
        {paused && <Button variant="primary" onClick={() => P.act("Resume", () => api.resume(P.pid))}><Play className="h-3.5 w-3.5" />Resume</Button>}
        {(running || paused) && <Button variant="ghost" onClick={() => P.act("Stop", () => api.stop(P.pid))}><Square className="h-3.5 w-3.5" />Stop</Button>}
        <div className="min-w-0 flex-1 truncate text-xs text-muted">
          {running && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin text-brand" />}
          {p.run.message && p.run.status !== "idle" ? p.run.message : ""}
        </div>
        {s.waiting_picks > 0 && (
          <Badge tone="warn"><MousePointerClick className="h-3 w-3" />{s.waiting_picks} take{s.waiting_picks > 1 ? "s" : ""} waiting for your pick</Badge>
        )}
        <Tip content={`Estimated ${fmtSec(s.seconds_min)}–${fmtSec(s.seconds_max)}`}>
          <span className={cn("text-xs tabular-nums", Math.abs(over) > 0.1 ? "text-warn" : "text-muted")}>
            <span className="font-medium text-ink">{fmtSec(s.seconds)}</span> / {fmtSec(s.target_seconds)}</span>
        </Tip>
        <Tip content={`Range ${fmtUsd(s.cost_min)}–${fmtUsd(s.cost_max)}; spent so far ${fmtUsd(s.spent)}`}>
          <span className="text-xs tabular-nums"><span className="font-medium">{fmtUsd(s.cost)}</span><span className="text-muted"> to make</span></span>
        </Tip>
        <span className="text-xs tabular-nums text-muted">~{fmtTime(s.time_s)}</span>
      </div>
      {s.warnings.length > 0 && (
        <div className="border-t border-line bg-warn/5 px-3 py-1.5 text-[11px] text-warn">{s.warnings.join(" · ")}</div>
      )}
    </footer>
  );
}
