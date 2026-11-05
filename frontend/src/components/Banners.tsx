import { AlertTriangle, Download, Info, KeyRound } from "lucide-react";
import { fileUrl } from "../api";
import { useP } from "../lib";
import { Badge, Button, Dialog, Tip } from "../ui";

const JOB_NAME: Record<string, string> = { video: "video", avatar: "talking animation", image: "pictures", voice: "voices" };

/** Says plainly when only free placeholder output will be made, and what to add. */
export function PreviewBanner() {
  const P = useP();
  const info = P.view?.summary.preview;
  if (!info) return null;
  const n = Object.keys(info.clips).length;
  const unused = info.voice_sample_unused;
  if (n === 0 && unused.length === 0) return null;
  const jobs = Object.keys(info.jobs);
  if (n === 0) {
    return (
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-warn/10 px-4 py-2 text-xs text-warn">
        <AlertTriangle className="h-4 w-4 shrink-0" /><span className="flex-1">{unused[0]}</span>
        <Button size="sm" variant="outline" onClick={() => P.openSettings("keys")}><KeyRound className="h-3.5 w-3.5" />Add a key</Button>
      </div>
    );
  }
  const chosen = info.chosen_free_mode;
  return (
    <div className={`flex flex-wrap items-start gap-2 border-b border-line px-4 py-2 text-xs ${chosen ? "bg-info/10 text-info" : "bg-warn/10 text-warn"}`}>
      {chosen ? <Info className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
      <div className="min-w-0 flex-1">
        <div className="font-semibold">
          {chosen ? "Free preview mode is on." : info.all_preview ? "Preview mode: no real video or image model is connected." : `${n} clip(s) will only be placeholders.`}
          {" "}Clips are made as text cards with gentle motion, not real footage.
        </div>
        <div className="mt-0.5 opacity-90">
          Missing for real results: {jobs.map((j) => JOB_NAME[j] || j).join(", ")}. {Object.values(info.jobs).slice(0, 2).join(" ")}
        </div>
        {unused.map((u) => <div key={u} className="mt-0.5">{u}</div>)}
      </div>
      <Button size="sm" variant="outline" onClick={() => P.openSettings("keys")}><KeyRound className="h-3.5 w-3.5" />Add keys</Button>
    </div>
  );
}

export function PreviewBadge({ nodeId }: { nodeId: string }) {
  const P = useP();
  const r = P.view?.summary.preview.clips[nodeId];
  if (!r || r.length === 0) return null;
  const what = r.map((x) => JOB_NAME[x] || x).join(", ");
  return (
    <Tip content={`Only free placeholders for: ${what}. Add keys in Settings to get real results.`}>
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
