import { useQuery } from "@tanstack/react-query";
import { Box, CheckCircle2, ExternalLink, RefreshCw, Send, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { api, fileUrl, Node } from "../api";
import { fmtUsd, useP, useToast } from "../lib";
import { Badge, Button, cn, Select, Switch } from "../ui";

/* The optional "3D camera reference": a rough 3D version of a clip made of plain coloured shapes, whose camera path the
   video model follows. Off unless switched on, so nothing else changes. */

const AGENTS = [
  { value: "claude_code", label: "Claude Code fixes" },
  { value: "codex", label: "Codex fixes" },
  { value: "pair", label: "Claude Code fixes, Codex checks" },
];
const RENDERERS = [
  { value: "auto", label: "Blender when installed, else a sketch" },
  { value: "blender", label: "Blender" },
  { value: "sketch", label: "Free sketch only" },
];
const SWATCH: Record<string, string> = {
  red: "#d62828", blue: "#1f6feb", green: "#2a9d3f", yellow: "#f2c500", purple: "#8338ec", orange: "#f77f00",
  cyan: "#00b4d8", pink: "#ff5d8f", brown: "#8d5524", white: "#f5f5f5", grey: "#9a9a9a",
};

function Choice({ value, onChange, inherit }: { value: boolean | null | undefined; onChange: (v: boolean | null) => void; inherit: string }) {
  const opts: { v: boolean | null; label: string }[] = [{ v: null, label: `Same as above (${inherit})` }, { v: true, label: "On" }, { v: false, label: "Off" }];
  return (
    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="3D camera reference">
      {opts.map((o) => {
        const selected = (value ?? null) === o.v;
        return (
          <button key={String(o.v)} type="button" role="radio" aria-checked={selected} onClick={() => !selected && onChange(o.v)}
            className={cn("rounded-lg border px-2.5 py-1.5 text-xs", selected ? "border-brand bg-brand/10" : "border-line hover:border-brand/40")}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** "On this computer: Blender 4.2 ✓ (fast engine) · Claude Code ✓ · Codex not installed": what the add-on can use here. */
function ComputerStatus() {
  const q = useQuery({ queryKey: ["scene3d-status"], queryFn: () => api.scene3dStatus(), staleTime: 60_000 });
  const d = q.data;
  if (!d) return <p className="text-[11px] text-muted">On this computer: checking…</p>;
  const ok = <span className="text-ok">✓</span>;
  const b = d.blender;
  const engine = b.engine === "BLENDER_WORKBENCH" ? "fast engine" : b.engine === "CYCLES" ? "slow engine: run `vg doctor` to see how to make it faster" : "";
  const noAgent = !d.claude_code.found && !d.codex.found;
  return (
    <div className="space-y-1 rounded-lg bg-sunken px-2.5 py-1.5 text-[11px]" aria-label="What this computer can use">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span className="text-muted">On this computer:</span>
        {b.found ? <span title={b.path}>{b.version || "Blender"} {ok}{engine && <span className="text-muted"> ({engine})</span>}</span>
          : <span className="text-warn">Blender not installed: a free sketch is drawn instead (get it free at blender.org)</span>}
        <span className="text-muted">·</span>
        {d.claude_code.found ? <span title={d.claude_code.path}>Claude Code {ok}</span> : <span className="text-muted">Claude Code not installed</span>}
        <span className="text-muted">·</span>
        {d.codex.found ? <span title={d.codex.path}>Codex {ok}</span> : <span className="text-muted">Codex not installed</span>}
      </div>
      {noAgent && <div className="text-warn">No agent can fix 3D plans that fail a check. Install Claude Code (the `claude` command) or Codex, then restart the app.</div>}
    </div>
  );
}

/** For the whole video (all the settings) or for one part (on, off, or the same as the part above). */
export function Scene3DPartPanel({ node, isRoot }: { node: Node; isRoot: boolean }) {
  const P = useP();
  const st = P.view!.project.settings.scene3d;
  const saveSettings = (patch: Partial<typeof st>, ok?: string) =>
    P.act("Save", () => api.patch(P.pid, { settings: { scene3d: { ...st, ...patch } } }), ok);
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold"><Box className="h-3.5 w-3.5 text-brand" />3D camera reference</div>
      <p className="mb-2 text-[11px] text-muted">
        For shots where the camera move matters: a rough 3D version of each clip (plain coloured shapes) is made, and the video model copies its
        camera path. The looks come from your pictures. Off means the clips are made the usual way.
      </p>
      {isRoot ? (
        <div className="space-y-2">
          <ComputerStatus />
          <div><Switch checked={st.enabled} onChange={(enabled) => saveSettings({ enabled }, enabled ? "3D camera reference is on" : "3D camera reference is off")}
            label={st.enabled ? "On for the whole video" : "Off"} /></div>
          {st.enabled && (
            <>
              <div><Switch checked={st.auto_approve} onChange={(auto_approve) => saveSettings({ auto_approve })}
                label="Approve a 3D preview by itself when its checks pass (otherwise you approve each one)" /></div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">When a check fails:</span>
                <Select value={st.agent} onChange={(agent) => saveSettings({ agent: agent as any })} options={AGENTS} title="Who fixes the 3D plan" />
                <span className="text-muted">at most</span>
                <input type="number" min={0} step={0.5} defaultValue={st.agent_max_usd} aria-label="Money cap per clip"
                  onBlur={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v) && v !== st.agent_max_usd) saveSettings({ agent_max_usd: v }); }}
                  className="w-16 rounded-md border border-line bg-panel px-1.5 py-1 text-xs" />
                <span className="text-muted">$ per clip</span>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">Render with:</span>
                <Select value={st.renderer} onChange={(renderer) => saveSettings({ renderer: renderer as any })} options={RENDERERS} title="Renderer" />
                <div className="flex-1" />
                <Button size="sm" variant="outline" disabled={P.busy.includes("3D references")}
                  onClick={() => P.act("3D references", () => api.scene3dAll(P.pid), "Preparing the 3D references in the background")}>
                  <Sparkles className="h-3.5 w-3.5" />Prepare all 3D references
                </Button>
              </div>
            </>
          )}
        </div>
      ) : (
        <Choice value={node.scene3d_enabled} inherit={st.enabled ? "on" : "off"}
          onChange={(v) => P.act("Save", () => api.patchNode(P.pid, node.id, { scene3d_enabled: v }))} />
      )}
    </div>
  );
}

/** The prompt box, as in the video: describe the scene (before there is one) or say what to change. Each request is
 *  applied, checked (and fixed when needed) and rendered by itself; the new preview appears when it is ready. */
function ScenePrompt({ node, working }: { node: Node; working: boolean }) {
  const P = useP();
  const [text, setText] = useState("");
  const s = node.scene3d;
  const hasPlan = !!s?.plan;
  const label = `3D change ${P.numbers[node.id] || ""}`;
  const send = async () => {
    const request = text.trim();
    if (!request) return;
    const r = await P.act(label, () => api.scene3dChange(P.pid, node.id, request),
      hasPlan ? "Changing the 3D scene. The new preview appears when it is ready." : "Making the 3D scene from the script and your words.");
    if (r) setText("");
  };
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium">{hasPlan ? "Change the 3D scene" : "Describe the 3D scene (optional)"}</div>
      <div className="flex items-end gap-2">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} disabled={working} aria-label={hasPlan ? "Change the 3D scene" : "Describe the 3D scene"}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder={hasPlan ? "e.g. make the lizard twice as big · end the camera closer to the chef · move the rock to the left"
            : "e.g. a big empty kitchen, the chef at the far end, the camera starts high and comes down"}
          className="min-h-[2.5rem] flex-1 resize-y rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs" />
        <Button size="sm" variant="primary" disabled={working || !text.trim()} onClick={send}>
          {working ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}{hasPlan ? "Change" : "Make it"}
        </Button>
      </div>
      <p className="text-[10px] text-muted">
        {hasPlan ? "Only what you ask for changes. It is checked and rendered by itself; Undo (Ctrl/⌘ Z) takes it back."
          : "Leave it empty to make the scene from the script alone (\"Plan, check and render\" below)."}
      </p>
      {!!s?.changes?.length && (
        <details className="text-[11px]">
          <summary className="cursor-pointer text-muted">Your changes so far ({s.changes.length})</summary>
          <ol className="mt-1 list-decimal space-y-0.5 pl-4">{s.changes.map((c, i) => <li key={i}>{c}</li>)}</ol>
        </details>
      )}
    </div>
  );
}

/** For one clip: is it on, the plan's colour legend, the checks, the preview pictures and video, and the actions. */
export function Scene3DClipPanel({ node }: { node: Node }) {
  const P = useP();
  const info = useQuery({ queryKey: ["scene3d", P.pid, node.id, P.view?.project.updated_at], queryFn: () => api.scene3d(P.pid, node.id), staleTime: 0 });
  const d = info.data;
  const s = node.scene3d;
  const label = `3D reference ${P.numbers[node.id] || ""}`;
  const working = P.busy.some((b) => b === label || b.startsWith(`3D fix ${P.numbers[node.id] || ""}`) || b.startsWith(`3D change ${P.numbers[node.id] || ""}`) || b === "3D references");
  const toast = useToast();
  if (!d) return null;
  const parentOn = P.view!.project.settings.scene3d.enabled;
  if (!d.enabled && node.scene3d_enabled == null && !s) return null;      // off and never used: the panel stays out of the way
  const status = working ? "Working on it: the new preview appears when it is ready" : !s?.plan ? "No plan yet" : d.stale ? `Out of date: ${d.stale}` : s.status === "approved" ? `Approved${s.approved_by === "auto" ? " by itself" : ""}`
    : s.status === "rendered" ? "Waiting for your approval" : s.status === "failed" ? "The render failed" : "Planned, not rendered";
  const tone = working ? "info" : d.ready ? "ok" : d.stale || s?.status === "failed" ? "bad" : s?.status === "rendered" ? "warn" : "neutral";
  return (
    <div className="space-y-3 rounded-xl border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Box className="h-3.5 w-3.5 text-brand" /><span className="text-xs font-semibold">3D camera reference</span>
        <Badge tone={tone as any}>{d.enabled ? status : "Off for this clip"}</Badge>
        {d.ready && <Badge tone="ok"><CheckCircle2 className="h-3 w-3" />used when this clip is made</Badge>}
        <div className="flex-1" />
        <Choice value={node.scene3d_enabled} inherit={parentOn ? "on" : "off"}
          onChange={(v) => P.act("Save", () => api.patchNode(P.pid, node.id, { scene3d_enabled: v }))} />
      </div>
      {d.enabled && (
        <>
          {d.legend.length > 0 && (
            <div className="flex flex-wrap gap-1.5 text-[11px]">
              {d.legend.map((l) => (
                <span key={l.colour + l.is} className="inline-flex items-center gap-1 rounded-md bg-sunken px-1.5 py-0.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SWATCH[l.colour] || "#999" }} />{l.colour} = {l.is}
                </span>
              ))}
              {s?.plan?.camera?.move && <span className="text-muted">· camera: {s.plan.camera.move}</span>}
            </div>
          )}
          {d.issues.length > 0 && (
            <ul className="space-y-0.5 text-[11px]">
              {d.issues.map((i) => <li key={i} className={i.startsWith("major") ? "text-bad" : "text-warn"}>{i}</li>)}
            </ul>
          )}
          <ScenePrompt node={node} working={working} />
          {s?.video && !d.stale && (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
              <video key={s.video} src={fileUrl(P.pid, s.video)} controls loop muted className="w-full rounded bg-black sm:col-span-1" />
              {(["start", "middle", "end"] as const).map((k) => s.checks?.[k] && (
                <figure key={k}><img src={fileUrl(P.pid, s.checks[k])} alt={`3D preview, ${k}`} className="w-full rounded" />
                  <figcaption className="mt-0.5 text-[10px] text-muted">{k}</figcaption></figure>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant={s?.video && !d.stale ? "outline" : "primary"} disabled={working}
              onClick={() => P.act(label, () => api.scene3dBuild(P.pid, node.id, {}), "Making the 3D reference in the background")}>
              {working ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Box className="h-3.5 w-3.5" />}
              {s?.video && !d.stale ? "Render again" : s?.plan ? "Check and render" : "Plan, check and render"}
            </Button>
            {s?.plan && (
              <Button size="sm" variant="ghost" disabled={working}
                onClick={() => P.act(label, () => api.scene3dBuild(P.pid, node.id, { replan: true }), "Planning the 3D scene again in the background")}>
                Plan again
              </Button>
            )}
            {s?.plan && (
              <Button size="sm" variant="ghost" disabled={working || !d.agents.builder} title={d.agents.notes.join(" ") || undefined}
                onClick={() => P.act(`3D fix ${P.numbers[node.id] || ""}`, () => api.scene3dFix(P.pid, node.id), `${d.agents.builder} is fixing the 3D plan`)}>
                <Wand2 className="h-3.5 w-3.5" />Fix with {d.agents.builder === "codex" ? "Codex" : "Claude Code"}{d.agents.checker ? " + Codex check" : ""}
              </Button>
            )}
            {s?.plan && (
              <Button size="sm" variant="outline" disabled={!s.blend}
                title={s.blend ? "Open this scene in your own Blender, looking through the camera" : "Drawn as a free sketch: there is no Blender scene to open"}
                onClick={async () => {
                  const r = await P.act("Open in Blender", () => api.scene3dOpen(P.pid, node.id));
                  if (r) toast({ text: (r as any).note, tone: "info" });
                }}>
                <ExternalLink className="h-3.5 w-3.5" />Open in Blender
              </Button>
            )}
            {s?.status === "rendered" && !d.stale && (
              <Button size="sm" variant="primary" onClick={() => P.act("Approve", () => api.scene3dApprove(P.pid, node.id), "3D preview approved")}>
                <CheckCircle2 className="h-3.5 w-3.5" />Approve this preview
              </Button>
            )}
            <span className="text-[11px] text-muted">
              {d.renderer === "sketch" ? "Drawn as a free sketch" : `Blender (${d.renderer.replace("BLENDER_", "").toLowerCase()})`}
              {s?.agent_rounds ? ` · agent: ${s.agent_rounds} round(s), ${fmtUsd(s.agent_cost_usd)}` : ""}
            </span>
          </div>
          {d.agents.notes.length > 0 && <p className="text-[11px] text-muted">{d.agents.notes.join(" ")}</p>}
          {!!s?.notes?.length && <p className="text-[11px] text-muted">{s.notes.join(" ")}</p>}
          {!!s?.agent_log?.length && (
            <details className="text-[11px]">
              <summary className="cursor-pointer text-muted">What the agent did</summary>
              <ul className="mt-1 space-y-0.5">{s.agent_log.slice(-8).map((l, i) => <li key={i}>{l}</li>)}</ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
