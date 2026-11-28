import { useQuery } from "@tanstack/react-query";
import { Image as ImageIcon, RefreshCw, Send } from "lucide-react";
import { api, Ctx, fileUrl } from "../api";
import { fmtUsd, useDraft, useP, useToast, withPaidOK } from "../lib";
import { Button } from "../ui";

/** A picture of a character or object, made for you: by Codex with your ChatGPT subscription when it is installed
 *  (Claude Code cannot make pictures), else by the picture service you connected. A character's picture becomes its
 *  look in every clip, and the picture Seedance is given. Change it in plain words. */
const BRAIN: Record<string, string> = { claude_code_brain: "Claude Code", codex_brain: "Codex", anthropic: "Claude (API)", openai: "OpenAI (API)", gemini: "Gemini (API)", fake_llm: "the offline brain" };

export default function PictureSection({ item }: { item: Ctx }) {
  const P = useP();
  const maker = useQuery({ queryKey: ["picture-maker"], queryFn: api.pictureMaker, staleTime: 60_000 });
  const [text, setText] = useDraft(`picture:${P.pid}:${item.id}`);
  const label = `Picture ${item.title}`;
  const working = P.busy.includes(label);
  const m = maker.data;
  const pic = item.picture;
  const cost = !m?.name ? "" : m.subscription ? "your subscription, no per-picture cost" : `about ${fmtUsd(m.price)} a picture`;
  const toast = useToast();
  const make = async (change = "") => {
    const r = await P.act(label, () => withPaidOK((ok) => api.makePicture(P.pid, item.id, change, ok)));
    if (r && !r.needs_confirm) toast({ text: `${change ? "Changing" : "Making"} the picture in the background (about a minute) — ${r.using || m?.name || ""}`, tone: "ok" });
    return r;
  };
  return (
    <div className="space-y-2 rounded-lg border border-line p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <ImageIcon className="h-3.5 w-3.5 text-brand" /><span className="font-semibold">Picture</span>
        <span className="text-muted">{item.type === "actor" ? "the look used in every clip and given to the video model" : item.type === "location" ? "how this place looks in every clip (no people)" : "how this object looks in every clip"}</span>
        <div className="flex-1" />
        <Button size="sm" variant={pic ? "outline" : "primary"} disabled={working || !m?.name} title={m?.why || cost}
          onClick={() => make()}>
          {working ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <ImageIcon className="h-3.5 w-3.5" />}
          {m?.name ? `${pic ? "Make again" : "Make a picture"} with ${m.name}` : "Make a picture"}
        </Button>
      </div>
      {m && !m.name && <p className="text-warn">{m.why}</p>}
      {m?.name && !pic && <p className="text-muted">{m.brain_name} writes the description from this card and the story{item.files.length ? " (and its photos)" : ""}; {m.name} draws it — {cost}.{m.note ? ` ${m.note}` : ""}</p>}
      {pic && (
        <div className="flex flex-wrap items-start gap-3">
          <img key={pic.file} src={fileUrl(P.pid, pic.file)} alt={`Picture of ${item.title}`} className="h-40 rounded-lg border border-line" />
          <div className="min-w-[12rem] flex-1 space-y-1.5">
            <div className="flex items-end gap-2">
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} disabled={working} aria-label={`Change the picture of ${item.title}`}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && text.trim()) { e.preventDefault(); make(text.trim()).then((r) => r && setText("")); } }}
                placeholder={item.type === "location" ? "e.g. more mud houses · a bigger banyan tree · evening light" : "e.g. a longer white beard · a darker saffron kurta · older, with thinner hair"}
                className="min-h-[2.5rem] flex-1 resize-y rounded-lg border border-line bg-panel px-2 py-1.5 text-xs" />
              <Button size="sm" variant="primary" disabled={working || !text.trim()} onClick={() => make(text.trim()).then((r) => r && setText(""))}>
                <Send className="h-3.5 w-3.5" />Change
              </Button>
            </div>
            <p className="text-[10px] text-muted">Only what you ask for changes; the current picture is the starting point. {pic.described_by ? `Described by ${BRAIN[pic.described_by] || pic.described_by}, drawn` : "Drawn"} by {pic.by === "codex_image_subscription" ? "Codex (your subscription)" : pic.by}.</p>
            {pic.changes.length > 0 && <p className="text-[10px] text-muted">Changes so far: {pic.changes.join(" · ")}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
