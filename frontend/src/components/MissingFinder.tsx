import { Search, Plus } from "lucide-react";
import { useState } from "react";
import { api, MissingItem } from "../api";
import { useP, useToast } from "../lib";
import { Badge, Button } from "../ui";

const TYPE_WORD: Record<string, string> = { actor: "Character", location: "Place", object: "Object" };

/** Reads every clip (script, actors, 3D scene) and lists the characters, places and objects the clips need that are not
 *  defined yet; you tick what to add. Each added item can then get its picture ("Make a picture with Codex"). */
export default function MissingFinder() {
  const P = useP();
  const toast = useToast();
  const [found, setFound] = useState<{ items: MissingItem[]; note: string } | null>(null);
  const [pick, setPick] = useState<Record<number, boolean>>({});
  const looking = P.busy.includes("Find missing");
  const find = async () => {
    const r = await P.act("Find missing", () => api.findMissing(P.pid));
    if (r) { setFound(r); setPick(Object.fromEntries(r.items.map((_, i) => [i, true]))); }
  };
  const add = async () => {
    if (!found) return;
    const items = found.items.filter((_, i) => pick[i]);
    const r = await P.act("Add missing", () => api.addMissing(P.pid, items));
    if (r) {
      P.set(r);
      setFound(null);
      toast({ text: r.added.length ? `Added: ${r.added.join(", ")}. Open each to check its description and make its picture. `
        + "To put new places and objects into the 3D scenes, use “Plan every scene again” (Whole video → Whole 3D film)." : "Nothing new was added.", tone: "ok" });
    }
  };
  return (
    <div className="space-y-1.5 rounded-lg border border-line p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">What do the clips still need?</span>
        <div className="flex-1" />
        <Button size="sm" variant="outline" loading={looking} onClick={find}><Search className="h-3.5 w-3.5" />Find missing characters, places and objects</Button>
      </div>
      <p className="text-[11px] text-muted">The AI brain reads every clip (its script and its 3D scene) and lists what is not defined here yet.</p>
      {found && (
        <div className="space-y-1.5">
          {found.items.length === 0 && <p className="text-ok">{found.note || "Nothing is missing."}</p>}
          {found.items.map((it, i) => (
            <label key={i} className="flex cursor-pointer items-start gap-2 rounded-md bg-sunken p-2">
              <input type="checkbox" className="mt-0.5" checked={!!pick[i]} onChange={(e) => setPick({ ...pick, [i]: e.target.checked })} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5"><Badge tone="info">{TYPE_WORD[it.type] || it.type}</Badge><span className="font-medium">{it.title}</span>
                  {it.clips.length > 0 && <span className="text-[10px] text-muted">clip {it.clips.join(", ")}</span>}</div>
                {it.description && <div className="mt-0.5">{it.description}</div>}
                {it.why && <div className="text-[10px] text-muted">{it.why}</div>}
              </div>
            </label>
          ))}
          {found.items.length > 0 && (
            <Button size="sm" variant="primary" disabled={!Object.values(pick).some(Boolean)} loading={P.busy.includes("Add missing")} onClick={add}>
              <Plus className="h-3.5 w-3.5" />Add the ticked ones
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
