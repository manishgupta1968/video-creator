import { Box, ExternalLink, RefreshCw, Send } from "lucide-react";
import { useState } from "react";
import { api, Ctx, fileUrl } from "../api";
import { fmtUsd, useP, useToast } from "../lib";
import { Badge, Button } from "../ui";

/** A character's or object's low-poly 3D model: built once in Blender by Claude Code / Codex from what the story says,
 *  used in every clip's 3D scene. Its look and its poses come from the plan, never from a fixed figure. */
export default function Model3DSection({ item }: { item: Ctx }) {
  const P = useP();
  const toast = useToast();
  const [text, setText] = useState("");
  const m = item.model3d;
  const label = `3D model ${item.title}`;
  const working = P.busy.includes(label) || m?.status === "building";
  if (!P.view?.project.settings.scene3d.enabled) return null;
  const views = ["three_quarter", "front", "side", "back"].filter((k) => m?.previews?.[k]);
  const poses = Object.keys(m?.previews || {}).filter((k) => k.startsWith("pose_"));
  const build = (change = "") => P.act(label, () => api.model3dBuild(P.pid, item.id, change),
    change ? "Changing the 3D model in the background" : "Building the 3D model in the background (a few minutes)");
  return (
    <div className="space-y-2 rounded-lg border border-line p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Box className="h-3.5 w-3.5 text-brand" /><span className="font-semibold">3D model</span>
        <Badge tone={m?.status === "built" ? "ok" : m?.status === "failed" ? "bad" : working ? "info" : "neutral"}>
          {working ? "Working on it" : m?.status === "built" ? `Built · ${m.height.toFixed(2)} m` : m?.status === "failed" ? "Could not be built" : "Not built yet"}
        </Badge>
        <div className="flex-1" />
        <Button size="sm" variant={m?.status === "built" ? "outline" : "primary"} disabled={working} onClick={() => build()}>
          {working ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Box className="h-3.5 w-3.5" />}{m?.status === "built" ? "Build again" : "Build the 3D model"}
        </Button>
        {m?.status === "built" && (
          <Button size="sm" variant="outline" disabled={!m.blend}
            onClick={async () => { const r = await P.act("Open in Blender", () => api.model3dOpen(P.pid, item.id)); if (r) toast({ text: (r as any).note, tone: "info" }); }}>
            <ExternalLink className="h-3.5 w-3.5" />Open in Blender
          </Button>
        )}
      </div>
      <p className="text-[11px] text-muted">
        Built once, low-poly, by Claude Code (or Codex) in Blender from what the story says, then used in every clip's 3D scene. The real look still
        comes from the pictures above.
      </p>
      {m?.brief?.description && <p className="text-[11px]"><span className="font-medium">Looks like:</span> {m.brief.description}</p>}
      {!!m?.brief?.poses?.length && (
        <p className="text-[11px]"><span className="font-medium">Poses the script needs:</span> {m.brief.poses.map((p) => p.name).join(", ")}</p>
      )}
      {views.length > 0 && (
        <div className="grid grid-cols-4 gap-1.5">
          {views.map((k) => <figure key={k}><img src={fileUrl(P.pid, m!.previews[k]) + `?v=${m!.version}`} alt={k} className="w-full rounded bg-sunken" />
            <figcaption className="text-[10px] text-muted">{k.replace("_", " ")}</figcaption></figure>)}
        </div>
      )}
      {poses.length > 0 && (
        <div className="grid grid-cols-5 gap-1.5">
          {poses.map((k) => <figure key={k}><img src={fileUrl(P.pid, m!.previews[k]) + `?v=${m!.version}`} alt={k} className="w-full rounded bg-sunken" />
            <figcaption className="text-[10px] text-muted">{k.slice(5).replace("_", " ")}</figcaption></figure>)}
        </div>
      )}
      {!!m?.missing?.length && <p className="text-[11px] text-warn">Poses still missing: {m.missing.join(", ")}</p>}
      {!!m?.issues?.length && m.status !== "built" && <ul className="text-[11px] text-bad">{m.issues.map((i) => <li key={i}>{i}</li>)}</ul>}
      {m?.status === "built" && (
        <div className="flex items-end gap-2">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} disabled={working} aria-label="Change the 3D model"
            placeholder="Change the model, e.g. give him a longer white beard · make the robe saffron"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (text.trim()) { build(text.trim()); setText(""); } } }}
            className="min-h-[2rem] flex-1 resize-y rounded-lg border border-line bg-panel px-2 py-1 text-xs" />
          <Button size="sm" variant="primary" disabled={working || !text.trim()} onClick={() => { build(text.trim()); setText(""); }}><Send className="h-3.5 w-3.5" />Change</Button>
        </div>
      )}
      {!!m?.agent_log?.length && (
        <details className="text-[11px]"><summary className="cursor-pointer text-muted">What the agent did{m.agent_cost_usd ? ` (${fmtUsd(m.agent_cost_usd)})` : ""}</summary>
          <ul className="mt-1 space-y-0.5">{m.agent_log.slice(-8).map((l, i) => <li key={i}>{l}</li>)}</ul></details>
      )}
    </div>
  );
}
