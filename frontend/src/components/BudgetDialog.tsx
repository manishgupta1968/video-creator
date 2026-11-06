import { useQuery } from "@tanstack/react-query";
import { Coins, Wallet } from "lucide-react";
import { api, BudgetGroup } from "../api";
import { fmtSec, fmtTime, fmtUsd, useP } from "../lib";
import { Badge, Dialog, Meter } from "../ui";

const money = (v: number) => (v === 0 ? "$0.00" : v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);

/** "Where did the money go?" Every number is explained, and every paid call is listed. */
export default function BudgetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const P = useP();
  const p = P.view?.project;
  const q = useQuery({ queryKey: ["budget", P.pid, p?.updated_at, p?.run.spent_usd], queryFn: () => api.budget(P.pid), enabled: open });
  const r = q.data;
  const used = r ? r.spent + r.remaining_estimate : 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide="xl" title="Cost and budget: where the money goes"
      description="Every amount below is worked out from calls this tool made, so you can check it against your vendor bills.">
      {!r ? <div className="skeleton h-40 rounded-lg" /> : (
        <div className="space-y-6 text-xs">
          <section aria-label="Summary" className="grid gap-3 sm:grid-cols-4">
            <Stat label="Your budget" value={money(r.budget)} hint="The limit you set. A safety net, not a bill." />
            <Stat label="Spent so far" value={money(r.spent)} hint="Total of every paid call listed below." />
            <Stat label="Still to spend" value={`≈ ${money(r.remaining_estimate)}`} hint="Estimate for the clips not made yet." />
            <Stat label="Left in budget" value={`≈ ${money(r.left_in_budget)}`} tone={r.left_in_budget < 0 ? "bad" : "ok"} hint="Budget − spent − still to spend." />
          </section>
          <div>
            <div className="mb-1 flex justify-between"><span className="text-muted">Spent plus still to spend, against the budget</span><span>{money(used)} of {money(r.budget)}</span></div>
            <Meter value={used} max={r.budget} />
          </div>

          <CostByPart />

          <section aria-label="What the numbers mean">
            <h3 className="mb-2 text-[13px] font-semibold">What these numbers mean</h3>
            <ul className="space-y-1.5">
              {r.explain.map((line, i) => <li key={i} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" /><span>{line}</span></li>)}
            </ul>
            {r.brain.plugin !== "fake_llm" && (
              <p className="mt-2 rounded-lg bg-sunken/70 px-3 py-2">Your AI brain is <b>{r.brain.plugin}</b> ({r.brain.model}) at {r.brain.price}. Example: 10,000 tokens in and 2,000 tokens out costs 10,000 × the in-price + 2,000 × the out-price, divided by one million.</p>
            )}
          </section>

          <section aria-label="Where the money went">
            <h3 className="mb-2 text-[13px] font-semibold">Where the money went</h3>
            {r.groups.length === 0 ? (
              <div className="rounded-xl border border-dashed border-line p-6 text-center text-muted">Nothing has been spent yet. Planning with the offline brain and free previews cost nothing.</div>
            ) : (
              <div className="space-y-2">{r.groups.map((g) => <Group key={g.key} g={g} />)}</div>
            )}
            <p className="mt-2 text-[11px] text-muted">The same list is saved on your computer in the project folder as <code>ledger.jsonl</code>.</p>
          </section>

          <section aria-label="Change the budget" className="flex flex-wrap items-center gap-3 rounded-xl border border-line p-3">
            <Wallet className="h-4 w-4 text-muted" />
            <span className="font-medium">Change the budget for this video</span>
            <span className="text-muted">$</span>
            <input type="number" min={0} step={1} defaultValue={r.budget} key={r.budget} aria-label="Budget in dollars"
              className="h-8 w-28 rounded-md border border-line bg-panel px-2 text-right"
              onBlur={(e) => { const v = Number(e.target.value); if (v !== r.budget && v >= 0) P.act("Save", () => api.patch(P.pid, { settings: { budget_usd: v } }), "Budget changed"); }} />
            <span className="text-[11px] text-muted">The default for new videos is in Settings → Budget &amp; quality.</span>
          </section>
        </div>
      )}
    </Dialog>
  );
}

const QUALITY_NAME: Record<string, string> = { best: "Best", balanced: "Balanced", budget: "Budget", free: "Free preview" };

/** Every part and clip with its length, cost, making time, quality and model. The part rows add up to the whole video. */
function CostByPart() {
  const P = useP();
  const s = P.view?.summary;
  if (!s || s.parts.length === 0) return null;
  const cell = "py-1.5 pr-3";
  return (
    <section aria-label="Cost by part" data-help="cost-by-part">
      <h3 className="mb-2 text-[13px] font-semibold">Cost by part</h3>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-left">
          <caption className="sr-only">Length, cost, time, quality and model of every part and clip</caption>
          <thead className="bg-sunken/60 text-[11px] text-muted">
            <tr><th className="px-3 py-1.5 font-medium">Part or clip</th><th className="font-medium">Length</th><th className="font-medium">Cost</th><th className="font-medium">Time to make</th>
              <th className="font-medium">Quality</th><th className="font-medium">Model</th><th className="pr-3 font-medium">Made</th></tr>
          </thead>
          <tbody>
            {s.parts.map((r) => (
              <tr key={r.id} className={`border-t border-line/60 ${r.kind === "goal" ? "font-medium" : "text-muted"}`}>
                <td className="px-3 py-1.5" style={{ paddingLeft: 12 + r.depth * 14 }}><span className="mr-1.5 tabular-nums">{r.number}</span>{r.title}</td>
                <td className={`${cell} tabular-nums`}>{fmtSec(r.seconds)}</td>
                <td className={`${cell} tabular-nums`} title={`Range ${fmtUsd(r.cost_min)} to ${fmtUsd(r.cost_max)}`}>{fmtUsd(r.cost)}</td>
                <td className={`${cell} tabular-nums`}>{r.time_s > 0 ? `~${fmtTime(r.time_s)}` : "–"}</td>
                <td className={cell}>{r.kind === "goal" ? QUALITY_NAME[r.quality] || r.quality : ""}</td>
                <td className={cell}>{r.models.join(", ") || "–"}</td>
                <td className="py-1.5 pr-3 tabular-nums">{r.done}/{r.clips}</td>
              </tr>
            ))}
            <tr className="border-t-2 border-line font-semibold">
              <td className="px-3 py-1.5">Whole video</td><td className={`${cell} tabular-nums`}>{fmtSec(s.seconds)}</td>
              <td className={`${cell} tabular-nums`}>{fmtUsd(s.cost_total)}</td><td className={`${cell} tabular-nums`}>{s.time_s > 0 ? `~${fmtTime(s.time_s)}` : "–"}</td>
              <td className={cell}>{QUALITY_NAME[s.quality_mode] || s.quality_mode}</td><td className={cell} /><td className="py-1.5 pr-3 tabular-nums">{s.done}/{s.clips}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-muted">Costs are estimates for each part's clips (price × amount × takes). “Time to make” is what is left; clips that do not depend on each other are made together, so the part times do not add up to the whole.</p>
    </section>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint: string; tone?: "ok" | "bad" }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${tone === "bad" ? "text-bad" : ""}`}>{value}</div>
      <div className="mt-0.5 text-[11px] text-muted">{hint}</div>
    </div>
  );
}

function Group({ g }: { g: BudgetGroup }) {
  return (
    <details className="group rounded-xl border border-line open:bg-sunken/30">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-3 py-2.5 [&::-webkit-details-marker]:hidden">
        <Coins className="h-4 w-4 text-muted" />
        <span className="flex-1 font-medium">{g.label}</span>
        <Badge>{g.calls} call{g.calls === 1 ? "" : "s"}</Badge>
        <span className="w-24 text-right font-semibold tabular-nums">{money(g.actual)}</span>
        <span className="text-muted group-open:rotate-90 transition-transform" aria-hidden>›</span>
      </summary>
      <div className="overflow-x-auto px-3 pb-3">
        <table className="w-full text-left">
          <caption className="sr-only">{g.label}: each call</caption>
          <thead className="text-[11px] text-muted"><tr><th className="py-1 font-medium">What</th><th className="font-medium">Service</th><th className="font-medium">How it was counted</th><th className="text-right font-medium">Estimated</th><th className="text-right font-medium">Counted</th></tr></thead>
          <tbody>
            {g.rows.map((row, i) => (
              <tr key={i} className="border-t border-line/60">
                <td className="py-1.5 pr-2">{row.what}</td>
                <td className="pr-2 text-muted">{row.vendor} {row.model}</td>
                <td className="pr-2 text-muted">{row.how || "—"}</td>
                <td className="text-right tabular-nums text-muted">{money(row.estimated)}</td>
                <td className="text-right tabular-nums">{money(row.actual)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export { fmtUsd };
