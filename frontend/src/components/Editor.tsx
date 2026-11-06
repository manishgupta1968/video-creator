import { AlertTriangle, ArrowRight, Check, CheckCircle2, Clapperboard, Film, Link2, Lock, LockOpen, Mic, Play, Plus, RefreshCw, Sparkles, Trash2, User, Wand2, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { api, fileUrl, Line, Node, Review, Script, Take } from "../api";
import { fmtRange, fmtSec, fmtTime, fmtUsd, leaves, SHOT_TYPES, STATUS, useP, useSettings } from "../lib";
import { Badge, Button, Card, cn, Dialog, Editable, Empty, HelpTip, Select, Switch, Textarea, Tip } from "../ui";
import { useRun } from "./ConfirmRun";
import DownloadButton from "./Download";
import ModelPicker from "./ModelPicker";
import QualityForPart from "./QualityForPart";
import { OptimizeButton } from "./OptimizeDialog";
import { useQuery } from "@tanstack/react-query";
import { FinalVideoDialog, PreviewBadge } from "./Banners";
import { commandBus, finalPlayer } from "../lib";

export default function Editor({ node }: { node: Node }) {
  const P = useP();
  const isRoot = node.id === P.view!.project.root.id;
  return (
    <div className="mx-auto max-w-[860px] px-6 py-5">
      {node.kind === "goal" || isRoot ? <GoalEditor node={node} isRoot={isRoot} /> : <ClipEditor node={node} />}
    </div>
  );
}

// ======================================================================= goal node
function GoalEditor({ node, isRoot }: { node: Node; isRoot: boolean }) {
  const P = useP();
  const run = useRun();
  const p = P.view!.project;
  const save = (patch: any) => (isRoot ? P.act("Save", () => api.patch(P.pid, patch.goal !== undefined ? { goal: patch.goal } : patch.title !== undefined ? { name: patch.title } : { settings: { target_seconds: patch.target_seconds } }))
    : P.act("Save", () => api.patchNode(P.pid, node.id, patch)));
  const clipsBelow = useMemo(() => {
    const out: Node[] = [];
    const w = (n: Node) => { if (n.kind !== "goal") out.push(n); n.children.forEach(w); };
    w(node);
    return out;
  }, [node]);
  const unscripted = clipsBelow.filter((c) => c.kind === "clip" && !c.script).length;
  const sum = P.view!.summary;
  const breaking = P.busy.includes("Breaking down");
  const [goalEdited, setGoalEdited] = useState(false);
  return (
    <div className="space-y-5">
      <div>
        <div className="field-label mb-1">{isRoot ? "Whole video" : `Part ${P.numbers[node.id]}`}</div>
        <Editable value={isRoot ? p.name : node.title} onSave={(title) => save({ title })} className="text-xl font-semibold" ariaLabel="Title" />
      </div>
      <Card className="p-4">
        <div className="field-label mb-1">Goal</div>
        <Editable value={isRoot ? p.goal : node.goal} onSave={(goal) => { setGoalEdited(true); return save({ goal }); }} multiline placeholder="What should this part achieve?" className="text-[14px]" />
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
          <LengthEditor node={node} onSave={(v) => save({ target_seconds: v })} isRoot={isRoot} />
          <span className="text-muted">Cost {fmtRange(node.cost.min_usd, node.cost.max_usd)}</span>
          <span className="text-muted">· ~{fmtTime(node.time.likely_s)} to make</span>
        </div>
      </Card>
      {goalEdited && clipsBelow.some((c) => c.kind === "clip" && c.script) && <RewriteOffer node={node} onDone={() => setGoalEdited(false)} />}
      <QualityForPart node={node} isRoot={isRoot} />
      {isRoot && p.music_advice && (
        <Card className="flex flex-wrap items-center gap-3 p-3 text-xs">
          <div className="min-w-0 flex-1"><span className="font-semibold">Music suggestion from the plan:</span> <span className="text-muted">{p.music_advice}</span></div>
          {!p.settings.music && !/^none/i.test(p.music_advice) && (
            <Button size="sm" variant="outline" onClick={() => P.act("Save", () => api.patch(P.pid, { settings: { music: true } }), "Background music is on")}>Turn music on</Button>
          )}
        </Card>
      )}
      {isRoot && sum.final_ready && (
        <Card data-help="final-card" className="overflow-hidden">
          <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
            <div className="text-sm font-semibold">Final video</div>
            {sum.final_stale ? <Badge tone="warn">Out of date — something changed since it was made</Badge> : <Badge tone="ok">Up to date</Badge>}
            <div className="flex-1" />
            <Button size="sm" variant="outline" onClick={() => finalPlayer.open()}>Open</Button>
            <a href={fileUrl(P.pid, p.final_output)} download><Button size="sm" variant="primary">Download</Button></a>
          </div>
          <video key={p.final_output || ""} src={fileUrl(P.pid, p.final_output)} controls preload="metadata" className="aspect-video w-full bg-black" />
          <div className="px-4 py-2 text-[11px] text-muted">The clips were joined with transitions, music and subtitles. When you change a clip, use “Update final video” in the bottom bar.</div>
        </Card>
      )}
      <NodeReview node={node} />
      <AskAI node={node} placeholder={isRoot ? "e.g. make the whole video more emotional" : "e.g. make this part shorter and punchier"} />
      <div className="flex flex-wrap gap-2">
        <Button help="break-down" variant="primary" loading={breaking} onClick={() => P.act("Breaking down", () => api.decompose(P.pid, node.id), "Broken down into clips")}>
          <Sparkles className="h-3.5 w-3.5" />Break down with AI
        </Button>
        {unscripted > 0 && <Button help="write-scripts" onClick={() => P.act("Writing scripts", () => api.writeScripts(P.pid, node.id), "Scripts written")} loading={P.busy.includes("Writing scripts")}>
          <Wand2 className="h-3.5 w-3.5" />Write {unscripted} missing script(s)</Button>}
        {clipsBelow.length > 0 && <Button help="generate-part" onClick={() => run({ mode: "clip", targets: clipsBelow.filter((c) => c.status !== "done").map((c) => c.id), title: `Make the clips in ${isRoot ? "the video" : `part ${P.numbers[node.id]}`}` })}>
          <Play className="h-3.5 w-3.5" />Generate this part</Button>}
        {!isRoot && clipsBelow.length > 0 && <DownloadButton node={node} />}
        {clipsBelow.some((c) => c.kind === "clip" && c.script) && <OptimizeButton scope={node.id} label={isRoot ? "Optimize the video…" : "Optimize this part…"} />}
      </div>
      <div>
        <div className="field-label mb-2">Inside ({node.children.length})</div>
        {node.children.length === 0 ? (
          <Empty title="Nothing inside yet" icon={<Clapperboard className="h-6 w-6" />}>Break it down with AI, or add clips from the story panel.</Empty>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {node.children.map((c) => (
              <Card key={c.id} className="cursor-pointer p-3 hover:border-brand/40" onClick={() => P.select(c.id)}>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-medium text-muted">{P.numbers[c.id]}</span>
                  <span className="flex-1 truncate font-medium">{c.title}</span>
                  {c.kind !== "goal" && <Badge tone={STATUS[c.status].tone}>{STATUS[c.status].label}</Badge>}
                </div>
                <div className="mt-1 line-clamp-2 text-xs text-muted">{c.script?.visual || c.goal}</div>
                <div className="mt-1.5 text-[11px] text-muted">~{fmtSec(c.duration.likely_s)} · {fmtRange(c.cost.min_usd, c.cost.max_usd)}</div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** The Review Agent's opinion of a joined part (or the whole video). It only suggests. */
function NodeReview({ node }: { node: Node }) {
  const P = useP();
  const p = P.view!.project;
  const isRoot = node.id === p.root.id;
  const review = p.reviews.find((r) => r.target === node.id);
  if (!review) return null;
  const stale = isRoot && P.view!.summary.final_stale;
  return (
    <Card className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Sparkles className="h-4 w-4 text-brand" />
        <span className="text-sm font-semibold">Review Agent — {isRoot ? "the whole video" : "this part"}</span>
        {verdictBadge(review)}
        {stale && <Badge tone="warn">older than your latest changes</Badge>}
        <span className="ml-auto text-[11px] text-muted">{review.reviewer_model} · {fmtUsd(review.cost_usd)} · suggestions only; you decide</span>
      </div>
      {review.summary && <p className="text-xs">{review.summary}</p>}
      <div className="mt-2 grid grid-cols-4 gap-x-4 gap-y-1.5">
        {Object.entries(review.scores).map(([k, v]) => (
          <div key={k} className="text-[11px]">
            <div className="flex justify-between"><span className="capitalize text-muted">{k}</span><span className="font-medium">{v}/5</span></div>
            <div className="mt-0.5 h-1 rounded-full bg-line"><div className={cn("h-full rounded-full", v >= 4 ? "bg-ok" : v >= 3 ? "bg-warn" : "bg-bad")} style={{ width: `${v * 20}%` }} /></div>
          </div>
        ))}
      </div>
      {review.issues.length > 0 && (
        <ul className="mt-3 space-y-1">
          {review.issues.map((iss, i) => (
            <li key={i} className="flex items-start gap-2 text-xs">
              <span className={cn("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", iss.severity === "major" ? "bg-bad" : "bg-warn")} />
              <span><span className="font-medium capitalize">{iss.check}:</span> {iss.text}</span>
            </li>
          ))}
        </ul>
      )}
      {review.suggestions.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <div className="field-label">Suggestions</div>
          {review.suggestions.map((sg) => (
            <div key={sg.id} className="flex items-start gap-2 rounded-lg bg-sunken/60 px-2.5 py-1.5 text-xs">
              <span className="flex-1">{sg.text}</span>
              <Button help="apply-with-ai" size="sm" variant="outline" onClick={() => commandBus.open(sg.text)}>Apply with Ask AI</Button>
            </div>
          ))}
          <div className="text-[11px] text-muted">“Apply with Ask AI” shows you exactly what would change before anything is edited.</div>
        </div>
      )}
    </Card>
  );
}

/** After you edit a goal: offers (never forces) to update the clip scripts under it to match. Clips already made or kept are left alone. Shows the AI cost first. */
function RewriteOffer({ node, onDone }: { node: Node; onDone: () => void }) {
  const P = useP();
  const q = useQuery({ queryKey: ["rewrite-offer", P.pid, node.id, node.goal], queryFn: () => api.rewriteOffer(P.pid, node.id), staleTime: 0 });
  const d = q.data;
  if (d && d.clips === 0) return null;
  return (
    <Card className="flex flex-wrap items-center gap-3 border-brand/40 bg-brand/5 p-3 text-xs">
      <Sparkles className="h-4 w-4 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">You changed the goal. Update the clip scripts to match?</div>
        <div className="text-muted">
          {d ? `The AI rewrites ${d.clips} clip script${d.clips > 1 ? "s" : ""} (${d.numbers.join(", ")}) for about ${fmtUsd(d.cost_usd)}.` : "Working out the cost…"}
          {d && d.kept.length > 0 ? ` Clips ${d.kept.join(", ")} are made or kept, so they are left as they are.` : ""} Lines marked “say exactly this” are never changed.
        </div>
      </div>
      <Button size="sm" variant="primary" disabled={!d} loading={P.busy.includes("Rewriting scripts")}
        onClick={async () => { await P.act("Rewriting scripts", () => api.writeScripts(P.pid, node.id, true), "Scripts updated. Ctrl+Z undoes it."); onDone(); }}>Update the scripts</Button>
      <Button size="sm" variant="ghost" onClick={onDone}>Not now</Button>
    </Card>
  );
}

function LengthEditor({ node, onSave, isRoot }: { node: Node; onSave: (v: number | null) => void; isRoot?: boolean }) {
  const P = useP();
  const target = isRoot ? P.view!.project.settings.target_seconds : node.target_seconds;
  return (
    <Tip content={<span>Estimate: {node.duration.explain}<br />Range {fmtSec(node.duration.min_s)}–{fmtSec(node.duration.max_s)} ({node.duration.basis === "goal" ? "from the goal" : node.duration.basis === "script" ? "from the script" : "real length"})</span>}>
      <span className="inline-flex items-center gap-1.5">
        <span className="font-medium">~{fmtSec(node.duration.likely_s)}</span>
        <span className="text-muted">target</span>
        <input data-help="target-seconds" aria-label="Target seconds" type="number" min={1} defaultValue={target ?? ""} placeholder="auto" key={String(target)}
          onBlur={(e) => { const v = e.target.value ? Number(e.target.value) : null; if (v !== target) onSave(v); }}
          className="h-6 w-16 rounded-md border border-line bg-panel px-1.5 text-xs" />
        <span className="text-muted">s</span>
      </span>
    </Tip>
  );
}

function AskAI({ node, placeholder }: { node: Node; placeholder: string }) {
  const P = useP();
  const [text, setText] = useState("");
  const busy = P.busy.includes("Revising");
  const send = async () => {
    if (!text.trim()) return;
    const r = await P.act("Revising", () => api.revise(P.pid, node.id, text.trim()), "Revised — Ctrl+Z to undo");
    if (r) setText("");
  };
  return (
    <div data-help="ask-ai-box" className="flex items-center gap-2 rounded-xl border border-line bg-panel px-3 py-1.5 focus-within:border-brand">
      <Sparkles className="h-4 w-4 shrink-0 text-brand" />
      <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
        placeholder={`Ask AI to change this — ${placeholder}`} aria-label="Ask AI"
        className="h-8 flex-1 bg-transparent text-[13px] placeholder:text-muted/70 focus:outline-none" />
      <Button size="sm" variant="primary" onClick={send} loading={busy} disabled={!text.trim()}><ArrowRight className="h-3.5 w-3.5" /></Button>
    </div>
  );
}

// ======================================================================= clip node
function ClipEditor({ node }: { node: Node }) {
  const P = useP();
  const run = useRun();
  const p = P.view!.project;
  const settings = useSettings();
  const s = node.script;
  const st = STATUS[node.status];
  const actors = p.context.filter((c) => c.type === "actor");
  const saveScript = (patch: Partial<Script>) => P.act("Save", () => api.patchNode(P.pid, node.id, { script: patch }));
  const saveNode = (patch: any) => P.act("Save", () => api.patchNode(P.pid, node.id, patch));
  const beforeDep = P.view!.project.dependencies.find((d) => d.to_id === node.id && d.type === "continues_from");
  const before = beforeDep ? leaves(P.view!.project).find((l) => l.id === beforeDep.from_id) : undefined;
  const versionTakes = node.takes.filter((t) => t.version === node.version);
  const shownTakes = versionTakes.length ? versionTakes : node.takes;
  const chosen = node.takes.find((t) => t.id === node.chosen_take);
  const autoRow = (settings.data?.catalog || []).find((e: any) => e.id === node.cost.model);
  const generating = node.status === "generating";
  const liveStep = (P.view!.engine.activity || []).find((a) => a.node === node.id);

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="field-label mb-0.5 flex items-center gap-2">Clip {P.numbers[node.id]}
            {node.kind !== "clip" && <Badge>{node.kind === "slides" ? "Your slides" : "Your video"}</Badge>}
            {node.version > 1 && <Badge tone="info">v{node.version}</Badge>}
            <PreviewBadge nodeId={node.id} />
          </div>
          <Editable value={node.title} onSave={(title) => saveNode({ title })} className="text-xl font-semibold" ariaLabel="Clip title" />
        </div>
        <div className="mt-4 flex items-center gap-2">
          {node.status === "done" && <DownloadButton node={node} />}
          <Badge tone={st.tone}>{st.icon}{st.label}</Badge>
        </div>
      </div>

      {node.blocked && node.status !== "done" && (
        <Card className="space-y-2 border-bad/40 bg-bad/5 p-3 text-xs">
          <div className="flex items-center gap-1.5 font-semibold text-bad"><AlertTriangle className="h-3.5 w-3.5" />This clip cannot be made yet</div>
          <div>{node.blocked}</div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => P.act("Save", () => api.setJoin(P.pid, node.id, "cut"), "Joined as a cut")}>Change the join to a cut</Button>
            {node.provider_override && <Button size="sm" variant="outline" onClick={() => saveNode({ provider_override: null })}>Use the best model</Button>}
            {before?.provider_override && <Button size="sm" variant="outline" onClick={() => P.act("Save", () => api.unpin(P.pid, [before.id]), "The clip before now uses the best model")}>Use the best model on clip {P.numbers[before.id]}</Button>}
            <Button size="sm" variant="ghost" onClick={() => P.openSettings("keys")}>Open Settings</Button>
          </div>
        </Card>
      )}

      {node.warnings.map((w, i) => (
        <div key={i} className="flex items-start gap-2 rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="flex-1">{w}</span></div>
      ))}
      {node.needs_split && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel px-3 py-2 text-xs">
          <span className="min-w-0 flex-1">This clip needs more than any single route can do, so part of it cannot be made well. Splitting makes consecutive clips that each need one kind of movement, linked so each starts where the last ends.</span>
          <HelpTip id="split-clip">
            <Button size="sm" variant="primary" loading={P.busy.includes("Splitting")}
              onClick={() => P.act("Splitting", () => api.splitClip(P.pid, node.id), "Clip split into parts")}>Split this clip</Button>
          </HelpTip>
        </div>
      )}

      {/* preview */}
      <Card className="overflow-hidden">
        <div className="relative aspect-video bg-black/90">
          {chosen?.video || node.output ? (
            <video key={node.output || chosen?.video || ""} src={fileUrl(P.pid, node.output || chosen?.video)} controls className="h-full w-full" />
          ) : shownTakes[0]?.keyframe ? (
            <img src={fileUrl(P.pid, shownTakes[0].keyframe)} className="h-full w-full object-contain" alt="Keyframe" />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-white/60">
              {generating ? <><RefreshCw className="h-6 w-6 animate-spin" /><span className="text-xs">{liveStep?.step || p.run.message || "Making this clip…"}</span>
                {liveStep && <span className="text-[11px] tabular-nums text-white/50">{Math.round(liveStep.elapsed_s + (Date.now() - P.fetchedAt) / 1000)} s so far{liveStep.expected_s ? ` · about ${Math.round(liveStep.expected_s)} s expected` : ""}</span>}</>
                : <><Film className="h-7 w-7" /><span className="text-xs">Not made yet</span></>}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line px-4 py-2.5 text-xs">
          <LengthEditor node={node} onSave={(v) => saveNode({ target_seconds: v })} />
          <Tip content={<div className="space-y-0.5">{node.cost.lines.map((l, i) => <div key={i}>{l.item}: {l.calc} = {fmtUsd(l.cost)}</div>)}</div>}>
            <span className="cursor-help"><span className="font-medium">{fmtRange(node.cost.min_usd, node.cost.max_usd)}</span>
              {node.cost.actual_usd != null && <span className="text-muted"> · actual {fmtUsd(node.cost.actual_usd)}</span>}</span>
          </Tip>
          <Tip content={node.time.explain}><span className="cursor-help text-muted">~{fmtTime(node.time.likely_s)} to make</span></Tip>
          <div className="flex-1" />
          {node.kind === "clip" && <Switch help="keep-clip" checked={!!node.locked} onChange={(locked) => saveNode({ locked })} label="Keep as it is" />}
          {node.kind === "clip" && (
            <ModelPicker jobs={["video", "avatar"]} help="model-select" showDetail={false} shot={s?.shot_type} value={node.provider_override || ""}
              autoLabel={`Auto (${node.cost.model || "best fit"}${autoRow ? ` · ${autoRow.price_text}` : ""})`}
              onChange={(v) => saveNode({ provider_override: v || null })} />
          )}
          <Button help="clip-generate" variant="primary" size="sm" disabled={generating}
            onClick={() => run({ mode: "clip", targets: [node.id], title: `Make clip ${P.numbers[node.id]}` })}>
            <Play className="h-3.5 w-3.5" />{node.status === "done" || node.takes.length ? "Re-make" : "Generate this clip"}
          </Button>
        </div>
      </Card>

      {shownTakes.length > 0 && node.kind === "clip" && <Takes node={node} takes={shownTakes} />}

      <AskAI node={node} placeholder="make Rahul look more frustrated" />

      {/* goal */}
      <Card className="p-4">
        <div className="field-label mb-1">Goal of this clip</div>
        <Editable value={node.goal} onSave={(goal) => saveNode({ goal })} multiline placeholder="What should this clip show?" />
      </Card>

      {node.kind !== "clip" ? (
        <Card className="space-y-2 p-4">
          <div className="field-label">Narration over your {node.kind === "slides" ? "slides" : "video"} (optional)</div>
          <Editable value={s?.narration || ""} onSave={(narration) => saveScript({ narration })} multiline placeholder="Text to be spoken" />
        </Card>
      ) : !s ? (
        <Card className="p-5">
          <Empty title="No script yet" icon={<Wand2 className="h-6 w-6" />}>
            <Button className="mt-2" variant="primary" loading={P.busy.includes("Writing script")} onClick={() => P.act("Writing script", () => api.writeScript(P.pid, node.id), "Script written")}>
              <Wand2 className="h-3.5 w-3.5" />Write the script with AI</Button>
          </Empty>
        </Card>
      ) : (
        <Card className="divide-y divide-line">
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <div>
              <div className="field-label mb-1">Shot type</div>
              <Select help="shot-type" title="Shot type" value={s.shot_type} onChange={(shot_type) => saveScript({ shot_type })} options={SHOT_TYPES} />
            </div>
            <div className="flex items-end gap-4">
              <Switch help="on-camera-speech" checked={s.on_camera_speech} onChange={(on_camera_speech) => saveScript({ on_camera_speech })} label="Someone speaks on camera (lip-sync)" />
            </div>
          </div>
          <div className="p-4">
            <div className="field-label mb-1">What we see</div>
            <Editable value={s.visual} onSave={(visual) => saveScript({ visual })} multiline />
          </div>
          <div className="grid gap-4 p-4 sm:grid-cols-2">
            <div>
              <div className="field-label mb-1">Action</div>
              <ListEditor items={s.action_beats} onSave={(action_beats) => saveScript({ action_beats })} placeholder="Add an action beat" />
            </div>
            <div>
              <div className="field-label mb-1">Camera</div>
              <Editable value={s.camera} onSave={(camera) => saveScript({ camera })} placeholder="e.g. slow push-in, eye level" />
            </div>
          </div>
          <div className="p-4">
            <div className="field-label mb-2 flex items-center gap-2"><User className="h-3.5 w-3.5" />Actors in this shot</div>
            <ActorsInShot node={node} />
          </div>
          <div className="p-4">
            <div className="field-label mb-2 flex items-center gap-2"><Mic className="h-3.5 w-3.5" />Dialogue</div>
            <Dialogue lines={s.dialogue} actors={actors.map((a) => ({ id: a.id, title: a.title }))} onSave={(dialogue) => saveScript({ dialogue })} />
          </div>
          <div className="p-4">
            <div className="field-label mb-1 flex items-center gap-2">Narration (voice-over)
              {s.narration.trim() && <ExactToggle on={!!s.narration_fixed} onChange={(narration_fixed) => saveScript({ narration_fixed })} />}</div>
            <Editable value={s.narration} onSave={(narration) => saveScript({ narration })} multiline placeholder="Optional voice-over" />
          </div>
          <div className="grid gap-4 p-4 sm:grid-cols-2">
            <div><HelpTip id="natural-sound"><div className="field-label mb-1">Natural sound (the plan)</div></HelpTip>
              <Editable value={s.sound_notes} onSave={(sound_notes) => saveScript({ sound_notes })} placeholder="Wind, birds, room tone, footsteps… or “silence”" /></div>
            <div><div className="field-label mb-1">Avoid</div><Editable value={s.negative} onSave={(negative) => saveScript({ negative })} placeholder="e.g. extra fingers, text" /></div>
          </div>
          <div className="grid gap-4 p-4 sm:grid-cols-2">
            <div><div className="field-label mb-1">The clip starts as</div>
              <Editable value={s.start_state || ""} onSave={(start_state) => saveScript({ start_state })} multiline placeholder="Pose, place, time of day, framing, light (a clip that continues the previous one starts where it ended)" /></div>
            <div><div className="field-label mb-1">The clip ends as</div>
              <Editable value={s.end_state || ""} onSave={(end_state) => saveScript({ end_state })} multiline placeholder="How it ends: the next clip that continues starts from here" /></div>
          </div>
        </Card>
      )}
    </div>
  );
}

function ListEditor({ items, onSave, placeholder }: { items: string[]; onSave: (v: string[]) => void; placeholder: string }) {
  const [add, setAdd] = useState("");
  return (
    <div className="space-y-1">
      {items.map((it, i) => (
        <div key={i} className="group flex items-start gap-1.5">
          <span className="mt-1 text-[11px] text-muted">{i + 1}.</span>
          <div className="flex-1"><Editable value={it} onSave={(v) => onSave(items.map((x, j) => (j === i ? v : x)).filter(Boolean))} /></div>
          <button aria-label="Remove" className="mt-1 opacity-0 group-hover:opacity-100 text-muted hover:text-bad" onClick={() => onSave(items.filter((_, j) => j !== i))}><Trash2 className="h-3 w-3" /></button>
        </div>
      ))}
      <input value={add} onChange={(e) => setAdd(e.target.value)} placeholder={`+ ${placeholder}`}
        onKeyDown={(e) => { if (e.key === "Enter" && add.trim()) { onSave([...items, add.trim()]); setAdd(""); } }}
        className="h-7 w-full rounded-md bg-transparent px-1.5 text-xs placeholder:text-muted/70 hover:bg-sunken focus:bg-sunken focus:outline-none" />
    </div>
  );
}

function ActorsInShot({ node }: { node: Node }) {
  const P = useP();
  const p = P.view!.project;
  const s = node.script!;
  const actors = p.context.filter((c) => c.type === "actor");
  const inShot = s.actors_in_shot;
  const save = (actors_in_shot: typeof inShot) => P.act("Save", () => api.patchNode(P.pid, node.id, { script: { actors_in_shot } }));
  return (
    <div className="space-y-2">
      {inShot.map((a, i) => {
        const actor = actors.find((x) => x.id === a.actor_id);
        const img = actor?.actor?.reference_sheet[0] || actor?.files.find((f) => /\.(png|jpe?g|webp)$/i.test(f));
        return (
          <div key={i} className="flex items-start gap-3 rounded-lg bg-sunken/60 p-2">
            <div className="h-10 w-10 shrink-0 overflow-hidden rounded-md bg-line">{img ? <img src={fileUrl(P.pid, img)} className="h-full w-full object-cover" alt="" /> : <User className="m-2.5 h-5 w-5 text-muted" />}</div>
            <div className="min-w-0 flex-1 text-xs">
              <div className="font-medium">{actor?.title || a.actor_id}</div>
              <div className="grid gap-1 sm:grid-cols-2">
                <Editable value={a.clothing} placeholder={`Clothing (default: ${actor?.actor?.clothing || "—"})`} onSave={(clothing) => save(inShot.map((x, j) => (j === i ? { ...x, clothing } : x)))} />
                <Editable value={a.behaviour} placeholder={`Behaviour (default: ${actor?.actor?.behaviour || "—"})`} onSave={(behaviour) => save(inShot.map((x, j) => (j === i ? { ...x, behaviour } : x)))} />
              </div>
            </div>
            <button aria-label="Remove from shot" className="text-muted hover:text-bad" onClick={() => save(inShot.filter((_, j) => j !== i))}><Trash2 className="h-3.5 w-3.5" /></button>
          </div>
        );
      })}
      <Select value="" onChange={(id) => id && save([...inShot, { actor_id: id, clothing: "", behaviour: "" }])}
        options={[{ value: "", label: "+ Add an actor to this shot" }, ...actors.filter((a) => !inShot.some((x) => x.actor_id === a.id)).map((a) => ({ value: a.id, label: a.title }))]} />
    </div>
  );
}

/** "Say exactly this": a line marked this way is never shortened, reworded or dropped, whatever the AI or the length change does. */
function ExactToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <Tip content={on ? "Said exactly as written. It is never shortened, reworded or dropped. Click to allow changes." : "Click to say this exactly as written: it is then never shortened, reworded or dropped."}>
      <button type="button" aria-pressed={on} aria-label="Say exactly this" data-help="say-exactly" onClick={() => onChange(!on)}
        className={cn("mt-1 inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[10px]", on ? "border-brand/50 bg-brand/10 text-brand" : "border-line text-muted hover:border-brand/40")}>
        {on ? <Lock className="h-2.5 w-2.5" /> : <LockOpen className="h-2.5 w-2.5" />}{on ? "exact" : "exact?"}
      </button>
    </Tip>
  );
}

function Dialogue({ lines, actors, onSave }: { lines: Line[]; actors: { id: string; title: string }[]; onSave: (l: Line[]) => void }) {
  const speakers = [{ value: "narrator", label: "Narrator" }, ...actors.map((a) => ({ value: a.id, label: a.title }))];
  return (
    <div className="space-y-1.5">
      {lines.map((l, i) => (
        <div key={i} className="group flex items-start gap-2">
          <Select value={l.speaker} onChange={(speaker) => onSave(lines.map((x, j) => (j === i ? { ...x, speaker } : x)))}
            options={speakers.some((s) => s.value === l.speaker) ? speakers : [...speakers, { value: l.speaker, label: l.speaker }]} className="w-32 shrink-0" />
          <div className="flex-1"><Editable value={l.text} onSave={(text) => onSave(lines.map((x, j) => (j === i ? { ...x, text } : x)))} multiline /></div>
          <ExactToggle on={!!l.fixed} onChange={(fixed) => onSave(lines.map((x, j) => (j === i ? { ...x, fixed } : x)))} />
          <button aria-label="Remove line" className="mt-1 opacity-0 group-hover:opacity-100 text-muted hover:text-bad" onClick={() => onSave(lines.filter((_, j) => j !== i))}><Trash2 className="h-3 w-3" /></button>
        </div>
      ))}
      <Button variant="ghost" size="sm" onClick={() => onSave([...lines, { speaker: actors[0]?.id || "narrator", text: "", emotion: "" }])}><Plus className="h-3.5 w-3.5" />Add line</Button>
    </div>
  );
}

// ======================================================================= takes + review
function verdictBadge(r?: Review) {
  if (!r) return <Badge>Not reviewed</Badge>;
  if (r.verdict === "meets_goal") return <Badge tone="ok"><CheckCircle2 className="h-3 w-3" />Meets the goal</Badge>;
  if (r.verdict === "minor_issues") return <Badge tone="warn"><AlertTriangle className="h-3 w-3" />Minor issues</Badge>;
  return <Badge tone="bad"><XCircle className="h-3 w-3" />Does not meet the goal</Badge>;
}

const JOIN_WORDS: Record<string, string> = { continues: "continues the same shot", same_scene: "stays in the same scene", cut: "is a deliberate cut" };

/** How this take is stitched to the clip before it: the two pictures the Review Agent was shown, the plan's join, the measured difference and the score. */
function StitchPanel({ review }: { review: Review }) {
  const P = useP();
  const j = review.join!;
  const score = review.scores.join || 0;
  return (
    <div data-help="stitch-panel" className="rounded-xl border border-line p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2 font-medium">
        <Link2 className="h-3.5 w-3.5 text-brand" />Stitch with the clip before{j.previous ? ` (clip ${j.previous})` : ""}
        {j.judged && score > 0 && <Badge tone={score >= 4 ? "ok" : score >= 3 ? "warn" : "bad"}>{score}/5</Badge>}
      </div>
      {j.judged ? (
        <div className="mt-2 flex flex-wrap items-start gap-3">
          {j.previous_frame && <figure className="w-36"><img src={fileUrl(P.pid, j.previous_frame)} alt={`Last picture of clip ${j.previous}`} className="w-full rounded" /><figcaption className="mt-0.5 text-[10px] text-muted">last picture of clip {j.previous}</figcaption></figure>}
          {j.this_frame && <figure className="w-36"><img src={fileUrl(P.pid, j.this_frame)} alt="First picture of this take" className="w-full rounded" /><figcaption className="mt-0.5 text-[10px] text-muted">first picture of this take</figcaption></figure>}
          <div className="min-w-0 flex-1 space-y-0.5 text-muted">
            <div>The plan says this clip <b className="text-ink">{JOIN_WORDS[j.kind] || "joins the clip before"}</b>{j.reason ? ` (${j.reason})` : ""}.</div>
            {j.transition && j.transition !== "cut" && <div>Planned transition: {j.transition}.</div>}
            {j.difference != null && <div>Measured difference {j.difference.toFixed(2)} (0 = the same picture){j.kind === "continues" ? `; the limit for a continuing shot is ${j.limit.toFixed(2)}` : ""}.</div>}
          </div>
        </div>
      ) : <div className="mt-1 text-muted">Not judged: {j.why_not || "there was nothing to compare with"}.</div>}
    </div>
  );
}

function Takes({ node, takes }: { node: Node; takes: Take[] }) {
  const P = useP();
  const p = P.view!.project;
  const reviews = Object.fromEntries(p.reviews.map((r) => [r.id, r]));
  const [feedback, setFeedback] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [focus, setFocus] = useState<string>(takes[0]?.id);
  const settings = useSettings();
  const [compare, setCompare] = useState(false);
  const focusTake = takes.find((t) => t.id === focus) || takes[0];
  const focusReview = focusTake?.review_id ? reviews[focusTake.review_id] : undefined;
  const allSuggestions = takes.flatMap((t) => (t.review_id && reviews[t.review_id] ? reviews[t.review_id].suggestions.map((s) => ({ ...s, rid: t.review_id! })) : []));
  const accepted = allSuggestions.filter((s) => s.accepted).map((s) => s.id);
  const needPick = node.status === "needs_pick";

  const openPreview = async () => {
    const r = await P.act("Preparing re-make", () => api.remakePreview(P.pid, node.id, accepted, feedback));
    if (r) setPreview(r);
  };

  return (
    <Card className={cn("p-4", needPick && "border-warn/50")}>
      <div className="mb-3 flex items-center gap-2">
        <div className="text-sm font-semibold">Takes</div>
        {needPick && <Badge tone="warn">Pick the best take</Badge>}
        <div className="flex-1" />
        <Button help="compare-models" size="sm" variant="ghost" onClick={() => setCompare(true)}>Compare models…</Button>
      </div>
      <div className={cn("grid gap-3", takes.length === 1 ? "grid-cols-1" : takes.length === 2 ? "grid-cols-2" : "grid-cols-3")}>
        {takes.map((t, i) => {
          const r = t.review_id ? reviews[t.review_id] : undefined;
          const chosen = node.chosen_take === t.id;
          return (
            <div key={t.id} onClick={() => setFocus(t.id)}
              className={cn("rounded-xl border p-1.5 transition-colors cursor-pointer", focus === t.id ? "border-brand" : "border-line", chosen && "ring-2 ring-ok/50")}>
              <video src={fileUrl(P.pid, t.video)} controls preload="metadata" className="aspect-video w-full rounded-lg bg-black" />
              <div className="flex flex-wrap items-center gap-1.5 px-1 pt-1.5 text-[11px]">
                <span className="font-medium">Take {i + 1}</span>
                <span className="text-muted">{t.model} · {t.seconds.toFixed(1)}s</span>
                {verdictBadge(r)}
                {t.quality.face_similarity != null && <Tip content="How closely the face matches the actor's photos"><span><Badge tone={t.quality.face_similarity > 0.6 ? "ok" : "warn"}>face {Math.round(t.quality.face_similarity * 100)}%</Badge></span></Tip>}
                {t.quality.flicker != null && t.quality.flicker > 0.03 && <Badge tone="warn">flicker</Badge>}
              </div>
              <div className="px-1 pb-0.5 pt-1.5">
                {chosen ? <Badge tone="ok"><Check className="h-3 w-3" />Chosen</Badge>
                  : <Button help="pick-take" size="sm" variant={needPick ? "primary" : "outline"} className="w-full" onClick={(e) => { e.stopPropagation(); P.act("Picking", () => api.pick(P.pid, node.id, t.id), "Take chosen"); }}>Pick this take</Button>}
              </div>
            </div>
          );
        })}
      </div>

      {/* review agent */}
      <div className="mt-4 rounded-xl bg-sunken/60 p-3">
        <div className="mb-2 flex items-center gap-2 text-xs">
          <Sparkles className="h-3.5 w-3.5 text-brand" /><span className="font-semibold">Review Agent</span>
          <span className="text-muted">— suggestions only; you decide</span>
          {focusReview && <span className="ml-auto text-[11px] text-muted">{focusReview.reviewer_model} · {fmtUsd(focusReview.cost_usd)}</span>}
        </div>
        {!focusReview ? <div className="text-xs text-muted">No review for this take yet.</div> : (
          <div className="space-y-3">
            {focusReview.summary && <p className="text-xs">{focusReview.summary}</p>}
            <div className="grid grid-cols-4 gap-x-4 gap-y-1.5">
              {Object.entries(focusReview.scores).filter(([k, v]) => !(k === "join" && (!v || focusReview.join))).map(([k, v]) => (
                <div key={k} className="text-[11px]">
                  <div className="flex justify-between"><span className="capitalize text-muted">{k}</span><span className="font-medium">{v}/5</span></div>
                  <div className="mt-0.5 h-1 rounded-full bg-line"><div className={cn("h-full rounded-full", v >= 4 ? "bg-ok" : v >= 3 ? "bg-warn" : "bg-bad")} style={{ width: `${v * 20}%` }} /></div>
                </div>
              ))}
            </div>
            {focusReview.join && <StitchPanel review={focusReview} />}
            {focusReview.issues.length > 0 && (
              <ul className="space-y-1">
                {focusReview.issues.map((iss, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs">
                    <span className={cn("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", iss.severity === "major" ? "bg-bad" : "bg-warn")} />
                    <span className="flex-1"><span className="font-medium capitalize">{iss.check}:</span> {iss.text}</span>
                    {iss.at_s != null && <Badge>{iss.at_s.toFixed(1)}s</Badge>}
                    {iss.frame && <img src={fileUrl(P.pid, iss.frame)} alt="" className="h-8 rounded" />}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {allSuggestions.length > 0 && (
          <div className="mt-3 space-y-1">
            <div className="field-label">Suggested fixes (tick the ones to use)</div>
            {allSuggestions.map((sg) => (
              <label key={sg.id} className="flex items-start gap-2 text-xs">
                <input type="checkbox" className="mt-0.5 accent-[rgb(var(--brand))]" checked={sg.accepted}
                  onChange={(e) => P.act("Save", () => api.patchSuggestion(P.pid, sg.rid, sg.id, { accepted: e.target.checked }))} />
                <span className="flex-1"><Editable value={sg.text} onSave={(text) => P.act("Save", () => api.patchSuggestion(P.pid, sg.rid, sg.id, { text }))} /></span>
              </label>
            ))}
          </div>
        )}
        <div className="mt-3">
          <div className="field-label mb-1">Your feedback (wins over the agent's)</div>
          <Textarea data-help="feedback-box" rows={2} value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="e.g. make the strap break in slow motion" />
        </div>
        <div className="mt-2 flex justify-end">
          <Button help="remake-feedback" variant="primary" size="sm" onClick={openPreview} loading={P.busy.includes("Preparing re-make")} disabled={!feedback.trim() && accepted.length === 0}>
            <RefreshCw className="h-3.5 w-3.5" />Re-make with feedback…</Button>
        </div>
      </div>

      <Dialog open={!!preview} onOpenChange={(o) => !o && setPreview(null)} wide title="Re-make with feedback"
        description="The AI combined your feedback with the accepted suggestions. Check the change and the new cost."
        footer={<>
          <Button variant="ghost" onClick={() => setPreview(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { await P.act("Re-making", () => api.remakeApply(P.pid, node.id, preview.new, preview.feedback), "Re-make started"); setPreview(null); }}>
            <Play className="h-3.5 w-3.5" />Re-make (≈ {fmtUsd(preview?.cost?.likely_usd)}, ~{fmtTime(preview?.time?.likely_s)})</Button>
        </>}>
        {preview && (
          <div className="space-y-3 text-xs">
            {preview.change_summary && <div className="rounded-lg bg-brand/10 px-3 py-2 text-brand">{preview.change_summary}</div>}
            {(["visual", "camera", "narration", "negative"] as const).map((f) => (preview.old?.[f] !== preview.new?.[f]) && (
              <div key={f} className="grid grid-cols-2 gap-3">
                <div><div className="field-label mb-1">{f} — before</div><div className="rounded-lg bg-bad/5 p-2 whitespace-pre-wrap">{preview.old?.[f] || "—"}</div></div>
                <div><div className="field-label mb-1">{f} — after</div><div className="rounded-lg bg-ok/10 p-2 whitespace-pre-wrap">{preview.new?.[f] || "—"}</div></div>
              </div>
            ))}
            {JSON.stringify(preview.old?.dialogue) !== JSON.stringify(preview.new?.dialogue) && (
              <div className="grid grid-cols-2 gap-3">
                <div><div className="field-label mb-1">dialogue — before</div><div className="rounded-lg bg-bad/5 p-2">{(preview.old?.dialogue || []).map((l: Line, i: number) => <div key={i}>{l.text}</div>)}</div></div>
                <div><div className="field-label mb-1">dialogue — after</div><div className="rounded-lg bg-ok/10 p-2">{(preview.new?.dialogue || []).map((l: Line, i: number) => <div key={i}>{l.text}</div>)}</div></div>
              </div>
            )}
          </div>
        )}
      </Dialog>
      <CompareDialog open={compare} onOpenChange={setCompare} node={node} catalog={settings.data?.catalog || []} />
    </Card>
  );
}

function CompareDialog({ open, onOpenChange, node, catalog }: { open: boolean; onOpenChange: (v: boolean) => void; node: Node; catalog: any[] }) {
  const P = useP();
  const models = catalog.filter((e) => e.job === "video" && e.usable);
  const [sel, setSel] = useState<string[]>([]);
  const cost = sel.reduce((a, id) => a + (models.find((m) => m.id === id)?.price.usd || 0) * node.duration.likely_s, 0);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Compare models on this clip"
      description="Makes the same clip once with each model, so you can judge them on your own content."
      footer={<>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" disabled={sel.length < 1} onClick={async () => { await P.act("Comparing", () => api.compare(P.pid, node.id, sel), "Comparison started"); onOpenChange(false); }}>
          Compare (≈ {fmtUsd(cost)})</Button>
      </>}>
      {models.length === 0 ? <div className="text-xs text-muted">Add a video vendor key in Settings to compare models.</div> : (
        <div className="space-y-1">
          {models.map((m) => (
            <label key={m.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs hover:bg-sunken">
              <input type="checkbox" checked={sel.includes(m.id)} onChange={(e) => setSel(e.target.checked ? [...sel, m.id] : sel.filter((x) => x !== m.id))} />
              <span className="flex-1 font-medium">{m.id}</span>
              <span className="text-muted">{fmtUsd(m.price.usd * node.duration.likely_s)}</span>
            </label>
          ))}
        </div>
      )}
    </Dialog>
  );
}

export { leaves };
