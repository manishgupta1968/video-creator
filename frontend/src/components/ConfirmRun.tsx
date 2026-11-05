import { AlertTriangle, Clock, Coins, Film, Play } from "lucide-react";
import React, { createContext, useContext, useState } from "react";
import { api, Estimate } from "../api";
import { fmtTime, fmtUsd, useP } from "../lib";
import { Button, Dialog, Meter, Switch } from "../ui";
import { askNotificationPermission } from "./ActivityBar";

type Req = { mode: string; targets?: string[]; title: string };
const Ctx = createContext<(r: Req) => void>(() => {});
export const useRun = () => useContext(Ctx);

/** Every Generate button goes through here: shows cost & time first. */
export function RunProvider({ children }: { children: React.ReactNode }) {
  const P = useP();
  const [req, setReq] = useState<Req | null>(null);
  const [est, setEst] = useState<Estimate | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoPick, setAutoPick] = useState(false);

  const open = async (r: Req) => {
    setReq(r);
    setEst(null);
    setAutoPick(!!P.view?.project.settings.auto_pick);
    try { setEst(await api.estimate(P.pid, { mode: r.mode, targets: r.targets })); } catch { setEst(null); }
  };
  const go = async () => {
    if (!req) return;
    setLoading(true);
    askNotificationPermission();      // so the browser can tell you when it needs you, or is done
    await P.act("Starting", () => api.run(P.pid, req.mode, req.targets, autoPick));
    setLoading(false);
    setReq(null);
  };
  const nums = P.numbers;
  const free = est && est.cost_usd === 0;
  const prev = P.view?.summary.preview;
  const previewClips = est && prev ? est.clips.filter((id) => (prev.clips[id] || []).length > 0) : [];
  return (
    <Ctx.Provider value={open}>
      {children}
      <Dialog open={!!req} onOpenChange={(o) => !o && setReq(null)} title={req?.title || ""}
        description={free ? "This uses only free tools." : "Check the cost and time before anything is paid for."}
        footer={<>
          <Button variant="ghost" onClick={() => setReq(null)}>Cancel</Button>
          <Button help="confirm-spend" variant="primary" onClick={go} loading={loading} disabled={!est}><Play className="h-3.5 w-3.5" />{free ? "Make it" : `Spend ≈ ${fmtUsd(est?.cost_usd)}`}</Button>
        </>}>
        {!est ? <div className="skeleton h-24 rounded-lg" /> : (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-2">
              <Stat icon={<Film className="h-4 w-4" />} label="Clips" value={String(est.clips.length)} />
              <Stat icon={<Coins className="h-4 w-4" />} label="Cost" value={fmtUsd(est.cost_usd)} />
              <Stat icon={<Clock className="h-4 w-4" />} label="Time" value={`~${fmtTime(est.time_s)}`} />
            </div>
            {previewClips.length > 0 && (
              <div className="rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn">
                <div className="flex items-center gap-1.5 font-semibold"><AlertTriangle className="h-3.5 w-3.5" />{previewClips.length} of these {est.clips.length} clip(s) will only be text-card previews, not real footage.</div>
                <div className="mt-1">{Object.values(prev!.jobs).slice(0, 2).join(" ")}</div>
                <button className="mt-1 underline" onClick={() => { setReq(null); P.openSettings("keys"); }}>Add keys in Settings</button>
              </div>
            )}
            {est.extra_upstream.length > 0 && (
              <div className="rounded-lg bg-info/10 px-3 py-2 text-xs text-info">
                Includes {est.extra_upstream.length} earlier clip(s) this one needs first: {est.extra_upstream.map((i) => nums[i]).join(", ")}
              </div>
            )}
            <div>
              <div className="mb-1 flex justify-between text-xs"><span className="text-muted">Budget after this</span>
                <span>{fmtUsd(est.spent_usd + est.cost_usd)} of {fmtUsd(est.budget_usd)}</span></div>
              <Meter value={est.spent_usd + est.cost_usd} max={est.budget_usd} />
              {est.over_budget && <div className="mt-2 flex items-center gap-1.5 text-xs text-bad"><AlertTriangle className="h-3.5 w-3.5" />Over budget — the run will pause before the clip that crosses it.</div>}
            </div>
            <Switch help="auto-pick" checked={autoPick} onChange={setAutoPick} label="Auto-pick the best take (so the run can finish without me)" />
            <p className="text-[11px] text-muted">Clips that don't depend on each other are made at the same time. You can pause or stop at any time; finished clips are kept.</p>
          </div>
        )}
      </Dialog>
    </Ctx.Provider>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="flex items-center gap-1.5 text-[11px] text-muted">{icon}{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}
