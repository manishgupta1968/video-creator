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
