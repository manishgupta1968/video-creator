import { ChevronDown, ChevronRight, Film, Link2, Loader2, MoreHorizontal, Paperclip, Plus, Presentation, Sparkles, Trash2, Video } from "lucide-react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { useState } from "react";
import { api, Node } from "../api";
import { fmtRange, fmtSec, STATUS, useP } from "../lib";
import { Button, cn, DropZone, Tip } from "../ui";

export default function StoryTree() {
  const P = useP();
  const p = P.view!.project;
  const s = P.view!.summary;
  const [drag, setDrag] = useState<string | null>(null);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-line px-3 py-2.5">
        <button onClick={() => P.select(p.root.id)} className={cn("w-full rounded-lg px-2 py-1.5 text-left hover:bg-sunken", P.selected === p.root.id && "bg-brand/10")}>
          <div className="field-label">Whole video</div>
          <div className="line-clamp-2 text-xs">{p.goal}</div>
          <div className="mt-1 flex gap-2 text-[11px] text-muted">
            <span title="Estimated length vs target">~{fmtSec(s.seconds)} / {fmtSec(s.target_seconds)}</span>
            <span>·</span><span title="Estimated cost">{fmtRange(s.cost_min, s.cost_max)}</span>
            <span>·</span><span>{s.done}/{s.clips} clips done</span>
          </div>
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto scroll-thin px-1.5 py-2" role="tree" aria-label="Goal tree">
        {p.root.children.map((c) => <Row key={c.id} node={c} depth={0} drag={drag} setDrag={setDrag} parentId={p.root.id} />)}
        <div className="px-2 pt-2">
          <Button variant="ghost" size="sm" className="w-full justify-start"
            onClick={async () => {
              const r = await P.act("Add part", () => api.addNode(P.pid, { parent_id: p.root.id, kind: "goal", title: "New part", goal: "" }));
              if (r) P.select((r as any).new_id);
            }}><Plus className="h-3.5 w-3.5" />Add part</Button>
        </div>
      </div>
      <div className="border-t border-line p-2">
        <DropZone compact label="" onFiles={(files) => P.act("Add files", () => api.upload(P.pid, files, { as_node: true }), "Added to the story")}>
          <span className="inline-flex items-center gap-1.5"><Paperclip className="h-3.5 w-3.5" />Drop slides or your own video to add them</span>
        </DropZone>
      </div>
    </div>
  );
}

function kindIcon(n: Node) {
  if (n.kind === "slides") return <Presentation className="h-3.5 w-3.5" />;
  if (n.kind === "user_clip") return <Film className="h-3.5 w-3.5" />;
  if (n.kind === "clip") return <Video className="h-3.5 w-3.5" />;
  return null;
}

function Row({ node, depth, drag, setDrag, parentId }: { node: Node; depth: number; drag: string | null; setDrag: (s: string | null) => void; parentId: string }) {
  const P = useP();
  const p = P.view!.project;
  const [open, setOpen] = useState(true);
  const [over, setOver] = useState<"before" | "inside" | "after" | null>(null);
  const isGoal = node.kind === "goal";
  const st = STATUS[node.status] || STATUS.ready;
  const ups = p.dependencies.filter((d) => d.to_id === node.id && d.type !== "order_only").length;
  const downs = p.dependencies.filter((d) => d.from_id === node.id && d.type !== "order_only").length;
  const ownCtx = p.context.filter((c) => c.scope === `node:${node.id}` || c.scope === `clip:${node.id}`).length + node.context_add.length;
  const selected = P.selected === node.id;
  const warn = node.warnings.length > 0;
  const act = (P.view!.engine.activity || []).find((a) => a.node === node.id);
  const preview = (P.view!.summary.preview.clips[node.id] || []).length > 0;

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/node");
    setOver(null);
    setDrag(null);
    if (!id || id === node.id) return;
    const parent = p.root.id === parentId ? p.root : findIn(p.root, parentId);
    const idx = parent ? parent.children.findIndex((c) => c.id === node.id) : 0;
    if (over === "inside" && isGoal) await P.act("Move", () => api.moveNode(P.pid, id, node.id, node.children.length));
    else await P.act("Move", () => api.moveNode(P.pid, id, parentId, over === "after" ? idx + 1 : idx));
  };

  return (
    <div role="treeitem" aria-expanded={isGoal ? open : undefined} aria-selected={selected}>
      <div
        draggable onDragStart={(e) => { e.dataTransfer.setData("text/node", node.id); setDrag(node.id); }} onDragEnd={() => setDrag(null)}
        onDragOver={(e) => {
          if (!drag || drag === node.id) return;
          e.preventDefault();
          const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
          const y = (e.clientY - r.top) / r.height;
          setOver(y < 0.3 ? "before" : y > 0.7 || !isGoal ? (y < 0.5 && !isGoal ? "before" : "after") : "inside");
        }}
        onDragLeave={() => setOver(null)} onDrop={onDrop}
        onClick={() => P.select(node.id)}
        className={cn("group relative flex cursor-pointer items-center gap-1 rounded-lg py-1 pr-1 text-[13px] hover:bg-sunken",
          selected && "bg-brand/10 hover:bg-brand/10", drag === node.id && "opacity-40",
          over === "inside" && "ring-2 ring-brand/60")}
        style={{ paddingLeft: 4 + depth * 14 }}>
        {over === "before" && <div className="absolute inset-x-2 -top-px h-0.5 rounded bg-brand" />}
        {over === "after" && <div className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-brand" />}
        <button aria-label={open ? "Collapse" : "Expand"} className={cn("grid h-5 w-5 place-items-center rounded text-muted hover:bg-line/60", !isGoal && "invisible")}
          onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </button>
        <span className="w-7 shrink-0 text-[11px] font-medium tabular-nums text-muted">{P.numbers[node.id]}</span>
        {!isGoal && <span className={cn("text-muted", node.status === "done" && "text-ok")}>{kindIcon(node)}</span>}
        <span className={cn("min-w-0 flex-1 truncate", isGoal && "font-medium")}>{node.title || node.goal || "Untitled"}</span>
        {ownCtx > 0 && <Tip content={`${ownCtx} context item(s) of its own`}><span className="text-[10px] text-muted">📎{ownCtx}</span></Tip>}
        {(ups > 0 || downs > 0) && (
          <Tip content={`${ups ? `depends on ${ups} clip(s)` : ""}${ups && downs ? " · " : ""}${downs ? `used by ${downs} clip(s)` : ""}`}>
            <span className="flex items-center text-info"><Link2 className="h-3 w-3" /></span>
          </Tip>
        )}
        <Tip content={`${node.duration.explain} — ${fmtRange(node.cost.min_usd, node.cost.max_usd)}`}>
          <span className="shrink-0 text-[11px] tabular-nums text-muted">{fmtSec(node.duration.likely_s)}</span>
        </Tip>
        {!isGoal && preview && node.status !== "done" && <Tip content="Only a free placeholder will be made until you add keys"><span className="text-[10px] font-medium text-warn">preview</span></Tip>}
        {!isGoal && (act ? (
          <Tip content={`Working: ${act.step}`}><span aria-label="Working"><Loader2 className="ml-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-brand" /></span></Tip>
        ) : (
          <Tip content={warn ? node.warnings[0] : st.label}>
            <span className={cn("ml-0.5 h-2 w-2 shrink-0 rounded-full", warn && node.status !== "done" ? "bg-warn" : st.dot)} aria-label={st.label} />
          </Tip>
        ))}
        <RowMenu node={node} parentId={parentId} />
      </div>
      {isGoal && open && node.children.map((c) => <Row key={c.id} node={c} depth={depth + 1} drag={drag} setDrag={setDrag} parentId={node.id} />)}
      {isGoal && open && node.children.length === 0 && (
        <div className="py-1 text-[11px] text-muted" style={{ paddingLeft: 40 + depth * 14 }}>
          <button className="text-brand hover:underline" onClick={() => P.act("Breaking down", () => api.decompose(P.pid, node.id), "Broken down into clips")}>Break down with AI</button>
          {" "}or{" "}
          <button className="hover:underline" onClick={() => P.act("Add clip", () => api.addNode(P.pid, { parent_id: node.id, kind: "clip", title: "New clip", goal: "" }))}>add a clip</button>
        </div>
      )}
    </div>
  );
}

function RowMenu({ node, parentId }: { node: Node; parentId: string }) {
  const P = useP();
  const item = "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs outline-none data-[highlighted]:bg-sunken";
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <button aria-label="More" onClick={(e) => e.stopPropagation()} className="grid h-5 w-5 place-items-center rounded text-muted opacity-0 hover:bg-line/60 group-hover:opacity-100 focus:opacity-100">
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="start" className="z-50 min-w-[190px] rounded-xl border border-line bg-panel p-1 shadow-pop" onClick={(e) => e.stopPropagation()}>
          <Menu.Item className={item} onSelect={() => P.act("Breaking down", () => api.decompose(P.pid, node.id), "Broken down with AI")}>
            <Sparkles className="h-3.5 w-3.5 text-brand" />Break down with AI</Menu.Item>
          <Menu.Item className={item} onSelect={async () => {
            const r = await P.act("Add", () => api.addNode(P.pid, { parent_id: node.kind === "goal" ? node.id : parentId, kind: "clip", title: "New clip", goal: "" }));
            if (r) P.select((r as any).new_id);
          }}><Plus className="h-3.5 w-3.5" />{node.kind === "goal" ? "Add clip inside" : "Add clip after"}</Menu.Item>
          <Menu.Item className={item} onSelect={() => P.act("Add", () => api.addNode(P.pid, { parent_id: node.kind === "goal" ? node.id : parentId, kind: "goal", title: "New part", goal: "" }))}>
            <Plus className="h-3.5 w-3.5" />Add sub-part</Menu.Item>
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Item className={cn(item, "text-bad")} onSelect={() => P.act("Delete", () => api.removeNode(P.pid, node.id), "Deleted")}>
            <Trash2 className="h-3.5 w-3.5" />Delete</Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}

function findIn(n: Node, id: string): Node | undefined {
  if (n.id === id) return n;
  for (const c of n.children) { const f = findIn(c, id); if (f) return f; }
  return undefined;
}
