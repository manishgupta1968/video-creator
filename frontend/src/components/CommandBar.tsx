import * as DialogP from "@radix-ui/react-dialog";
import { ArrowRight, Check, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api, CommandPlan } from "../api";
import { findNode, useP } from "../lib";
import { Button } from "../ui";

const EXAMPLES = ["make the hook shorter", "give Priya a blue kurta in all clips", "generate the next clip", "Why does this cost $0.23?"];
const QUESTION = /\?\s*$|^\s*(what|why|how|when|where|which|who|is|are|can|could|does|do|will|should|explain|tell me|show me how)\b/i;

export default function CommandBar({ open, onOpenChange, initialText }: { open: boolean; onOpenChange: (v: boolean) => void; initialText?: string }) {
  const P = useP();
  const [text, setText] = useState("");
  const [plan, setPlan] = useState<CommandPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  useEffect(() => { if (!open) { setPlan(null); setText(""); setAnswer(null); } else { setText(initialText || ""); setPlan(null); setAnswer(null); } }, [open]); // eslint-disable-line
  const isQuestion = QUESTION.test(text);
  const focus = P.view && P.selected !== P.view.project.root.id ? P.selected : undefined;
  const focusNode = P.view && focus ? findNode(P.view.project, focus) : undefined;

  const ask = async () => {
    if (!text.trim()) return;
    if (isQuestion) {
      setLoading(true);
      try { setAnswer((await api.explain(P.pid, text.trim(), focus)).answer); }
      catch (e: any) { setAnswer(`Sorry, I could not answer: ${e.message}`); }
      setLoading(false);
      return;
    }
    setLoading(true);
    const r = await P.act("Thinking", () => api.planCommand(P.pid, text.trim(), focus));
    setLoading(false);
    if (r) setPlan(r as CommandPlan);
  };
  const apply = async () => {
    setLoading(true);
    const r = await P.act("Applying", () => api.applyCommand(P.pid, plan!), "Done — Ctrl+Z to undo");
    setLoading(false);
    if (r) onOpenChange(false);
  };
  return (
    <DialogP.Root open={open} onOpenChange={onOpenChange}>
      <DialogP.Portal>
        <DialogP.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <DialogP.Content className="fixed left-1/2 top-[18%] z-50 w-[calc(100vw-32px)] max-w-xl -translate-x-1/2 rounded-2xl border border-line bg-panel shadow-pop" aria-describedby={undefined}>
          <DialogP.Title className="sr-only">Ask AI</DialogP.Title>
          <div className="flex items-center gap-2 border-b border-line px-4">
            <Sparkles className="h-4 w-4 text-brand" />
            <input autoFocus value={text} onChange={(e) => { setText(e.target.value); setPlan(null); setAnswer(null); }} onKeyDown={(e) => e.key === "Enter" && (plan && !isQuestion ? apply() : ask())}
              placeholder={focusNode ? `Change something, or ask a question (focus: ${P.numbers[focusNode.id]} ${focusNode.title})` : "Change something, or ask a question about your project…"}
              className="h-12 flex-1 bg-transparent text-sm placeholder:text-muted/70 focus:outline-none" aria-label="Command" />
            <Button size="sm" variant="primary" onClick={plan && !isQuestion ? apply : ask} loading={loading} disabled={!text.trim()}>
              {plan && !isQuestion ? <><Check className="h-3.5 w-3.5" />Apply</> : isQuestion ? "Ask" : <ArrowRight className="h-3.5 w-3.5" />}
            </Button>
          </div>
          <div className="px-4 py-3 text-xs" aria-live="polite">
            {answer ? (
              <div className="space-y-2">
                <div className="field-label">Answer from your project's own numbers</div>
                <div className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-sunken/70 p-3 text-[13px] leading-relaxed scroll-thin">{answer}</div>
                <div className="text-muted">Want a change instead? Type it as an instruction, for example “make the hook shorter”.</div>
              </div>
            ) : isQuestion && text.trim() ? (
              <div className="text-muted">That looks like a question. Press Enter and I will answer it from your project. Nothing will be changed.</div>
            ) : plan ? (
              <div className="space-y-2">
                <div className="font-medium">{plan.summary}</div>
                <ul className="space-y-1">
                  {plan.ops.map((o, i) => (
                    <li key={i} className="rounded-lg bg-sunken px-2.5 py-1.5"><span className="font-medium">{o.op.replace(/_/g, " ")}</span> {o.target && <span className="text-muted">· {o.target}</span>} {o.field && <span className="text-muted">· {o.field}</span>} {o.value && <span>→ {o.value}</span>}</li>
                  ))}
                </ul>
                <div className="text-muted">Press Enter to apply. You can undo with Ctrl+Z.</div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {EXAMPLES.map((e) => <button key={e} onClick={() => setText(e)} className="rounded-full border border-line px-2.5 py-1 text-muted hover:text-ink">{e}</button>)}
              </div>
            )}
          </div>
        </DialogP.Content>
      </DialogP.Portal>
    </DialogP.Root>
  );
}
