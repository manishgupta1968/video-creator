import { AlertTriangle, Download, Info, KeyRound } from "lucide-react";
import { api, fileUrl } from "../api";
import { useP } from "../lib";
import { Badge, Button, Dialog, Tip } from "../ui";

const JOB_NAME: Record<string, string> = { video: "video", avatar: "talking animation", image: "pictures", voice: "voices" };

/** Says plainly when only free placeholder output will be made, WHY (a clip you pinned to a free model, a missing key, free preview
 *  quality, or no model that fits), and what to do about it. It never blames a missing key when the key is there. */
export function PreviewBanner() {
  const P = useP();
  const info = P.view?.summary.preview;
  if (!info) return null;
  const n = Object.keys(info.clips).length;
  const unused = info.voice_sample_unused;
  if (n === 0 && unused.length === 0) return null;
  const jobs = Object.keys(info.jobs);                      // only kinds of work with no real model connected
  const chosen = info.chosen_free_mode;
  const pinned = info.pinned || [];
  const causes = Object.values(info.causes || {}).flatMap((c) => Object.values(c));
  const noKeyClips = Object.values(info.causes || {}).filter((c) => Object.values(c).includes("no_key")).length;
  const uncovered = causes.includes("not_covered");
  const bar = "flex flex-wrap items-start gap-2 border-b border-line px-4 py-2 text-xs";
  return (
    <div>
      {pinned.length > 0 && (
        <div className={`${bar} bg-warn/10 text-warn`}>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold">{pinned.length} clip(s) are set to the free preview model, so they will only be placeholders.</div>
            <div className="mt-0.5 opacity-90">This is a choice made on the clip (its Model box), not a missing key. Your keys are fine.</div>
          </div>
          <Button help="unpin" size="sm" variant="outline" loading={P.busy.includes("Choosing the best model")}
            onClick={() => P.act("Choosing the best model", () => api.unpin(P.pid), "These clips use the best model again. Make the out-of-date ones again.")}>Use the best model</Button>
        </div>
      )}
      {chosen && (
        <div className={`${bar} bg-info/10 text-info`}>
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1"><div className="font-semibold">Free preview mode is on. Clips are made as text cards with gentle motion, not real footage.</div>
            <div className="mt-0.5 opacity-90">Change “Quality” at the top to Balanced, Budget or Best to get real footage.</div></div>
        </div>
      )}
      {!chosen && jobs.length > 0 && (
        <div className={`${bar} bg-warn/10 text-warn`}>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold">
              {info.all_preview ? "Preview mode: no real video or image model is connected." : `${noKeyClips} clip(s) will only be placeholders.`}
              {" "}Clips are made as text cards with gentle motion, not real footage.
            </div>
            <div className="mt-0.5 opacity-90">Missing for real results: {jobs.map((j) => JOB_NAME[j] || j).join(", ")}. {Object.values(info.jobs).slice(0, 2).join(" ")}</div>
          </div>
          <Button size="sm" variant="outline" onClick={() => P.openSettings("keys")}><KeyRound className="h-3.5 w-3.5" />Add keys</Button>
        </div>
      )}
      {!chosen && uncovered && (
        <div className={`${bar} bg-warn/10 text-warn`}>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">Real models are connected, but none of them fits what some clips need, so those clips will only be placeholders. Open the clip to see what it needs.</div>
        </div>
      )}
      {unused.length > 0 && (
        <div className={`${bar} bg-warn/10 text-warn`}>
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span className="flex-1">{unused[0]}</span>
          <Button size="sm" variant="outline" onClick={() => P.openSettings("keys")}><KeyRound className="h-3.5 w-3.5" />Add a key</Button>
        </div>
      )}
    </div>
  );
}

export function PreviewBadge({ nodeId }: { nodeId: string }) {
  const P = useP();
  const r = P.view?.summary.preview.clips[nodeId];
  if (!r || r.length === 0) return null;
  const why = Object.values(P.view?.summary.preview.causes?.[nodeId] || {});
  const what = r.map((x) => JOB_NAME[x] || x).join(", ");
  const text = why.includes("pinned") ? "This clip is set to the free preview model (its Model box). Choose “Auto” there, or use “Use the best model” at the top."
    : why.includes("free_mode") ? "Free preview quality is on. Change Quality at the top to get real footage."
    : why.includes("not_covered") ? `Real models are connected, but none fits what this clip needs (${what}).`
    : `Only free placeholders for: ${what}. Add keys in Settings to get real results.`;
  return (
    <Tip content={text}>
      <span><Badge tone="warn">Preview</Badge></span>
    </Tip>
  );
}

export function FinalVideoDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const P = useP();
  const p = P.view?.project;
  if (!p || !p.final_output) return null;
  const url = fileUrl(P.pid, p.final_output);
  const credits = fileUrl(P.pid, "output/credits.txt");
  const hasCredits = p.context.some((c) => (c.analysis?.credits || []).length > 0);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide title="Your final video" description="All clips joined with transitions, music and subtitles."
      footer={<>
        <a href={fileUrl(P.pid, "output/final.srt")} download><Button variant="ghost" size="sm">Subtitles (.srt)</Button></a>
        {hasCredits && <a href={credits} download><Button variant="ghost" size="sm">Photo credits</Button></a>}
        <a href={url} download><Button variant="primary"><Download className="h-3.5 w-3.5" />Download</Button></a>
      </>}>
      <video src={url} controls autoPlay className="w-full rounded-xl bg-black" />
    </Dialog>
  );
}
