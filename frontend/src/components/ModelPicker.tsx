import { AlertTriangle } from "lucide-react";
import { FoundModel, ModelRow } from "../api";
import { useP, useSettings, useToast } from "../lib";
import { cn, Select, SelectOption } from "../ui";

const CONNECTED = "Connected: ready to use";
const NOT_CONNECTED = "Not connected yet";
const FOUND = "Found at your vendor (not in your catalogue yet)";

/** What a model can do and costs, in one plain line, for under a dropdown. */
export function ModelDetail({ row, shot }: { row?: ModelRow; shot?: string }) {
  if (!row) return null;
  const strength = shot ? (row.strengths?.[shot] ?? row.strengths?.other ?? row.quality) : undefined;
  const bits = [row.note, row.abilities.join(" · "), strength !== undefined && row.job === "video" ? `${strength}/5 for this kind of shot` : "",
    row.draft_cost_usd !== undefined ? (row.draft_cost_usd === 0 ? "free" : row.draft_cost_usd < 0.01 ? "under 1 cent for one plan draft" : `≈ $${row.draft_cost_usd.toFixed(2)} for one plan draft`) : ""].filter(Boolean);
  return (
    <div className="mt-1 space-y-0.5 text-[11px] text-muted">
      <div>{row.price_text}{bits.length ? " · " : ""}{bits.join(" · ")}</div>
      {!row.usable && <div className="flex items-center gap-1 text-warn"><AlertTriangle className="h-3 w-3" />Not connected: {row.why_not}</div>}
      {row.usable && !row.is_free && !row.price_verified && row.job !== "video" && (
        <div className="flex items-center gap-1 text-warn"><AlertTriangle className="h-3 w-3" />This price is not checked with the vendor yet. Check it on the vendor's page (Settings → Model catalogue).</div>
      )}
    </div>
  );
}

/** A dropdown of EVERY model of one or more kinds (video, picture, voice …), connected or not. A model that is not connected is
 *  listed with what is missing; choosing it opens Settings instead of failing later. `value` "" = Auto. */
export default function ModelPicker({ jobs, value, onChange, autoLabel, shot, title = "Model", help, className, showDetail = true }: {
  jobs: string[]; value: string; onChange: (id: string) => void; autoLabel?: string; shot?: string; title?: string; help?: string; className?: string; showDetail?: boolean;
}) {
  const P = useP();
  const toast = useToast();
  const rows: ModelRow[] = ((useSettings().data?.catalog || []) as ModelRow[]).filter((r) => jobs.includes(r.job));
  const label = (r: ModelRow) => {
    const strength = shot && r.job === "video" ? ` · ${r.strengths?.[shot] ?? r.strengths?.other ?? r.quality}/5` : "";
    return `${r.id} · ${r.price_text}${strength}${r.usable ? "" : ` — ${r.why_not}`}`;
  };
  const options: SelectOption[] = [
    ...(autoLabel !== undefined ? [{ value: "", label: autoLabel }] : []),
    ...rows.filter((r) => r.usable).map((r) => ({ value: r.id, label: label(r), group: CONNECTED })),
    ...rows.filter((r) => !r.usable).map((r) => ({ value: r.id, label: label(r), group: NOT_CONNECTED })),
  ];
  if (value && !rows.some((r) => r.id === value)) options.push({ value, label: `${value} (not in the catalogue)`, group: CONNECTED });
  const picked = rows.find((r) => r.id === value);
  const pinnedFree = !!picked?.is_free;
  return (
    <div className={cn("inline-block", className)}>
      <Select help={help} title={title} value={value} className={cn("max-w-full", pinnedFree && "border-warn")} options={options}
        onChange={(v) => {
          const r = rows.find((x) => x.id === v);
          if (r && !r.usable) {
            toast({ text: `${r.id} is not connected (${r.why_not}). Add what is missing in Settings.`, tone: "info" });
            P.openSettings("keys");
            return;
          }
          onChange(v);
        }} />
      {showDetail && picked && <ModelDetail row={picked} shot={shot} />}
    </div>
  );
}

/** The AI brain dropdown used in Settings: every brain model with its price and what one plan draft costs.
 *  value: "auto" | "same" | "plugin:model". Models found at the vendor (not in the catalogue yet) come last. */
export function BrainPicker({ value, onPick, onFound, onUnusable, found = [], autoLabel, sameLabel, title }: {
  value: string; onPick: (value: string, row?: ModelRow) => void; onFound: (m: FoundModel) => void; onUnusable: (row: ModelRow) => void;
  found?: FoundModel[]; autoLabel?: string; sameLabel?: string; title: string;
}) {
  const rows: ModelRow[] = ((useSettings().data?.catalog || []) as ModelRow[]).filter((r) => r.job === "llm");
  const key = (r: ModelRow) => `${r.plugin}:${r.model}`;
  const draft = (r: ModelRow) => (!r.draft_cost_usd ? "" : r.draft_cost_usd < 0.01 ? " · under 1 cent a draft" : ` · ≈ $${r.draft_cost_usd.toFixed(2)} a draft`);
  const label = (r: ModelRow) => (r.is_free ? "Offline brain · free · simple rules, no AI" : `${r.model} · ${r.vendor} · ${r.price_text}${draft(r)}${r.usable ? "" : ` — ${r.why_not}`}`);
  const options: SelectOption[] = [
    ...(autoLabel ? [{ value: "auto", label: autoLabel }] : []),
    ...(sameLabel ? [{ value: "same", label: sameLabel }] : []),
    ...rows.filter((r) => r.usable).map((r) => ({ value: key(r), label: label(r), group: CONNECTED })),
    ...rows.filter((r) => !r.usable).map((r) => ({ value: key(r), label: label(r), group: NOT_CONNECTED })),
    ...found.filter((m) => !m.in_catalogue && m.plugin).map((m) => ({ value: `found:${m.plugin}:${m.id}`, label: `${m.id} · ${m.plugin} · price not in your catalogue`, group: FOUND })),
  ];
  if (!options.some((o) => o.value === value)) options.push({ value, label: value.replace(":", " · "), group: CONNECTED });
  const picked = rows.find((r) => key(r) === value);
  return (
    <div>
      <Select title={title} value={value} className="w-[30rem] max-w-full" options={options}
        onChange={(v) => {
          if (v.startsWith("found:")) {
            const [, plugin, ...rest] = v.split(":");
            const m = found.find((f) => f.plugin === plugin && f.id === rest.join(":"));
            if (m) onFound(m);
            return;
          }
          const r = rows.find((x) => key(x) === v);
          if (r && !r.usable) { onUnusable(r); return; }
          onPick(v, r);
        }} />
      <ModelDetail row={picked} />
    </div>
  );
}
