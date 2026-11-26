import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Select } from "../ui";

/** A model choice for Claude Code or Codex. The list is read from the program on this computer
 *  (Codex: `codex debug models`; Claude Code: the names its own help gives), never typed in by hand. */
export function SubscriptionModelSelect({ which, value, onChange, title }: { which: "claude_code" | "codex"; value: string; onChange: (v: string) => void; title?: string }) {
  const q = useQuery({ queryKey: ["subscription-models"], queryFn: () => api.subscriptionModels(), staleTime: 300_000 });
  const list = q.data?.[which];
  const options = [{ value: "", label: "its usual model" }, ...(list?.models || []).map((m) => ({ value: m.id, label: m.note ? `${m.name} — ${m.note}` : m.name }))];
  if (value && !options.some((o) => o.value === value)) options.push({ value, label: `${value} (not in its list)` });
  return (
    <span className="inline-flex items-center gap-1.5">
      <Select value={value || ""} onChange={onChange} options={options} title={title || (list?.problem ? `Model list: ${list.problem}` : "Read from the program on this computer")} />
      {q.isLoading && <span className="text-[10px] text-muted">reading its list…</span>}
      {list?.problem && <span className="text-[10px] text-warn">{list.problem}</span>}
    </span>
  );
}

/** How hard Claude Code or Codex thinks (its reasoning effort). The levels come from the program: Claude Code's help
 *  (--effort), Codex's model catalogue (each model's own levels and its default). */
export function EffortSelect({ which, model, value, onChange, usualLabel }: { which: "claude_code" | "codex"; model: string; value: string; onChange: (v: string) => void; usualLabel?: string }) {
  const q = useQuery({ queryKey: ["subscription-models"], queryFn: () => api.subscriptionModels(), staleTime: 300_000 });
  const models = q.data?.[which]?.models || [];
  const chosen = models.find((m) => m.id === model);
  let levels = chosen?.efforts || [];
  if (!chosen) {                     // its usual model: every level any of its models offers
    const seen = new Map<string, string>();
    models.forEach((m) => (m.efforts || []).forEach((e) => { if (!seen.has(e.id)) seen.set(e.id, e.note); }));
    levels = [...seen].map(([id, note]) => ({ id, note }));
  }
  const usual = usualLabel || (chosen?.default_effort ? `its usual effort (${chosen.default_effort})` : "its usual effort");
  const options = [{ value: "", label: usual }, ...levels.map((e) => ({ value: e.id, label: e.note ? `${e.id} — ${e.note}` : e.id }))];
  if (value && !options.some((o) => o.value === value)) options.push({ value, label: `${value} (this model may not offer it)` });
  if (!levels.length && !value) return null;
  return <Select value={value || ""} onChange={onChange} options={options} title="How hard it thinks: higher = more careful, slower, and uses more of your plan's limit" />;
}
