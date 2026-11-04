import { Background, Connection, Controls, Edge, MarkerType, Node as FlowNode, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api, Dep } from "../api";
import { DEP_TYPES, depLabel, fmtSec, leaves, STATUS, useP } from "../lib";
import { Button, Dialog, Select } from "../ui";

const COLORS: Record<string, string> = { done: "rgb(var(--ok))", needs_pick: "rgb(var(--warn))", failed: "rgb(var(--bad))", generating: "rgb(var(--brand))", stale: "rgb(var(--warn))" };

export default function GraphView({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const P = useP();
  const p = P.view?.project;
  const [pending, setPending] = useState<Connection | null>(null);
  const [type, setType] = useState("continues_from");
  const [edge, setEdge] = useState<Dep | null>(null);

  const { nodes, edges } = useMemo(() => {
    if (!p) return { nodes: [], edges: [] };
    const clips = leaves(p);
    const parts: Record<string, number> = {};
    const nodes: FlowNode[] = clips.map((c, i) => {
      const top = (P.numbers[c.id] || "").split(".")[0];
      parts[top] = (parts[top] ?? -1) + 1;
      return {
        id: c.id, position: { x: (Number(top) - 1) * 230, y: parts[top] * 110 },
        data: { label: (
          <div className="text-left">
            <div className="text-[10px] text-muted">{P.numbers[c.id]} · {fmtSec(c.duration.likely_s)}</div>
            <div className="truncate text-xs font-medium">{c.title}</div>
            <div className="text-[10px]" style={{ color: COLORS[c.status] || "rgb(var(--muted))" }}>{STATUS[c.status].label}</div>
          </div>) },
        style: { width: 190, borderRadius: 12, border: `1.5px solid ${COLORS[c.status] || "rgb(var(--line))"}`, background: "rgb(var(--panel))", color: "rgb(var(--ink))", padding: 8 },
      };
    });
    const edges: Edge[] = p.dependencies.map((d) => ({
      id: d.id, source: d.from_id, target: d.to_id, label: depLabel(d.type), animated: d.type === "continues_from",
      markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: d.type === "continues_from" ? "rgb(var(--info))" : "rgb(var(--muted))" },
      labelStyle: { fontSize: 10, fill: "rgb(var(--ink))" }, labelBgStyle: { fill: "rgb(var(--panel))" },
    }));
    return { nodes, edges };
  }, [p, P.numbers]);

  if (!p) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide="xl" title="Links between clips"
      description="Arrows show what each clip needs from another. Drag from one clip's edge to another to add a link; click an arrow to change or remove it.">
      <div className="h-[60vh] rounded-xl border border-line">
        <ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable onConnect={(c) => setPending(c)}
          onEdgeClick={(_, e) => setEdge(p.dependencies.find((d) => d.id === e.id) || null)}
          onNodeClick={(_, n) => { P.select(n.id); onOpenChange(false); }} proOptions={{ hideAttribution: true }}>
          <Background gap={18} size={1} color="rgb(var(--line))" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <Dialog open={!!pending} onOpenChange={(o) => !o && setPending(null)} title="New link"
        description={pending ? `${P.numbers[pending.target!]} depends on ${P.numbers[pending.source!]}` : ""}
        footer={<><Button variant="ghost" onClick={() => setPending(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { await P.act("Link", () => api.addDep(P.pid, pending!.source!, pending!.target!, type), "Link added"); setPending(null); }}>Add link</Button></>}>
        <Select value={type} onChange={setType} options={DEP_TYPES} className="w-full" />
      </Dialog>
      <Dialog open={!!edge} onOpenChange={(o) => !o && setEdge(null)} title="Link"
        description={edge ? `${P.numbers[edge.from_id]} → ${P.numbers[edge.to_id]} (${edge.source === "ai" ? "found by AI" : edge.source === "rule" ? "added automatically" : "added by you"})` : ""}
        footer={<><Button variant="danger" onClick={async () => { await P.act("Remove", () => api.removeDep(P.pid, edge!.id)); setEdge(null); }}><Trash2 className="h-3.5 w-3.5" />Remove</Button>
          <Button onClick={() => setEdge(null)}>Done</Button></>}>
        {edge && (
          <div className="space-y-2 text-xs">
            <Select value={edge.type} onChange={(t) => P.act("Save", () => api.patchDep(P.pid, edge.id, t)).then(() => setEdge({ ...edge, type: t }))} options={DEP_TYPES} className="w-full" />
            {edge.note && <div className="text-muted">{edge.note}</div>}
            {edge.payload?.handoff_frame ? (<><div className="field-label">What is handed over (last frame)</div><img src={`/files/${P.pid}/${edge.payload.handoff_frame}`} className="rounded-lg" alt="Hand-off frame" /></>)
              : <div className="text-muted">{edge.type === "continues_from" ? "The last frame of the first clip becomes the start of the second, once the first is made." : "Used as context when making the second clip."}</div>}
          </div>
        )}
      </Dialog>
    </Dialog>
  );
}
