import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Box, CheckCircle2, ExternalLink, Film, RefreshCw, Send, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { api, fileUrl, Node } from "../api";
import { fmtUsd, useP, useToast } from "../lib";
import { Badge, Button, cn, Select, Switch } from "../ui";
import { EffortSelect, SubscriptionModelSelect } from "./SubscriptionModel";

/* The optional "3D camera reference": a rough 3D version of a clip made of plain coloured shapes, whose camera path the
   video model follows. Off unless switched on, so nothing else changes. */

const AGENTS = [
  { value: "brain", label: "The same tool as the AI brain fixes" },
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

/** The whole 3D film: every clip's 3D preview joined in story order, to watch here or in Blender before paying anything. */
function WholeFilm() {
  const P = useP();
  const toast = useToast();
  const q = useQuery({ queryKey: ["scene3d-film", P.pid, P.view?.project.updated_at], queryFn: () => api.scene3dFilm(P.pid), staleTime: 0, placeholderData: keepPreviousData });
  const working = P.busy.includes("Whole 3D film");
  const f = q.data?.film;
  const stale = q.data?.stale || "";
  const has = !!f?.video;
  return (
    <div className="space-y-2 rounded-lg border border-line p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Film className="h-3.5 w-3.5 text-brand" /><span className="text-xs font-semibold">Whole 3D film</span>
        {has && <Badge tone={working ? "info" : stale ? "warn" : "ok"}>{working ? "Working on it" : stale ? `Out of date: ${stale}` : `${f!.seconds.toFixed(0)} s, up to date`}</Badge>}
        <div className="flex-1" />
        <Button size="sm" variant={has && !stale ? "outline" : "primary"} disabled={working}
          title={has && !stale ? "Every clip's preview is up to date, so this only joins them again (a second). Use the box below to change the film." : "Makes the missing or out-of-date previews, then joins them all"}
          onClick={() => P.act("Whole 3D film", () => api.scene3dMakeFilm(P.pid), has && !stale ? "Joining the 3D film again" : "Making the missing 3D previews and joining them, in the background")}>
          {working ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}{!has ? "Make the whole 3D film" : stale ? "Update the film" : "Join again"}
        </Button>
        {has && (
          <Button size="sm" variant="outline" disabled={working} title="Plans every clip's 3D scene afresh from its script, then renders and joins them (takes minutes)"
            onClick={() => {
              if (!window.confirm("Plan every 3D scene again from the scripts?\n\nEach clip gets a new layout and camera, then is rendered again. It takes a few minutes and uses your AI brain. Changes you asked for in single clips are replaced. One Undo (Ctrl/⌘ Z) brings the old scenes back.")) return;
              P.act("Whole 3D film", () => api.scene3dMakeFilm(P.pid, true), "Planning every 3D scene again, then rendering and joining them, in the background");
            }}>
            <Sparkles className="h-3.5 w-3.5" />Plan every scene again
          </Button>
        )}
        {has && (
          <Button size="sm" variant="outline" disabled={!f!.blend} title={f!.blend ? "Watch it in your own Blender's video editor" : "Made without Blender: no Blender file"}
            onClick={async () => { const r = await P.act("Open in Blender", () => api.scene3dOpenFilm(P.pid)); if (r) toast({ text: (r as any).note, tone: "info" }); }}>
            <ExternalLink className="h-3.5 w-3.5" />Open the whole film in Blender
          </Button>
        )}
      </div>
      <AskHistory />
      <p className="text-[11px] text-muted">
        Every clip's 3D preview, one after another, before anything is paid for. Missing previews are made first (free); a clip without one shows a
        card of the same length saying why.
      </p>
      {has && (
        <>
          <video key={f!.video! + f!.updated_at} src={fileUrl(P.pid, f!.video)} controls className="w-full max-w-xl rounded bg-black" />
          <div className="flex flex-wrap gap-1.5 text-[11px]">
            {f!.parts.map((pt) => (
              <span key={pt.nid} title={pt.why || "3D preview"} className={cn("rounded-md px-1.5 py-0.5", pt.source === "card" ? "bg-warn/15 text-warn" : "bg-sunken")}>
                {pt.number} · {pt.source === "3d" ? "3D" : pt.source === "footage" ? "your video" : pt.why}
              </span>
            ))}
          </div>
          {f!.notes.map((n) => <p key={n} className="text-[11px] text-muted">{n}</p>)}
        </>
      )}
    </div>
  );
}

/** Your "Ask AI" requests this session and what came of them. The agents read the same list (history.md), so a new
 *  request never undoes an earlier one. */
function AskHistory() {
  const P = useP();
  const asks = P.view!.project.ask_history || [];
  return (
    <div className="space-y-1">
      <div className="text-[11px]">
        <span className="font-medium">To change the film, type in “Ask AI to change this…” at the top.</span>{" "}
        <span className="text-muted">The AI decides whether it is for the story or the 3D scenes, and which clips it affects.</span>
      </div>
      {asks.length > 0 && (
        <details className="text-[11px]" open={asks.length <= 3}>
          <summary className="cursor-pointer text-muted">Your requests this session ({asks.length}) — Claude Code / Codex read these each time</summary>
          <ol className="mt-1 space-y-0.5 pl-4">
            {asks.slice(-12).map((a, i) => (
              <li key={a.at + i} className="list-decimal"><span className="text-muted">{a.where}:</span> {a.request}
                {a.result && <span className="text-muted"> → {a.result}</span>}</li>
            ))}
          </ol>
        </details>
      )}
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
                <span className="text-muted">Model and reasoning for 3D work (“its usual” = as chosen in Settings → AI brain):</span>
                <span>Claude Code</span>
                <SubscriptionModelSelect which="claude_code" value={st.agent_models?.claude_code || ""} title="The model Claude Code uses to build characters, fix and change 3D scenes"
                  onChange={(v) => saveSettings({ agent_models: { ...(st.agent_models || {}), claude_code: v } })} />
                <EffortSelect which="claude_code" model={st.agent_models?.claude_code || ""} value={st.agent_efforts?.claude_code || ""} usualLabel="effort as for the AI brain"
                  onChange={(v) => saveSettings({ agent_efforts: { ...(st.agent_efforts || {}), claude_code: v } })} />
                <span>Codex</span>
                <SubscriptionModelSelect which="codex" value={st.agent_models?.codex || ""} title="The model Codex uses to build characters, fix and change 3D scenes"
                  onChange={(v) => saveSettings({ agent_models: { ...(st.agent_models || {}), codex: v } })} />
                <EffortSelect which="codex" model={st.agent_models?.codex || ""} value={st.agent_efforts?.codex || ""} usualLabel="effort as for the AI brain"
                  onChange={(v) => saveSettings({ agent_efforts: { ...(st.agent_efforts || {}), codex: v } })} />
              </div>
              <div className="space-y-1 rounded-lg border border-line p-2">
                <Switch checked={!!st.ai_check} onChange={(ai_check) => saveSettings({ ai_check }, ai_check ? "The AI checker is on" : "The AI checker is off")}
                  label="AI checker: after each render, Claude Code or Codex writes success criteria, looks at the rendered preview and gives the builder feedback to fix" />
                {st.ai_check && (
                  <div className="flex flex-wrap items-center gap-2 pl-1 text-xs">
                    <span className="text-muted">Rounds of check and fix per clip:</span>
                    <input type="number" min={1} max={10} step={1} defaultValue={st.check_rounds || 3} aria-label="Rounds of check and fix"
                      onBlur={(e) => { const v = Math.max(1, Math.min(10, parseInt(e.target.value) || 1)); if (v !== st.check_rounds) saveSettings({ check_rounds: v }); }}
                      className="w-14 rounded-md border border-line bg-panel px-1.5 py-1 text-xs" />
                    <span className="text-muted">· checker: {st.agent === "pair" ? "the other tool (pair mode)" : "the same tool as the builder, in its own run"} · uses your subscription</span>
                  </div>
                )}
              </div>
              <div><Switch checked={st.models !== false} onChange={(models) => saveSettings({ models })}
                label="Build a low-poly 3D model of each character and object (else plain shapes)" /></div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">Render with:</span>
                <Select value={st.renderer} onChange={(renderer) => saveSettings({ renderer: renderer as any })} options={RENDERERS} title="Renderer" />
                <div className="flex-1" />
                <Button size="sm" variant="outline" disabled={P.busy.includes("3D references")}
                  onClick={() => P.act("3D references", () => api.scene3dAll(P.pid), "Preparing the 3D references in the background")}>
                  <Sparkles className="h-3.5 w-3.5" />Prepare all 3D references
                </Button>
              </div>
              <WholeFilm />
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

const name = (tool?: string | null) => (tool === "codex" ? "Codex" : tool === "claude_code" ? "Claude Code" : tool === "fake_agent" ? "the test agent" : "AI");

/** The AI checker on this clip: its success criteria (met or not), each round's feedback to the builder, and why it
 *  stopped. Changes are asked for in the "Ask AI to change this…" box at the top of the clip. */
function ClipCheck({ node, working, tool, checker, notes }: { node: Node; working: boolean; tool?: string | null; checker?: string | null; notes?: string[] }) {
  const P = useP();
  const s = node.scene3d;
  const st = P.view!.project.settings.scene3d;
  const rv = s?.review;
  const last = rv?.rounds?.[rv.rounds.length - 1];
  const checking = P.busy.some((b) => b.startsWith(`3D check ${P.numbers[node.id] || ""}`));
  return (
    <div className="space-y-1.5 text-[11px]">
      <div className="text-muted">To describe or change this 3D scene, type in “Ask AI to change this…” at the top of the clip.</div>
      {!!s?.changes?.length && (
        <details>
          <summary className="cursor-pointer text-muted">Changes to this scene so far ({s.changes.length})</summary>
          <ol className="mt-1 list-decimal space-y-0.5 pl-4">{s.changes.map((c, i) => <li key={i}>{c}</li>)}</ol>
        </details>
      )}
      <div className="rounded-lg border border-line p-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">AI check of the rendered preview</span>
          {rv && rv.rounds.length > 0 && <Badge tone={rv.passed ? "ok" : "warn"}>{rv.passed ? `Passed in round ${last!.round}` : `Not passed (${rv.rounds.length} round${rv.rounds.length > 1 ? "s" : ""})`}</Badge>}
          {checking && <Badge tone="info">Checking…</Badge>}
          <div className="flex-1" />
          <Button size="sm" variant="primary" disabled={working || checking || !s?.plan || !tool}
            title={tool ? `${name(checker || tool)} writes success criteria and looks at the rendered frames; ${name(tool)} fixes what fails; it is rendered and checked again — up to ${st.check_rounds || 3} round(s)` : (notes || []).join(" ")}
            onClick={() => P.act(`3D check ${P.numbers[node.id] || ""}`, () => api.scene3dFix(P.pid, node.id), `${name(tool)} is checking the rendered preview and fixing what fails, in the background (a few minutes)`)}>
            <Wand2 className="h-3.5 w-3.5" />Check and fix with {name(tool)}{checker && checker !== tool ? ` + ${name(checker)} checks` : ""}
          </Button>
        </div>
        {!rv && <p className="mt-1 text-muted">{!tool ? "Install Claude Code or Codex to use the AI checker." : st.ai_check ? "It runs by itself after each render, or click the button." : "Click the button, or switch on the AI checker in the Whole video box to run it after each render."}</p>}
        {rv && rv.criteria.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {rv.criteria.map((c) => {
              const r = last?.results.find((x) => x.criterion === c);
              return <li key={c} className={r ? (r.met ? "text-ok" : "text-bad") : "text-muted"}>{r ? (r.met ? "✓ " : "✗ ") : "• "}{c}{r && !r.met && r.why ? <span className="text-muted"> — {r.why}</span> : null}</li>;
            })}
          </ul>
        )}
        {rv && rv.rounds.length > 0 && (
          <details className="mt-1">
            <summary className="cursor-pointer text-muted">Each round: the checker's feedback and the builder's fix</summary>
            <ol className="mt-1 space-y-1 pl-4">
              {rv.rounds.map((r) => (
                <li key={r.round} className="list-decimal">
                  <span className={r.ok ? "text-ok" : "text-warn"}>{r.ok ? "Passed" : "Not passed"}</span> <span className="text-muted">({r.checked_by})</span>
                  {r.feedback.map((f) => <div key={f}>→ {f}</div>)}
                  {r.fixed_by && <div className="text-muted">Fixed by {r.fixed_by}: {r.fix_summary}</div>}
                </li>
              ))}
            </ol>
          </details>
        )}
        {rv?.note && <p className="mt-1 text-muted">{rv.note}</p>}
      </div>
    </div>
  );
}

/** For one clip: is it on, the plan's colour legend, the checks, the preview pictures and video, and the actions. */
export function Scene3DClipPanel({ node }: { node: Node }) {
  const P = useP();
  const info = useQuery({ queryKey: ["scene3d", P.pid, node.id, P.view?.project.updated_at], queryFn: () => api.scene3d(P.pid, node.id), staleTime: 0, placeholderData: keepPreviousData });
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
          {d.uses.length > 0 && (
            <div className="text-[11px]"><span className="font-medium">Used when this clip is made: </span>
              <span className="text-muted">{d.uses.join(" · ")}</span></div>
          )}
          <ClipCheck node={node} working={working} tool={d.agents.builder} checker={d.agents.checker} notes={d.agents.notes} />
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
