import { Clapperboard, Music } from "lucide-react";
import React, { createContext, useContext, useState } from "react";
import { api, MusicStatus } from "../api";
import { useP } from "../lib";
import { Button, Dialog } from "../ui";

type Choice = "auto" | "reuse" | "new" | "none";
const Ctx = createContext<() => void>(() => {});
/** Joins the clips into the final video. If new background music would have to be paid for, it says so first. */
export const useJoin = () => useContext(Ctx);

export function JoinProvider({ children }: { children: React.ReactNode }) {
  const P = useP();
  const [st, setSt] = useState<MusicStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async (music: Choice) => {
    setBusy(true);
    await P.act("Joining", () => api.assemble(P.pid, music));
    setBusy(false);
    setSt(null);
  };
  const start = async () => {
    let status: MusicStatus | null = null;
    try { status = await api.musicStatus(P.pid); } catch { status = null; }
    // nothing to pay for (music off, a free track, or a saved track that still fits): just join
    if (!status || !status.enabled || status.cost_usd === 0) { await P.act("Joining", () => api.assemble(P.pid, "auto")); return; }
    setSt(status);
  };
  const usd = (v: number) => `$${v.toFixed(2)}`;
  return (
    <Ctx.Provider value={start}>
      {children}
      <Dialog open={!!st} onOpenChange={(o) => !o && setSt(null)} wide title="Join the clips into the final video"
        description="Check the background music first. Nothing is paid for until you choose."
        footer={st && <>
          <Button variant="ghost" onClick={() => setSt(null)}>Cancel</Button>
          <Button help="join-music" variant="outline" loading={busy} onClick={() => go("none")}>Join without music</Button>
          {st.saved && <Button variant="outline" loading={busy} onClick={() => go("reuse")}>Use the saved music (free)</Button>}
          <Button variant="primary" loading={busy} onClick={() => go("new")}><Clapperboard className="h-3.5 w-3.5" />Make new music, then join ≈ {usd(st.cost_usd)}</Button>
        </>}>
        {st && (
          <div className="space-y-3 text-sm">
            <div className="flex items-start gap-2 rounded-xl border border-line p-3">
              <Music className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
              <div>
                {st.saved ? (
                  <>
                    <div className="font-medium">New background music is needed</div>
                    <div className="text-muted">The saved music was made for {Math.round(st.made_for_s)} s. {st.why ? st.why.charAt(0).toUpperCase() + st.why.slice(1) + "." : ""} It can still be used (it repeats to fit), for free.</div>
                  </>
                ) : (
                  <>
                    <div className="font-medium">No background music has been made yet</div>
                    <div className="text-muted">A new track is made once for the whole video ({st.model}, about {Math.round(st.total_s)} s) and saved.</div>
                  </>
                )}
                <div className="mt-1.5">New music costs about <b>{usd(st.cost_usd)}</b>. It is then reused for free by every later join and by every part you download.</div>
              </div>
            </div>
          </div>
        )}
      </Dialog>
    </Ctx.Provider>
  );
}
