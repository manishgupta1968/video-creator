import { AlertTriangle, ArrowRight, CheckCircle2, Gauge, Link2, Loader2, Lock, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Node, OptAi, OptEdit, OptLevel, OptProposal, OptRequest } from "../api";
import { findNode, fmtSec, fmtTime, fmtUsd, useP, walk } from "../lib";
import { Badge, Button, cn, Dialog, HelpTip } from "../ui";

const MADE = ["done", "needs_pick", "generating", "queued"];
const usd = (v: number) => `$${v.toFixed(2)}`;
const signed = (v: number, f: (x: number) => string) => (Math.abs(v) < 0.005 ? "no change" : `${v < 0 ? "−" : "+"}${f(Math.abs(v))}`);

/** The button that opens the Optimize dialog for a scope (the whole video, or one part). */
export function OptimizeButton({ scope, label, size = "md", variant = "outline" }: { scope?: string; label?: string; size?: "sm" | "md"; variant?: "outline" | "ghost" }) {
  return (
    <Button help="optimize-open" size={size} variant={variant} onClick={() => window.dispatchEvent(new CustomEvent("vg-open-optimize", { detail: scope || "" }))}>
      <Gauge className="h-3.5 w-3.5" />{label || "Optimize…"}
    </Button>
  );
}

/** Shorter and cheaper, in three steps: say the goal, read the proposal (before and after, the ladder, what you lose), then apply the changes you ticked.
 *  Nothing changes until Apply, and Apply is one change that one Undo takes back. */
export default function OptimizeHost() {
  const P = useP();
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState("");
  const [step, setStep] = useState<"goal" | "proposal">("goal");
  const [mode, setMode] = useState<"lowest" | "number">("lowest");
  const [useLength, setUseLength] = useState(true);
  const [useCost, setUseCost] = useState(false);
  const [lengthVal, setLengthVal] = useState("");
  const [costVal, setCostVal] = useState("");
  const [protect, setProtect] = useState<string[]>([]);
  const [prop, setProp] = useState<OptProposal | null>(null);
  const [ticked, setTicked] = useState<string[]>([]);
  const [aiEdits, setAiEdits] = useState<any[]>([]);
  const [aiInfo, setAiInfo] = useState<OptAi | null>(null);
  const [busy, setBusy] = useState<"" | "propose" | "recalc" | "ai" | "apply">("");
  const [error, setError] = useState("");
  const seq = useRef(0);

  const project = P.view?.project;
  const scopeId = scope || project?.root.id || "";
  const node: Node | undefined = project ? findNode(project, scopeId) : undefined;
  const isRoot = !!project && scopeId === project.root.id;
  const clips = useMemo(() => (node ? walk(node).filter((n) => n.kind === "clip") : []), [node]);
  const toMake = clips.filter((c) => c.status !== "done");

  useEffect(() => {
    const h = (e: Event) => {
      setScope((e as CustomEvent).detail || "");
      setStep("goal"); setProp(null); setTicked([]); setAiEdits([]); setAiInfo(null); setProtect([]); setError(""); setBusy("");
      setOpen(true);
    };
    window.addEventListener("vg-open-optimize", h);
    return () => window.removeEventListener("vg-open-optimize", h);
  }, []);

  const body = useCallback((extra: Partial<OptRequest> = {}): OptRequest => ({
    scope: scopeId, lowest: mode === "lowest",
    length: mode === "number" && useLength && lengthVal ? Number(lengthVal) : null,
    cost: mode === "number" && useCost && costVal ? Number(costVal) : null,
    protect, ai_edits: aiEdits, ...extra,
  }), [scopeId, mode, useLength, useCost, lengthVal, costVal, protect, aiEdits]);

  const run = async (kind: "propose" | "recalc", b: OptRequest) => {
    const mine = ++seq.current;
    setBusy(kind); setError("");
    try {
      const r = await api.optimizePropose(P.pid, b);
      if (mine !== seq.current) return;                      // a newer answer is on its way
      setProp(r);
      setTicked(r.edits.filter((e) => e.checked).map((e) => e.id));
      setStep("proposal");
    } catch (e: any) { if (mine === seq.current) setError(e.message || String(e)); }
    if (mine === seq.current) setBusy("");
  };
  const see = () => run("propose", body());
  const toggle = (id: string) => {
    const next = ticked.includes(id) ? ticked.filter((x) => x !== id) : [...ticked, id];
    setTicked(next);
    run("recalc", body({ ticked: next }));
  };
  const askAi = async () => {
    setBusy("ai"); setError("");
    try {
      const r = await api.optimizeAi(P.pid, body());
      setAiEdits(r.edits); setAiInfo(r);
      await run("propose", body({ ai_edits: r.edits }));
    } catch (e: any) { setError(e.message || String(e)); setBusy(""); }
  };
  const apply = async () => {
    setBusy("apply");
    const r = await P.act("Optimizing", () => api.optimizeApply(P.pid, body({ ticked })), "Optimized. Ctrl+Z undoes it all at once.");
    setBusy("");
    if (r) setOpen(false);
  };

  const goalOk = mode === "lowest" || (useLength && Number(lengthVal) > 0) || (useCost && Number(costVal) > 0);
  const title = isRoot ? "Optimize the whole video" : `Optimize part ${P.numbers[scopeId] || ""}`;
  const protectedNow = (c: Node) => c.locked || MADE.includes(c.status);

  const footer = (
    <>
      <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
      {step === "proposal" && <Button variant="outline" onClick={() => setStep("goal")}>Back</Button>}
      {step === "goal"
        ? <Button variant="primary" disabled={!goalOk || toMake.length === 0} loading={busy === "propose"} onClick={see}>See the proposal<ArrowRight className="h-3.5 w-3.5" /></Button>
        : <Button help="optimize-apply" variant="primary" disabled={ticked.length === 0 || busy === "recalc"} loading={busy === "apply"} onClick={apply}>
          Apply {ticked.length} change{ticked.length === 1 ? "" : "s"}</Button>}
    </>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen} wide="xl" title={title}
      description={step === "goal" ? "Say what you want. You see exactly what would change, and what you would lose, before anything is changed or spent." : "Read it, tick what you want, then apply. Nothing changes until you press Apply, and one Undo takes it all back."}
      footer={footer}>
      {error && <div className="mb-3 rounded-lg bg-bad/10 px-3 py-2 text-xs text-bad">{error}</div>}
      {step === "goal" ? (
        <GoalStep node={node} clips={clips} toMake={toMake.length} mode={mode} setMode={setMode} useLength={useLength} setUseLength={setUseLength} useCost={useCost} setUseCost={setUseCost}
          lengthVal={lengthVal} setLengthVal={setLengthVal} costVal={costVal} setCostVal={setCostVal} protect={protect} setProtect={setProtect} protectedNow={protectedNow} numbers={P.numbers} />
      ) : prop && (
        <ProposalStep prop={prop} ticked={ticked} toggle={toggle} busy={busy} askAi={askAi} aiInfo={aiInfo} />
      )}
    </Dialog>
  );
}

// ======================================================================= step 1: the goal
function GoalStep(p: {
  node?: Node; clips: Node[]; toMake: number; mode: "lowest" | "number"; setMode: (m: "lowest" | "number") => void; useLength: boolean; setUseLength: (v: boolean) => void;
  useCost: boolean; setUseCost: (v: boolean) => void; lengthVal: string; setLengthVal: (v: string) => void; costVal: string; setCostVal: (v: string) => void;
  protect: string[]; setProtect: (v: string[]) => void; protectedNow: (c: Node) => boolean; numbers: Record<string, string>;
}) {
  const now = p.node?.duration.likely_s || 0;
  const cost = p.clips.filter((c) => c.status !== "done").reduce((a, c) => a + c.cost.likely_usd, 0);
  const radio = "flex cursor-pointer items-start gap-2 rounded-xl border p-3 text-sm";
  return (
    <div className="space-y-4 text-sm">
      <div className="grid grid-cols-3 gap-2">
        <Box label="Length now" value={`~${fmtSec(now)}`} />
        <Box label="Still to spend" value={cost === 0 ? "Free" : usd(cost)} sub="clips not made yet" />
        <Box label="Clips" value={`${p.clips.length}`} sub={`${p.toMake} not made yet`} />
      </div>
      {p.toMake === 0 && <div className="rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn">Every clip here is already made, so there is nothing left to make shorter or cheaper.</div>}
      <HelpTip id="optimize-goal">
        <div className="space-y-2">
          <label className={cn(radio, p.mode === "lowest" ? "border-brand bg-brand/5" : "border-line")}>
            <input type="radio" name="optmode" checked={p.mode === "lowest"} onChange={() => p.setMode("lowest")} className="mt-1" />
            <span><b>As short and cheap as possible, without losing quality</b><br /><span className="text-xs text-muted">Only empty time is taken out of the clips. Every word and every action step stays. This is the safe choice.</span></span>
          </label>
          <label className={cn(radio, p.mode === "number" ? "border-brand bg-brand/5" : "border-line")}>
            <input type="radio" name="optmode" checked={p.mode === "number"} onChange={() => p.setMode("number")} className="mt-1" />
            <span className="flex-1"><b>Reach a number</b><br /><span className="text-xs text-muted">It tries the gentlest changes first and stops at the first step that gets you there.</span>
              {p.mode === "number" && (
                <span className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
                  <span className="inline-flex items-center gap-1.5"><input type="checkbox" checked={p.useLength} onChange={(e) => p.setUseLength(e.target.checked)} aria-label="Use a length goal" />
                    Length <input type="number" min={1} value={p.lengthVal} onChange={(e) => p.setLengthVal(e.target.value)} placeholder={String(Math.round(now))} aria-label="Length in seconds" className="h-7 w-20 rounded-md border border-line bg-panel px-2" /> seconds</span>
                  <span className="inline-flex items-center gap-1.5"><input type="checkbox" checked={p.useCost} onChange={(e) => p.setUseCost(e.target.checked)} aria-label="Use a cost goal" />
                    Still to spend at most $ <input type="number" min={0} step="0.5" value={p.costVal} onChange={(e) => p.setCostVal(e.target.value)} placeholder={cost.toFixed(2)} aria-label="Cost in dollars" className="h-7 w-24 rounded-md border border-line bg-panel px-2" /></span>
                </span>
              )}
            </span>
          </label>
        </div>
      </HelpTip>
      <details className="rounded-xl border border-line p-3 text-xs">
        <summary className="cursor-pointer font-medium">Protect clips ({p.clips.filter(p.protectedNow).length + p.protect.length} protected)</summary>
        <p className="mt-2 text-muted">Clips already made, clips marked <i>Keep as it is</i>, and lines marked <i>exact</i> are always protected. Tick any other clip you want left exactly as it is.</p>
        <div className="mt-2 grid gap-1 sm:grid-cols-2">
          {p.clips.map((c) => {
            const fixed = p.protectedNow(c);
            return (
              <label key={c.id} className={cn("flex items-center gap-2 rounded-md px-2 py-1", fixed && "opacity-70")}>
                <input type="checkbox" disabled={fixed} checked={fixed || p.protect.includes(c.id)} onChange={(e) => p.setProtect(e.target.checked ? [...p.protect, c.id] : p.protect.filter((x) => x !== c.id))} />
                <span className="w-8 tabular-nums text-muted">{p.numbers[c.id]}</span><span className="min-w-0 flex-1 truncate">{c.title || c.goal}</span>
                {fixed && <span className="inline-flex items-center gap-1 text-[10px] text-muted"><Lock className="h-3 w-3" />{c.locked ? "kept" : "made"}</span>}
              </label>
            );
          })}
        </div>
      </details>
    </div>
  );
}

function Box({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

// ======================================================================= step 2: the proposal
function ProposalStep({ prop, ticked, toggle, busy, askAi, aiInfo }: {
  prop: OptProposal; ticked: string[]; toggle: (id: string) => void; busy: string; askAi: () => void; aiInfo: OptAi | null;
}) {
  const b = prop.before, a = prop.after;
  const lowest = prop.goal.lowest;
  return (
    <div className="space-y-4 text-sm">
      {/* before and after */}
      <div className="relative grid grid-cols-3 gap-2">
        <Change label="Length" from={`~${fmtSec(b.seconds)}`} to={`~${fmtSec(a.seconds)}`} change={signed(prop.saves.seconds, (x) => fmtSec(x))} good={prop.saves.seconds < 0} />
        <Change label="Still to spend" from={fmtUsd(b.cost)} to={fmtUsd(a.cost)} change={signed(prop.saves.cost, usd)} good={prop.saves.cost < 0} />
        <Change label="Time to make" from={`~${fmtTime(b.time_s)}`} to={`~${fmtTime(a.time_s)}`} change={signed(prop.saves.time_s, (x) => fmtTime(x))} good={prop.saves.time_s < 0} />
        {busy === "recalc" && <div className="absolute inset-0 grid place-items-center rounded-xl bg-panel/70"><span className="inline-flex items-center gap-2 text-xs text-muted"><Loader2 className="h-4 w-4 animate-spin" />Working it out…</span></div>}
      </div>
      {/* goal status */}
      {lowest ? (
        <div className="flex items-start gap-2 rounded-lg bg-ok/10 px-3 py-2 text-xs"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" /><span>This is as low as it goes <b>without losing quality</b>: only empty time is taken out. Go further by choosing a number, or tick more changes below.</span></div>
      ) : prop.met ? (
        <div className="flex items-start gap-2 rounded-lg bg-ok/10 px-3 py-2 text-xs"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" /><span>Your goal is met{prop.stopped_at ? <> at <b>level {prop.stopped_at} · {prop.levels[prop.stopped_at - 1]?.name}</b>. The gentler levels were tried first; deeper ones are left unticked.</> : "."}</span></div>
      ) : (
        <div className="flex items-start gap-2 rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span><b>This goal cannot be met with what is ticked.</b> {prop.reason}</span></div>
      )}
      {prop.protected.count > 0 && <p className="text-[11px] text-muted">Left as they are (made, kept or protected): clips {prop.protected.numbers.join(", ")}. Lines marked <i>exact</i> are never changed.</p>}
      {/* the ladder */}
      <div className="space-y-2">
        {prop.levels.map((lv) => (
          <LevelCard key={lv.level} lv={lv} prop={prop} edits={prop.edits.filter((e) => e.level === lv.level)} ticked={ticked} toggle={toggle} askAi={askAi} asking={busy === "ai"} aiInfo={aiInfo} />
        ))}
      </div>
      {/* joins and continuity */}
      <div className="rounded-xl border border-line p-3 text-xs">
        <div className="flex items-center gap-2 font-medium"><Link2 className="h-3.5 w-3.5 text-brand" />
          {prop.joins.of === 0 ? "No continuing joins in this scope." : <>Joins kept: <span className={prop.joins.kept === prop.joins.of ? "text-ok" : "text-warn"}>{prop.joins.kept} of {prop.joins.of}</span></>}</div>
        {prop.joins.broken.map((t, i) => <div key={i} className="mt-1 text-warn">{t}</div>)}
        {prop.findings.length > 0 && <div className="mt-2 space-y-1">{prop.findings.map((f, i) => <div key={i} className="text-muted"><Badge tone={f.severity === "problem" ? "bad" : "info"}>{f.severity === "problem" ? "New problem" : "New note"}</Badge> {f.text}</div>)}</div>}
      </div>
      {prop.notes.map((n, i) => <p key={i} className="text-[11px] text-muted">{n}</p>)}
    </div>
  );
}

function Change({ label, from, to, change, good }: { label: string; from: string; to: string; change: string; good: boolean }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-2 tabular-nums"><span className="text-muted line-through">{from}</span><ArrowRight className="h-3 w-3 text-muted" /><span className="text-lg font-semibold">{to}</span></div>
      <div className={cn("text-[11px] font-medium", good ? "text-ok" : "text-muted")}>{change}</div>
    </div>
  );
}

function LevelCard({ lv, prop, edits, ticked, toggle, askAi, asking, aiInfo }: {
  lv: OptLevel; prop: OptProposal; edits: OptEdit[]; ticked: string[]; toggle: (id: string) => void; askAi: () => void; asking: boolean; aiInfo: OptAi | null;
}) {
  const here = edits.filter((e) => ticked.includes(e.id)).length;
  const isAi = lv.level === 4;
  if (!isAi && edits.length === 0) {
    return <div className="rounded-xl border border-dashed border-line px-3 py-2 text-xs text-muted"><b>Level {lv.level} · {lv.name}</b>: nothing to change here.</div>;
  }
  return (
    <HelpTip id="optimize-level">
      <div className={cn("rounded-xl border p-3", prop.stopped_at === lv.level ? "border-ok/50" : "border-line")}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">Level {lv.level} · {lv.name}</span>
          {prop.stopped_at === lv.level && !prop.goal.lowest && <Badge tone="ok">Meets your goal</Badge>}
          <span className="text-[11px] text-muted">{edits.length > 0 ? `${here} of ${edits.length} ticked · taking everything up to this level: ${signed(lv.saves.seconds, (x) => fmtSec(x))}, ${signed(lv.saves.cost, usd)}` : ""}</span>
        </div>
        <p className="mt-0.5 text-[11px] text-muted">{lv.help}</p>
        <div className="mt-2 space-y-1.5">
          {edits.map((e) => (
            <label key={e.id} className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 hover:bg-sunken">
              <input type="checkbox" className="mt-0.5" checked={ticked.includes(e.id)} onChange={() => toggle(e.id)} aria-label={e.label} />
              <span className="min-w-0 flex-1">
                <span className="text-[13px]">{e.label}</span>
                <span className="ml-2 text-[11px] tabular-nums text-ok">{e.effect.seconds ? signed(e.effect.seconds, (x) => fmtSec(x)) : ""}{e.effect.seconds && e.effect.cost ? " · " : ""}{e.effect.cost ? signed(e.effect.cost, usd) : ""}</span>
                {e.loses && <span className="block text-[11px] text-muted">You lose: {e.loses}</span>}
                {(e.reason || e.kept) && <span className="block text-[11px] text-muted">{e.reason}{e.reason && e.kept ? ". " : ""}{e.kept ? `Meaning kept: ${e.kept}` : ""}</span>}
              </span>
            </label>
          ))}
          {isAi && edits.length === 0 && (
            <div className="rounded-lg bg-sunken px-3 py-2 text-xs">
              {prop.ai.available ? (
                <>
                  <div>The AI can suggest shorter lines, or clips to drop or merge. It never changes a line marked <i>exact</i>, keeps at least one clip in every part, and keeps the joins where it can. You see every suggestion and tick what you want.</div>
                  <Button help="optimize-ai" className="mt-2" size="sm" variant="outline" loading={asking} onClick={askAi}><Sparkles className="h-3.5 w-3.5" />
                    Ask AI to tighten the script ({prop.ai.cost_high === 0 ? "free: the offline helper" : `about ${usd(prop.ai.cost_low)} to ${usd(prop.ai.cost_high)}`})</Button>
                  <span className="ml-2 text-[11px] text-muted">{prop.ai.model && prop.ai.cost_high > 0 ? `uses ${prop.ai.model}` : ""}</span>
                </>
              ) : <span className="text-muted">{prop.ai.why}</span>}
            </div>
          )}
          {isAi && aiInfo && aiInfo.skipped.length > 0 && <div className="space-y-0.5 text-[11px] text-muted">{aiInfo.skipped.map((s, i) => <div key={i}>Not used: {s}</div>)}</div>}
          {isAi && aiInfo && edits.length === 0 && aiInfo.edits.length === 0 && <div className="text-[11px] text-muted">{aiInfo.note || "The AI found nothing it could tighten without losing meaning."} (This cost {fmtUsd(aiInfo.cost_usd)}.)</div>}
          {isAi && aiInfo && edits.length > 0 && <div className="text-[11px] text-muted">The AI call cost {fmtUsd(aiInfo.cost_usd)}. {aiInfo.note}</div>}
        </div>
      </div>
    </HelpTip>
  );
}
