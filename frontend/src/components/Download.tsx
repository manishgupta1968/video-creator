import { Download as DownloadIcon, Music } from "lucide-react";
import { useState } from "react";
import { api, ExportResult, Node } from "../api";
import { useP, useToast, walk } from "../lib";
import { Button, Dialog, HelpTip, Tip } from "../ui";

const usd = (v: number) => `$${v.toFixed(2)}`;

/** Everything needed to save the video of one clip or part: how many clips are still to make, the action, and the question about
 *  music (asked only when a new track would cost money). Render `dialog` once, somewhere that stays mounted. */
export function useDownload(node: Node) {
  const P = useP();
  const toast = useToast();
  const isLeaf = node.kind !== "goal";
  const clips = walk(node).filter((n) => n.kind !== "goal");
  const left = clips.filter((c) => c.status !== "done" || !c.output).length;
  const [ask, setAsk] = useState<ExportResult | null>(null);
  const [busy, setBusy] = useState(false);

  const trigger = (url: string, name = "") => {
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  const save = (r: ExportResult) => {
    trigger(r.url as string, r.filename);
    toast({ text: `Saved ${r.filename} (${Math.round(r.seconds || 0)} s${r.with_music ? ", with the music of the final video" : isLeaf ? "" : ", no music"})`, tone: "ok",
      action: r.srt_url ? { label: "Subtitles (.srt)", run: () => trigger(r.srt_url as string) } : undefined });
    (r.notes || []).forEach((n) => toast({ text: n, tone: "info" }));
  };
  const go = async (music: "auto" | "new" | "none" = "auto") => {
    setBusy(true);
    const r = await P.act(isLeaf ? "Preparing the download" : "Joining this part", () => api.exportNode(P.pid, node.id, music)) as ExportResult | undefined;
    setBusy(false);
    if (!r) return;
    if (r.needs_music_choice) { setAsk(r); return; }
    setAsk(null);
    save(r);
  };
  const reason = clips.length === 0 ? "There are no clips here yet." : `${left} of ${clips.length} clip${clips.length === 1 ? " is" : "s are"} still to make`;
  const dialog = (
    <Dialog open={!!ask} onOpenChange={(o) => !o && setAsk(null)} wide title="Background music for this part"
      description="The part uses the same music as the final video. It has not been made yet."
      footer={ask && <>
        <Button variant="ghost" onClick={() => setAsk(null)}>Cancel</Button>
        <Button variant="outline" loading={busy} onClick={() => go("none")}>Download without music</Button>
        <Button variant="primary" loading={busy} onClick={() => go("new")}>Make the music (≈ {usd(ask.cost_usd || 0)}), then download</Button>
      </>}>
      {ask && (
        <div className="flex items-start gap-2 rounded-xl border border-line p-3 text-sm">
          <Music className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
          <div>
            <div>One track is made for the whole video (about {Math.round(ask.seconds || 0)} s, {ask.model}) and saved. It costs about <b>{usd(ask.cost_usd || 0)}</b>.</div>
            <div className="mt-1 text-muted">Every other part and the final video then reuse it for free, so you pay for the music only once.</div>
          </div>
        </div>
      )}
    </Dialog>
  );
  return { isLeaf, clips, left, busy, go, reason, dialog, ready: clips.length > 0 && left === 0 };
}

/** Saves the video of one clip or one part. Enabled when every clip under it is made. A part is its clips joined (same music as the
 *  final video, as a free slice of the saved track). If the music has not been made yet and would cost money, it asks first. */
export default function DownloadButton({ node, variant = "outline", size = "sm", label }: {
  node: Node; variant?: "outline" | "primary" | "ghost"; size?: "sm" | "md"; label?: string;
}) {
  const d = useDownload(node);
  const text = label || (d.isLeaf ? "Download clip" : "Download part");
  return (
    <>
      <HelpTip id={d.isLeaf ? "download-clip" : "download-part"}>
        <span className="inline-flex">
          {d.ready ? (
            <Button size={size} variant={variant} loading={d.busy} onClick={() => d.go("auto")}><DownloadIcon className="h-3.5 w-3.5" />{text}</Button>
          ) : (
            <Tip content={d.reason}><span><Button size={size} variant={variant} disabled><DownloadIcon className="h-3.5 w-3.5" />{text}</Button></span></Tip>
          )}
        </span>
      </HelpTip>
      {d.dialog}
    </>
  );
}
