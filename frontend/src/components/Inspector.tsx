import { useQuery } from "@tanstack/react-query";
import { ArrowRight, History, Link2, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, Node } from "../api";
import { DEP_TYPES, depLabel, fmtRange, fmtSec, fmtTime, fmtUsd, leaves, TRANSITIONS, useP, useSettings } from "../lib";
import { Badge, Button, DropZone, Empty, Input, Select, TabList, TabPanel, Tabs } from "../ui";
import { ContextCard } from "./ContextCard";

export default function Inspector({ node }: { node: Node }) {
  const P = useP();
  const p = P.view!.project;
  const isClip = node.kind !== "goal";
  const ups = p.dependencies.filter((d) => d.to_id === node.id || d.from_id === node.id).length;
  return (
    <Tabs defaultValue="context" className="flex min-h-0 flex-1 flex-col">
      <TabList tabs={[
        { value: "context", label: "Context" },
        { value: "cost", label: "Cost & time" },
        ...(isClip ? [{ value: "links", label: "Links", count: ups }, { value: "versions", label: "Versions", count: node.versions.length }] : []),
      ]} />
      <div className="min-h-0 flex-1 overflow-auto scroll-thin p-3">
        <TabPanel value="context"><ContextTab node={node} /></TabPanel>
        <TabPanel value="cost"><CostTab node={node} /></TabPanel>
        {isClip && <TabPanel value="links"><LinksTab node={node} /></TabPanel>}
        {isClip && <TabPanel value="versions"><VersionsTab node={node} /></TabPanel>}
      </div>
    </Tabs>
  );
}

// ------------------------------------------------------------------ context
function ContextTab({ node }: { node: Node }) {
  const P = useP();
  const p = P.view!.project;
  const isRoot = node.id === p.root.id;
  const eff = useQuery({ queryKey: ["ctx", P.pid, node.id, p.updated_at], queryFn: () => api.nodeContext(P.pid, node.id), enabled: !isRoot });
  const shared = p.context.filter((c) => c.scope === "project");
  const own = isRoot ? [] : (eff.data || []).filter((e) => e.origin === "this");
  const inherited = isRoot ? [] : (eff.data || []).filter((e) => e.origin !== "this");
  const off = new Set(node.context_off);
  const offItems = p.context.filter((c) => off.has(c.id));
  const [note, setNote] = useState("");
  const scope = isRoot ? "project" : `node:${node.id}`;
  const addNote = async (target: string) => {
    if (!note.trim()) return;
    await P.act("Add note", () => api.addContext(P.pid, { type: "text", role: "knowledge", title: note.slice(0, 40), text: note, scope: target }), "Note added");
    setNote("");
  };
  const ownLabel = node.kind === "goal" ? "This part and below" : "This clip only";
  return (
    <div className="space-y-5">
      {!isRoot && (
        <section>
          <SectionTitle title={ownLabel} hint="Photos, sounds, notes that apply only here" />
          <div className="space-y-1.5">
            {own.map((e) => <ContextCard key={e.item.id} item={e.item} origin="this" />)}
            <DropZone compact label="Drop photos, sounds, notes for this one"
              onFiles={(files) => P.act("Upload", () => api.upload(P.pid, files, { scope }), "Added")} />
          </div>
        </section>
      )}
      <section>
        <SectionTitle title={isRoot ? "Shared — all clips" : "Inherited"} hint={isRoot ? "Brand, style, actors, narrator, facts" : "From the whole video and parent parts"} />
        <div className="space-y-1.5">
          {(isRoot ? shared.map((c) => ({ item: c, origin: "shared" })) : inherited).map((e) => (
            <ContextCard key={e.item.id} item={e.item} origin={e.origin}
              onToggle={isRoot ? undefined : (o) => P.act("Save", () => api.toggleContext(P.pid, node.id, e.item.id, o))} />
          ))}
          {offItems.map((c) => (
            <ContextCard key={c.id} item={c} origin="shared" inheritedOff onToggle={(o) => P.act("Save", () => api.toggleContext(P.pid, node.id, c.id, o))} />
          ))}
          {isRoot && <DropZone compact label="Drop logo, brand guide, actor photos, voice, music…"
            onFiles={(files) => P.act("Upload", () => api.upload(P.pid, files, { scope: "project" }), "Added to shared context")} />}
          {!isRoot && inherited.length === 0 && offItems.length === 0 && <div className="text-xs text-muted">Nothing inherited.</div>}
        </div>
      </section>
      <section className="space-y-1.5">
        <Input value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addNote(scope)}
          placeholder={`Add a note ${isRoot ? "for all clips" : node.kind === "goal" ? "for this part" : "for this clip"}… (Enter)`} />
        <div className="flex gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => P.act("Add actor", () => api.addContext(P.pid, { type: "actor", role: "must_appear", title: "New actor", scope }), "Actor added — click it to describe")}>
            <Plus className="h-3.5 w-3.5" />Actor</Button>
          <Button size="sm" variant="ghost" onClick={() => P.act("Add", () => api.addContext(P.pid, { type: "location", role: "look_reference", title: "Location", scope }))}><Plus className="h-3.5 w-3.5" />Location</Button>
          <Button size="sm" variant="ghost" onClick={() => P.act("Add", () => api.addContext(P.pid, { type: "object", role: "must_appear", title: "Object", scope }))}><Plus className="h-3.5 w-3.5" />Object</Button>
        </div>
      </section>
    </div>
  );
}

function SectionTitle({ title, hint }: { title: string; hint?: string }) {
  return <div className="mb-1.5"><div className="text-xs font-semibold">{title}</div>{hint && <div className="text-[11px] text-muted">{hint}</div>}</div>;
}

// ------------------------------------------------------------------ cost
function CostTab({ node }: { node: Node }) {
  const P = useP();
  const p = P.view!.project;
  const isClip = node.kind === "clip";
  const settings = useSettings();
  const models = (settings.data?.catalog || []).filter((e: any) => (e.job === "video" || e.job === "avatar") && e.usable);
  const ledger = useQuery({ queryKey: ["ledger", P.pid, p.updated_at], queryFn: () => api.ledger(P.pid) });
  const rows = (ledger.data || []).filter((r) => node.id === p.root.id || (r.what || "").includes(node.id) || r.node === node.id);
  return (
    <div className="space-y-4 text-xs">
      <div className="grid grid-cols-3 gap-2">
        <Box label="Length" value={`~${fmtSec(node.duration.likely_s)}`} sub={node.duration.basis === "goal" ? "from goal" : node.duration.basis === "script" ? "from script" : "real"} />
        <Box label="Cost" value={fmtUsd(node.cost.likely_usd)} sub={fmtRange(node.cost.min_usd, node.cost.max_usd)} />
        <Box label="Time" value={`~${fmtTime(node.time.likely_s)}`} sub="to make" />
      </div>
      <div className="text-[11px] text-muted">{node.duration.explain}</div>
      {node.cost.lines.length > 0 && (
        <table className="w-full">
          <tbody>
            {node.cost.lines.map((l, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                <td className="py-1.5 pr-2"><div className="font-medium">{l.item}</div><div className="text-[11px] text-muted">{l.calc}</div></td>
                <td className="py-1.5 text-right tabular-nums">{fmtUsd(l.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {node.cost.actual_usd != null && <div className="flex justify-between rounded-lg bg-sunken px-3 py-2"><span>Actual so far</span><span className="font-medium">{fmtUsd(node.cost.actual_usd)}</span></div>}
      {isClip && (
        <div className="space-y-2 rounded-xl border border-line p-3">
          <div className="text-xs font-semibold">What if…</div>
          <div className="flex items-center justify-between gap-2"><span className="text-muted">Model</span>
            <Select value={node.provider_override || ""} onChange={(v) => P.act("Save", () => api.patchNode(P.pid, node.id, { provider_override: v || null }))}
              options={[{ value: "", label: "Auto (best fit)" }, ...models.map((m: any) => ({ value: m.id, label: `${m.id} · $${m.price.usd}/s` }))]} /></div>
          <div className="flex items-center justify-between gap-2"><span className="text-muted">Takes</span>
            <Select value={String(node.takes_override || "")} onChange={(v) => P.act("Save", () => api.patchNode(P.pid, node.id, { takes_override: v ? Number(v) : null }))}
              options={[{ value: "", label: "Default" }, { value: "1", label: "1" }, { value: "2", label: "2" }, { value: "3", label: "3" }, { value: "4", label: "4" }]} /></div>
          <div className="flex items-center justify-between gap-2"><span className="text-muted">Transition in</span>
            <Select value={node.transition_in} onChange={(v) => P.act("Save", () => api.patchNode(P.pid, node.id, { transition_in: v }))} options={TRANSITIONS} /></div>
          <div className="flex items-center justify-between gap-2"><span className="text-muted">Review Agent</span>
            <Select value={node.review_enabled ? "on" : "off"} onChange={(v) => P.act("Save", () => api.patchNode(P.pid, node.id, { review_enabled: v === "on" }))}
              options={[{ value: "on", label: "On" }, { value: "off", label: "Off" }]} /></div>
        </div>
      )}
      {node.id === p.root.id && (
        <div className="space-y-2 rounded-xl border border-line p-3">
          <div className="text-xs font-semibold">Whole video</div>
          {[
            ["Quality", "quality_mode", [{ value: "best", label: "Best" }, { value: "balanced", label: "Balanced" }, { value: "budget", label: "Budget" }, { value: "free", label: "Free preview" }]],
            ["Resolution", "resolution", [{ value: "720p", label: "720p" }, { value: "1080p", label: "1080p" }, { value: "4k", label: "4K" }]],
            ["Takes for people", "takes_people", [1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }))],
            ["Format", "format", [{ value: "mp4", label: ".mp4" }, { value: "mov", label: ".mov" }]],
          ].map(([label, key, opts]: any) => (
            <div key={key} className="flex items-center justify-between gap-2"><span className="text-muted">{label}</span>
              <Select value={String((p.settings as any)[key])} options={opts}
                onChange={(v) => P.act("Save", () => api.patch(P.pid, { settings: { [key]: key === "takes_people" ? Number(v) : v } }))} /></div>
          ))}
          <div className="flex items-center justify-between gap-2"><span className="text-muted">Budget ($)</span>
            <input type="number" defaultValue={p.settings.budget_usd} key={p.settings.budget_usd} className="h-7 w-24 rounded-md border border-line bg-panel px-2 text-right"
              onBlur={(e) => P.act("Save", () => api.patch(P.pid, { settings: { budget_usd: Number(e.target.value) } }))} /></div>
          {[["Background music", "music"], ["Review Agent", "review_enabled"], ["Auto-pick best take", "auto_pick"]].map(([label, key]) => (
            <div key={key} className="flex items-center justify-between gap-2"><span className="text-muted">{label}</span>
              <Select value={(p.settings as any)[key] ? "on" : "off"} options={[{ value: "on", label: "On" }, { value: "off", label: "Off" }]}
                onChange={(v) => P.act("Save", () => api.patch(P.pid, { settings: { [key]: v === "on" } }))} /></div>
          ))}
        </div>
      )}
      {rows.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold">Spending log</div>
          <div className="max-h-60 overflow-auto scroll-thin rounded-lg border border-line">
            {rows.slice(-40).reverse().map((r, i) => (
              <div key={i} className="flex justify-between gap-2 border-b border-line/60 px-2 py-1 last:border-0">
                <span className="truncate">{r.what}</span>
                <span className="tabular-nums text-muted">est {fmtUsd(r.estimated_usd)} · {fmtUsd(r.actual_usd)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Box({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="rounded-lg border border-line p-2"><div className="text-[10px] uppercase text-muted">{label}</div><div className="text-sm font-semibold tabular-nums">{value}</div>{sub && <div className="text-[10px] text-muted">{sub}</div>}</div>;
}

// ------------------------------------------------------------------ links
function LinksTab({ node }: { node: Node }) {
  const P = useP();
  const p = P.view!.project;
  const clips = leaves(p).filter((c) => c.id !== node.id);
  const ups = p.dependencies.filter((d) => d.to_id === node.id);
  const downs = p.dependencies.filter((d) => d.from_id === node.id);
  const [from, setFrom] = useState("");
  const [type, setType] = useState("continues_from");
  const title = (id: string) => `${P.numbers[id]} ${leaves(p).find((c) => c.id === id)?.title || ""}`;
  const row = (d: typeof ups[number], other: string, dir: "up" | "down") => (
    <div key={d.id} className="rounded-lg border border-line p-2 text-xs">
      <div className="flex items-center gap-1.5">
        {dir === "up" ? <><span className="font-medium">{title(other)}</span><ArrowRight className="h-3 w-3 text-muted" /><span className="text-muted">this</span></>
          : <><span className="text-muted">this</span><ArrowRight className="h-3 w-3 text-muted" /><span className="font-medium">{title(other)}</span></>}
        <div className="flex-1" />
        <Badge tone={d.source === "user" ? "neutral" : "brand"}>{d.source === "ai" ? "AI" : d.source === "rule" ? "auto" : "you"}</Badge>
        <button aria-label="Remove link" className="text-muted hover:text-bad" onClick={() => P.act("Save", () => api.removeDep(P.pid, d.id))}><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      <Select value={d.type} onChange={(t) => P.act("Save", () => api.patchDep(P.pid, d.id, t))} options={DEP_TYPES} className="mt-1.5 w-full" />
      {d.note && <div className="mt-1 text-[11px] text-muted">{d.note}</div>}
      {d.payload?.handoff_frame && <div className="mt-1.5"><div className="text-[10px] text-muted">Hand-off frame used:</div><img src={`/files/${P.pid}/${d.payload.handoff_frame}`} className="mt-0.5 h-16 rounded" alt="Hand-off frame" /></div>}
    </div>
  );
  return (
    <div className="space-y-4">
      <p className="text-[11px] text-muted">The tool handles links automatically: a clip that “continues from” another starts on that clip's last frame, and waits until it is made.</p>
      <section className="space-y-1.5">
        <div className="text-xs font-semibold">Depends on</div>
        {ups.length ? ups.map((d) => row(d, d.from_id, "up")) : <div className="text-xs text-muted">Nothing — it can be made any time.</div>}
      </section>
      <section className="space-y-1.5">
        <div className="text-xs font-semibold">Used by</div>
        {downs.length ? downs.map((d) => row(d, d.to_id, "down")) : <div className="text-xs text-muted">No later clip depends on this one.</div>}
      </section>
      <section className="space-y-1.5 rounded-xl border border-line p-2">
        <div className="text-xs font-semibold">Add a link</div>
        <Select value={from} onChange={setFrom} className="w-full" options={[{ value: "", label: "This clip depends on…" }, ...clips.map((c) => ({ value: c.id, label: title(c.id) }))]} />
        <Select value={type} onChange={setType} className="w-full" options={DEP_TYPES} />
        <Button size="sm" disabled={!from} onClick={() => P.act("Link", () => api.addDep(P.pid, from, node.id, type), "Link added").then(() => setFrom(""))}><Link2 className="h-3.5 w-3.5" />Add link</Button>
      </section>
      <Button size="sm" variant="ghost" loading={P.busy.includes("Finding links")} onClick={() => P.act("Finding links", () => api.suggestDeps(P.pid), "Links updated")}>
        <Sparkles className="h-3.5 w-3.5" />Find links with AI</Button>
    </div>
  );
}

// ------------------------------------------------------------------ versions
function VersionsTab({ node }: { node: Node }) {
  const P = useP();
  if (!node.versions.length) return <Empty title="Only one version" icon={<History className="h-6 w-6" />}>Each re-make with feedback keeps the previous version here, with the feedback that led to it.</Empty>;
  return (
    <div className="space-y-2 text-xs">
      <div className="rounded-lg bg-brand/10 px-3 py-2 text-brand">Current: v{node.version}</div>
      {[...node.versions].reverse().map((v) => (
        <div key={`${v.version}-${v.created_at}`} className="rounded-lg border border-line p-2.5">
          <div className="flex items-center justify-between"><span className="font-medium">v{v.version}</span><span className="text-[11px] text-muted">{new Date(v.created_at).toLocaleString()}</span></div>
          {v.feedback && <div className="mt-1 text-[11px] text-muted line-clamp-3">Feedback: {v.feedback}</div>}
          <div className="mt-1 line-clamp-2">{v.script.visual}</div>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => P.act("Going back", () => api.revert(P.pid, node.id, v.version), `Back to v${v.version}`)}>Go back to this version</Button>
        </div>
      ))}
    </div>
  );
}
