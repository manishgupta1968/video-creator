import { AlertTriangle, ArrowRight, CheckCircle2, Film, Link2, Loader2, Lock, Sparkles } from "lucide-react";
import { useMemo } from "react";
import { CutAnswer, CutRow, Node, OptMeasure, QuestionAnswer, ReplanQuestion, ReplanResult } from "../api";
import { findNode, fmtSec, fmtTime, fmtUsd, useP } from "../lib";
import { Badge, cn, HelpTip } from "../ui";

const MADE = ["done", "needs_pick", "generating", "queued"];
const usd = (v: number) => `$${v.toFixed(2)}`;

// ======================================================================= what may be cut?
/** A checklist of every part and clip, with what dropping it would save, so you decide with the numbers in front of you. */
export function CutsStep({ rows, answers, setAnswers, loading }: { rows: CutRow[] | null; answers: Record<string, CutAnswer>; setAnswers: (a: Record<string, CutAnswer>) => void; loading: boolean }) {
  const set = (n: string, v: CutAnswer) => {
    const next = { ...answers };
    if (v === "shorten") delete next[n]; else next[n] = v;
    setAnswers(next);
  };
  if (loading || !rows) return <div className="flex items-center gap-2 py-6 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" />Working out what each part and clip would save…</div>;
  const choices: { v: CutAnswer; label: string }[] = [{ v: "keep", label: "Must stay" }, { v: "shorten", label: "May shorten" }, { v: "cut", label: "May cut" }];
  return (
    <div className="space-y-3 text-sm">
      <HelpTip id="optimize-cuts">
        <div className="rounded-xl bg-sunken px-3 py-2 text-xs">
          <b>What may be cut?</b> The gentle changes cannot reach your goal, so tell the tool what it may remove. <b>Must stay</b> is never touched. <b>May shorten</b> is the usual choice (the AI may tighten the words).
          <b> May cut</b> lets the tool propose dropping it. The numbers are what dropping it would save. Clips that hold a line marked <i>exact</i>, clips you keep, and your own slides or footage always stay.
        </div>
      </HelpTip>
      <div className="overflow-hidden rounded-xl border border-line">
        <table className="w-full text-xs">
          <thead className="bg-sunken text-left text-[11px] text-muted"><tr><th className="px-3 py-1.5">What</th><th className="px-2 py-1.5">Length</th><th className="px-2 py-1.5">Dropping it saves</th><th className="px-2 py-1.5">Your choice</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const fixed = r.exact || r.protected;
              const cur: CutAnswer = answers[r.number] || "shorten";
              return (
                <tr key={r.number} className={cn("border-t border-line/60", r.kind === "part" && "bg-sunken/50 font-medium")}>
                  <td className={cn("px-3 py-1.5", r.kind === "clip" && "pl-7")}>
                    <span className="tabular-nums text-muted">{r.number}</span> {r.title}
                    {r.made && <Badge className="ml-1.5" tone="info">made</Badge>}
                    {fixed && <span className="ml-1.5 inline-flex items-center gap-0.5 text-[10px] text-muted"><Lock className="h-3 w-3" />{r.exact ? "holds an exact line" : r.note}</span>}
                    {r.made && !fixed && <span className="ml-1.5 text-[10px] text-muted">its video stays on disk if cut</span>}
                  </td>
                  <td className="px-2 py-1.5 tabular-nums">{fmtSec(r.seconds)}</td>
                  <td className="px-2 py-1.5 tabular-nums text-ok">{r.saves_seconds > 0 ? `${fmtSec(r.saves_seconds)}, ` : ""}{r.saves_cost > 0 ? usd(r.saves_cost) : "free"}</td>
                  <td className="px-2 py-1.5">
                    <div role="radiogroup" aria-label={`What may happen to ${r.number}`} className="inline-flex overflow-hidden rounded-lg border border-line">
                      {choices.map((c) => {
                        const off = fixed && c.v === "cut";
                        return (
                          <button key={c.v} type="button" role="radio" aria-checked={cur === c.v} disabled={off} onClick={() => set(r.number, c.v)}
                            className={cn("px-2 py-1 text-[11px]", cur === c.v ? (c.v === "cut" ? "bg-bad/15 text-bad" : c.v === "keep" ? "bg-brand/15 text-brand" : "bg-sunken font-medium") : "hover:bg-sunken", off && "cursor-not-allowed opacity-40")}>
                            {c.label}
                          </button>
                        );
                      })}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ======================================================================= the Goal, old and new
function words(t: string) { return t.split(/(\s+)/).filter((x) => x.length > 0); }

/** Word-level difference between two texts (what was removed, what was added), by the longest common run of words. */
export function diffWords(a: string, b: string): { t: string; k: "same" | "del" | "add" }[] {
  const x = words(a), y = words(b);
  const dp: number[][] = Array.from({ length: x.length + 1 }, () => new Array(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) for (let j = y.length - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { t: string; k: "same" | "del" | "add" }[] = [];
  let i = 0, j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { out.push({ t: x[i], k: "same" }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: x[i], k: "del" }); i++; }
    else { out.push({ t: y[j], k: "add" }); j++; }
  }
  while (i < x.length) out.push({ t: x[i++], k: "del" });
  while (j < y.length) out.push({ t: y[j++], k: "add" });
  return out;
}

export function GoalDiff({ label, before, after, text, setText }: { label: string; before: string; after: string; text: string; setText: (v: string) => void }) {
  const changed = after !== before;
  const parts = useMemo(() => diffWords(before, text), [before, text]);
  return (
    <div className="rounded-xl border border-line p-3 text-xs">
      <div className="mb-1 flex items-center gap-2 font-medium">{label}{!changed && <span className="text-[11px] font-normal text-muted">unchanged</span>}</div>
      <p className="leading-relaxed" aria-label={`${label}, changes marked`}>
        {parts.map((p, i) => p.k === "same" ? <span key={i}>{p.t}</span>
          : p.k === "del" ? <del key={i} className="rounded bg-bad/10 text-bad">{p.t}</del> : <ins key={i} className="rounded bg-ok/15 text-ok no-underline">{p.t}</ins>)}
      </p>
      <label className="mt-2 block text-[11px] text-muted">The new text (you can edit it; it is used exactly as you write it)
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} aria-label={`${label}: the new text`}
          className="mt-1 w-full rounded-lg border border-line bg-panel px-2 py-1.5 text-xs text-ink" />
      </label>
    </div>
  );
}

// ======================================================================= the planner asked something
export function QuestionsStep({ questions, answers, setAnswers, note }: { questions: ReplanQuestion[]; answers: QuestionAnswer[]; setAnswers: (a: QuestionAnswer[]) => void; note?: string }) {
  const pick = (q: ReplanQuestion, a: string) => setAnswers([...answers.filter((x) => x.id !== q.id), { id: q.id, text: q.text, answer: a }]);
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-start gap-2 rounded-lg bg-info/10 px-3 py-2 text-xs"><Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" /><span>The planner could not decide by itself and asks you.{note ? ` ${note}` : ""} Answer, and it is asked again (the cost is shown on the button).</span></div>
      {questions.map((q) => {
        const cur = answers.find((a) => a.id === q.id)?.answer || "";
        return (
          <div key={q.id} className="rounded-xl border border-line p-3">
            <div className="mb-2 font-medium">{q.text}</div>
            <div className="flex flex-wrap gap-2">
              {q.options.map((o) => <button key={o} type="button" aria-pressed={cur === o} onClick={() => pick(q, o)}
                className={cn("rounded-lg border px-3 py-1.5 text-xs", cur === o ? "border-brand bg-brand/10" : "border-line hover:border-brand/40")}>{o}</button>)}
              <input value={q.options.includes(cur) ? "" : cur} onChange={(e) => pick(q, e.target.value)} placeholder="or write your own answer" aria-label={`Your own answer to: ${q.text}`}
                className="h-8 min-w-[12rem] flex-1 rounded-lg border border-line bg-panel px-2 text-xs" />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ======================================================================= the new plan beside the current one
export function PlanStep({ res, reuse, setReuse, goalText, setGoalText, partGoalText, setPartGoalText, busy, scopeId }: {
  res: ReplanResult; reuse: Record<string, boolean>; setReuse: (r: Record<string, boolean>) => void; goalText: string; setGoalText: (v: string) => void;
  partGoalText: string; setPartGoalText: (v: string) => void; busy: boolean; scopeId: string;
}) {
  const P = useP();
  const plan = res.plan!;
  const project = P.view!.project;
  const isRoot = scopeId === project.root.id;
  const nowParts: Node[] = isRoot ? project.root.children : [findNode(project, scopeId)!];
  const mapped = plan.parts.flatMap((p) => p.clips).filter((c) => c.reuse_id && !c.forced);
  const madeMapped = mapped.filter((c) => { const n = findNode(project, c.reuse_id!); return n && MADE.includes(n.status); });
  const b = res.before, a = res.after;
  const set = (id: string, v: boolean) => setReuse({ ...reuse, [id]: v });
  const dl = (x: number, f: (n: number) => string) => (Math.abs(x) < 0.005 ? "no change" : `${x < 0 ? "−" : "+"}${f(Math.abs(x))}`);
  return (
    <div className="space-y-4 text-sm">
      <div className="relative grid grid-cols-3 gap-2">
        <Box label="Length" from={`~${fmtSec(b.seconds)}`} to={`~${fmtSec(a.seconds)}`} change={dl(a.seconds - b.seconds, fmtSec)} good={a.seconds < b.seconds} />
        <Box label="Still to spend" from={fmtUsd(b.cost)} to={fmtUsd(a.cost)} change={dl(a.cost - b.cost, usd)} good={a.cost < b.cost} />
        <Box label="Clips to make" from={String(b.to_make)} to={String(a.to_make)} change={dl(a.to_make - b.to_make, String)} good={a.to_make < b.to_make} />
        {busy && <div className="absolute inset-0 grid place-items-center rounded-xl bg-panel/70"><span className="inline-flex items-center gap-2 text-xs text-muted"><Loader2 className="h-4 w-4 animate-spin" />Working it out…</span></div>}
      </div>
      <p className="text-[11px] text-muted">The new clips have no script yet, so their numbers are a range from the plan. Writing their scripts comes after you apply (the cost is shown first).</p>
      {plan.warnings.map((w, i) => <div key={i} className="flex items-start gap-2 rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}</div>)}
      {plan.note && <p className="rounded-lg bg-sunken px-3 py-2 text-xs"><b>The planner says:</b> {plan.note}</p>}

      <GoalDiff label={isRoot ? "The main Goal" : "The main Goal (one short clause added)"} before={plan.goal.old} after={plan.goal.new} text={goalText} setText={setGoalText} />
      {!isRoot && <GoalDiff label="This part's Goal" before={plan.part_goal.old} after={plan.part_goal.new} text={partGoalText} setText={setPartGoalText} />}

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-line p-3 text-xs">
          <div className="mb-1.5 font-medium text-muted">The plan now</div>
          {nowParts.map((p) => (
            <div key={p.id} className="mb-1.5">
              <div className="font-medium">{P.numbers[p.id]} {p.title || p.goal.slice(0, 40)} <span className="font-normal tabular-nums text-muted">{fmtSec(p.duration.likely_s)} · {usd(p.cost.likely_usd)}</span></div>
              {(p.kind === "goal" ? flat(p) : []).map((c) => (
                <div key={c.id} className="flex gap-1.5 pl-3 text-muted"><span className="w-7 tabular-nums">{P.numbers[c.id]}</span><span className="min-w-0 flex-1 truncate">{c.title || c.goal}</span>
                  {MADE.includes(c.status) && <Badge tone="info">made</Badge>}<span className="tabular-nums">{fmtSec(c.duration.likely_s)}</span></div>
              ))}
            </div>
          ))}
        </div>
        <div className="rounded-xl border border-ok/40 p-3 text-xs">
          <div className="mb-1.5 font-medium text-ok">The new plan</div>
          {res.outline.map((p) => (
            <div key={p.number} className="mb-1.5">
              <div className="font-medium">{p.number} {p.title} <span className="font-normal tabular-nums text-muted">{fmtSec(p.seconds)} · {usd(p.cost)}</span></div>
              {p.clips.map((c) => (
                <div key={c.number} className="flex gap-1.5 pl-3"><span className="w-7 tabular-nums text-muted">{c.number}</span><span className="min-w-0 flex-1 truncate">{c.title}</span>
                  {c.reused && c.made ? <Badge tone="ok">reuses its video</Badge> : c.reused ? <Badge>kept</Badge> : <Badge tone="brand">new</Badge>}
                  <span className="tabular-nums text-muted">{fmtSec(c.seconds)}</span></div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {(madeMapped.length > 0 || plan.unused_made.length > 0 || plan.forced.length > 0) && (
        <HelpTip id="optimize-reuse">
          <div className="rounded-xl border border-line p-3 text-xs">
            <div className="mb-1.5 flex items-center gap-2 font-medium"><Film className="h-3.5 w-3.5 text-brand" />Your videos</div>
            <p className="mb-2 text-muted">A video already made is yours: reuse it, or make a new one. Nothing is deleted: a video that is not used stays on disk, and Undo brings it back.</p>
            <div className="space-y-1.5">
              {madeMapped.map((c) => (
                <label key={c.reuse_id!} className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1 hover:bg-sunken">
                  <input type="checkbox" className="mt-0.5" checked={reuse[c.reuse_id!] !== false} onChange={(e) => set(c.reuse_id!, e.target.checked)} aria-label={`Reuse the video of clip ${c.reuse_number}`} />
                  <span>Clip {c.reuse_number} <b>{c.title}</b>: <span className="text-muted">the new plan keeps it as it is. Reuse its video (untick to make a new one).</span></span>
                </label>
              ))}
              {plan.unused_made.map((u) => (
                <label key={u.id} className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1 hover:bg-sunken">
                  <input type="checkbox" className="mt-0.5" checked={!!reuse[u.id]} onChange={(e) => set(u.id, e.target.checked)} aria-label={`Keep the video of clip ${u.number} in part ${u.part_number}`} />
                  <span>Clip {u.number} <b>{u.title}</b> is made but not in the new plan. <span className="text-muted">Tick to keep it in part {u.part_number}; otherwise its video stays on disk, unused.</span></span>
                </label>
              ))}
              {plan.forced.map((f) => <div key={f.id} className="flex items-start gap-2 px-2 py-0.5 text-muted"><Lock className="mt-0.5 h-3 w-3 shrink-0" />Clip {f.number} stays: {f.why}.</div>)}
            </div>
          </div>
        </HelpTip>
      )}
      <div className="flex items-start gap-2 text-[11px] text-muted"><Link2 className="mt-0.5 h-3 w-3 shrink-0" />Joins are rebuilt for the new neighbours, the saved background music stays reusable, and every length follows the new plan.</div>
    </div>
  );
}

function flat(n: Node): Node[] { return n.children.flatMap((c) => (c.kind === "goal" ? flat(c) : [c])); }

function Box({ label, from, to, change, good }: { label: string; from: string; to: string; change: string; good: boolean }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-2 tabular-nums"><span className="text-muted line-through">{from}</span><ArrowRight className="h-3 w-3 text-muted" /><span className="text-lg font-semibold">{to}</span></div>
      <div className={cn("text-[11px] font-medium", good ? "text-ok" : "text-muted")}>{change}</div>
    </div>
  );
}
