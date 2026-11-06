import { Clock, Coins, Film, Gauge, Wallet } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fmtSec, fmtTime, fmtUsd, useP } from "../lib";
import { cn, HelpTip, Meter, Select } from "../ui";

const QUALITY = [{ value: "best", label: "Best quality" }, { value: "balanced", label: "Balanced" }, { value: "budget", label: "Budget" }, { value: "free", label: "Free preview" }];
const usd = (v: number) => `$${v.toFixed(2)}`;

/** The numbers a person looks at first, always visible: how long, how much, how long to make, what quality, what budget.
 *  A small chip shows what the last edit changed, so you see the effect of what you did. */
export default function SummaryStrip() {
  const P = useP();
  const s = P.view!.summary;
  const p = P.view!.project;
  const over = s.budget > 0 && s.spent + s.cost > s.budget + 1e-6;
  const auto = s.length_mode === "auto";
  const lengthOff = !auto && s.target_seconds > 0 && Math.abs(s.seconds - s.target_seconds) / s.target_seconds > 0.1;
  const openBudget = () => window.dispatchEvent(new Event("vg-open-budget"));

  // what the last edit changed (the whole-video estimate does not move while clips are being made, only when you edit)
  const prev = useRef<{ cost: number; sec: number } | null>(null);
  const [delta, setDelta] = useState<{ cost: number; sec: number } | null>(null);
  useEffect(() => {
    const now = { cost: s.cost_total, sec: s.seconds };
    const was = prev.current;
    prev.current = now;
    if (!was) return;
    const d = { cost: now.cost - was.cost, sec: now.sec - was.sec };
    if (Math.abs(d.cost) >= 0.01 || Math.abs(d.sec) >= 0.5) {
      setDelta(d);
      const t = window.setTimeout(() => setDelta(null), 9000);
      return () => window.clearTimeout(t);
    }
  }, [s.cost_total, s.seconds]);
  const sign = (v: number, f: (x: number) => string) => `${v > 0 ? "+" : "−"}${f(Math.abs(v))}`;

  return (
    <section aria-label="Length, cost, time, quality and budget" data-help="summary-strip"
      className="grid grid-cols-2 gap-2 border-b border-line bg-panel px-3 py-2 sm:grid-cols-3 lg:grid-cols-5">
      <Tile id="summary-length" icon={<Film className="h-3.5 w-3.5" />} label="Length" tone={lengthOff ? "warn" : undefined}
        value={`~${fmtSec(s.seconds)}`} sub={auto ? "Auto: as short as the story allows" : `target ${fmtSec(s.target_seconds)}${lengthOff ? " (not met)" : ""}`}
        onClick={() => P.select(p.root.id)} chip={delta && Math.abs(delta.sec) >= 0.5 ? sign(delta.sec, (x) => fmtSec(Math.round(x))) : undefined} />
      <Tile id="summary-cost" icon={<Coins className="h-3.5 w-3.5" />} label="Cost of the whole video" tone={over ? "bad" : undefined}
        value={s.cost_total === 0 ? "Free" : `≈ ${usd(s.cost_total)}`}
        sub={over ? `over your ${usd(s.budget)} budget` : s.spent > 0 ? `${fmtUsd(s.cost)} still to spend · ${usd(s.spent)} spent` : "estimate before you spend anything"}
        onClick={openBudget} chip={delta && Math.abs(delta.cost) >= 0.01 ? sign(delta.cost, usd) : undefined} />
      <Tile id="summary-time" icon={<Clock className="h-3.5 w-3.5" />} label="Time to make" value={s.time_s > 0 ? `~${fmtTime(s.time_s)}` : "Nothing left"}
        sub={s.clips > 0 && s.done === s.clips ? (s.time_s > 0 ? "to join the clips into the final video" : "every clip is made") : s.time_s > 0 ? "clips that do not depend on each other run together" : "every clip is made"} onClick={openBudget} />
      <Tile id="summary-quality" icon={<Gauge className="h-3.5 w-3.5" />} label="Quality" sub="for the whole video"
        value={<Select title="Quality for the whole video" value={p.settings.quality_mode} options={QUALITY} className="h-8 border-0 bg-transparent px-0 text-base font-semibold"
          onChange={(v) => P.act("Save", () => api.patch(P.pid, { settings: { quality_mode: v } }))} />} />
      <Tile id="summary-budget" icon={<Wallet className="h-3.5 w-3.5" />} label="Budget" tone={over ? "bad" : undefined}
        value={`${usd(s.spent)} of ${usd(s.budget)}`} sub={<Meter value={s.spent + s.cost} max={s.budget} />} onClick={openBudget} />
    </section>
  );
}

function Tile({ id, icon, label, value, sub, tone, onClick, chip }: {
  id: string; icon: React.ReactNode; label: string; value: React.ReactNode; sub: React.ReactNode; tone?: "warn" | "bad"; onClick?: () => void; chip?: string;
}) {
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-[11px] text-muted">{icon}{label}
        {chip && <span aria-live="polite" className="ml-auto rounded-full bg-brand/10 px-1.5 text-[10px] font-semibold text-brand">{chip}</span>}
      </div>
      <div className="mt-0.5 min-h-[1.75rem] text-lg font-semibold tabular-nums leading-7">{value}</div>
      <div className="text-[11px] leading-snug text-muted">{sub}</div>
    </>
  );
  const cls = cn("flex flex-col items-stretch justify-start rounded-xl border px-3 py-1.5 text-left", tone === "bad" ? "border-bad/50 bg-bad/5" : tone === "warn" ? "border-warn/50 bg-warn/5" : "border-line",
    onClick && "cursor-pointer hover:border-brand/40");
  return (
    <HelpTip id={id}>
      {onClick ? <button type="button" onClick={onClick} className={cls}>{body}</button> : <div className={cls}>{body}</div>}
    </HelpTip>
  );
}
