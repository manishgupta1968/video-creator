import { useState } from "react";
import { api } from "../api";
import { CTX_TYPES, useP } from "../lib";
import { Button, cn, Dialog, DropZone, Empty } from "../ui";
import { ContextCard } from "./ContextCard";

export default function ContextLibrary({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const P = useP();
  const p = P.view?.project;
  const [type, setType] = useState("all");
  if (!p) return null;
  const items = p.context.filter((c) => type === "all" || c.type === type);
  const where = (scope: string) => {
    if (scope === "project") return "shared";
    const id = scope.split(":")[1];
    return `node:${P.numbers[id] || "?"}`;
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide="xl" title="Context library"
      description="Everything that guides the video: actors, objects, brand, locations, style, sounds and notes — shared or for specific clips.">
      <div className="mb-3 flex flex-wrap gap-1">
        {[{ value: "all", label: "All" }, ...CTX_TYPES].map((t) => (
          <button key={t.value} onClick={() => setType(t.value)}
            className={cn("rounded-full px-2.5 py-1 text-xs", type === t.value ? "bg-brand/10 font-medium text-brand" : "text-muted hover:bg-sunken")}>
            {t.label} <span className="opacity-60">{t.value === "all" ? p.context.length : p.context.filter((c) => c.type === t.value).length}</span>
          </button>
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((c) => <ContextCard key={c.id} item={c} origin={where(c.scope)} />)}
        <DropZone label="Drop files to add shared context" onFiles={(files) => P.act("Upload", () => api.upload(P.pid, files, { scope: "project" }), "Added")} />
      </div>
      {items.length === 0 && <Empty title="Nothing here yet">Drop photos, voice recordings, logos, music or notes. Text-only descriptions work too.</Empty>}
      <div className="mt-3 flex gap-2">
        <Button size="sm" onClick={() => P.act("Add actor", () => api.addContext(P.pid, { type: "actor", role: "must_appear", title: "New actor", scope: "project" }), "Actor added")}>+ Actor (text only)</Button>
        <Button size="sm" onClick={() => P.act("Add", () => api.addContext(P.pid, { type: "entity", role: "must_appear", title: "Brand", scope: "project" }))}>+ Brand</Button>
        <Button size="sm" onClick={() => P.act("Add", () => api.addContext(P.pid, { type: "style", role: "look_reference", title: "Style", scope: "project" }))}>+ Style</Button>
        <Button size="sm" onClick={() => P.act("Add", () => api.addContext(P.pid, { type: "text", role: "knowledge", title: "Facts to say", scope: "project" }))}>+ Facts / brief</Button>
      </div>
    </Dialog>
  );
}
