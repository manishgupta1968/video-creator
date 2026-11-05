import { ExternalLink, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api, Ctx, StockPhoto } from "../api";
import { useP } from "../lib";
import { Badge, Button, Dialog, Empty, Input, Select } from "../ui";

export default function StockSearch({ item, open, onOpenChange }: { item: Ctx | undefined; open: boolean; onOpenChange: (v: boolean) => void }) {
  const P = useP();
  const [q, setQ] = useState("");
  const [source, setSource] = useState("wikimedia");
  const [sources, setSources] = useState<string[]>(["wikimedia"]);
  const [results, setResults] = useState<StockPhoto[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<string>("");
  const isPerson = item?.type === "actor" && (!item.actor || ["ai_person", "real_person", "digital_twin"].includes(item.actor.kind));

  useEffect(() => {
    if (open && item) { setQ(item.title === "Photo" ? "" : (item.actor?.description || item.title || "").split(/[.,;]/)[0].slice(0, 60)); setResults(null); setError(""); }
  }, [open, item?.id]); // eslint-disable-line

  const search = async () => {
    if (!q.trim()) return;
    setLoading(true); setError("");
    try {
      const r = await api.stockSearch(q.trim(), source);
      setResults(r.results); setSources(r.sources);
    } catch (e: any) { setError(e.message); setResults([]); }
    setLoading(false);
  };
  if (!item) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide="xl" title={`Find a photo for ${item.title}`}
      description="Real photos with their licence. Choose one and it becomes the picture the tool starts from.">
      {isPerson ? (
        <Empty title="Photos of people must be uploaded">Photos of a person must be your own, or used with that person's permission. Upload a photo instead. Photo search is for animals, objects, places and styles.</Empty>
      ) : (
        <div className="space-y-3">
          <div className="flex gap-2">
            <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} placeholder="e.g. male lion savannah" aria-label="Search photos" />
            <Select value={source} onChange={setSource} options={sources.map((s) => ({ value: s, label: s === "wikimedia" ? "Wikimedia Commons" : "Pexels" }))} className="h-8" />
            <Button variant="primary" onClick={search} loading={loading}><Search className="h-3.5 w-3.5" />Search</Button>
          </div>
          <p className="text-[11px] text-muted">Check each photo's licence. Many need a credit; the tool saves the credits to a file next to your final video.</p>
          {error && <div className="rounded-lg bg-bad/10 px-3 py-2 text-xs text-bad">{error}</div>}
          {results && results.length === 0 && !error && <Empty title="No photos found">Try a simpler word, for example "lion".</Empty>}
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {(results || []).map((r) => (
              <div key={r.url} className="overflow-hidden rounded-xl border border-line">
                <img src={r.thumb} alt={r.title} loading="lazy" className="aspect-[4/3] w-full object-cover" />
                <div className="space-y-1 p-2 text-[11px]">
                  <div className="truncate font-medium" title={r.title}>{r.title}</div>
                  <div className="flex flex-wrap items-center gap-1"><Badge tone="info">{r.license}</Badge><span className="truncate text-muted" title={r.author}>{r.author}</span></div>
                  <div className="flex items-center gap-1.5">
                    <Button size="sm" variant="primary" className="flex-1" loading={adding === r.url}
                      onClick={async () => {
                        setAdding(r.url);
                        const ok = await P.act("Adding photo", () => api.stockAdd(P.pid, item.id, r), "Photo added");
                        setAdding("");
                        if (ok) onOpenChange(false);
                      }}>Use this photo</Button>
                    {r.source_url && <a href={r.source_url} target="_blank" rel="noreferrer" aria-label="Open the photo's page" className="text-muted hover:text-ink"><ExternalLink className="h-3.5 w-3.5" /></a>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Dialog>
  );
}
