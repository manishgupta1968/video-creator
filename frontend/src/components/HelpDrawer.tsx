import { BookOpen, Eye, HelpCircle, Keyboard, Loader2, Send, Sparkles } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { GUIDES, SHORTCUTS } from "../helpContent";
import { useToast } from "../lib";
import { Button, cn, Dialog, Input, spotlight } from "../ui";
import { replayTour } from "./Tour";

const EXAMPLE_QUESTIONS = [
  "Why does the budget show a cost?",
  "What is left to spend?",
  "Why was this model chosen for clip 1.1?",
  "How long will the rest take?",
];

/** Step-by-step guides. Each step has a "Show me" button that points at the real control. */
export default function HelpDrawer({ open, onOpenChange, pid }: { open: boolean; onOpenChange: (v: boolean) => void; pid?: string }) {
  const [guideId, setGuideId] = useState(GUIDES[0].id);
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);
  const toast = useToast();
  const guide = GUIDES.find((g) => g.id === guideId)!;

  const show = (id: string) => {
    onOpenChange(false);
    setTimeout(() => {
      if (!spotlight(id)) toast({ text: pid ? "That control is not on this screen right now. Open the clip or part it belongs to." : "Open a project first, then use Show me.", tone: "info" });
    }, 250);
  };
  const ask = async (text = q) => {
    if (!pid || !text.trim()) return;
    setAsking(true); setAnswer("");
    try { setAnswer((await api.explain(pid, text.trim())).answer); }
    catch (e: any) { setAnswer(`Sorry, I could not answer: ${e.message}`); }
    setAsking(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide="xl" title="Help" description="Pick what you want to do. Each step says what you will get, and “Show me” points at the exact button.">
      <div className="grid gap-5 md:grid-cols-[230px_1fr]">
        <nav aria-label="Guides" className="space-y-0.5">
          {GUIDES.map((g) => (
            <button key={g.id} onClick={() => setGuideId(g.id)} aria-current={g.id === guideId}
              className={cn("flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition-colors", g.id === guideId ? "bg-brand/10 font-medium text-brand" : "text-ink hover:bg-sunken")}>
              <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0" />{g.title}
            </button>
          ))}
          <div className="my-2 h-px bg-line" />
          <button onClick={() => { onOpenChange(false); setTimeout(replayTour, 250); }} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs hover:bg-sunken">
            <Eye className="h-3.5 w-3.5" />Take the quick tour again
          </button>
        </nav>

        <div className="min-w-0 space-y-5">
          <section aria-labelledby="guide-title">
            <h3 id="guide-title" className="text-[15px] font-semibold">{guide.title}</h3>
            <p className="mt-1 rounded-lg bg-ok/10 px-3 py-2 text-xs text-ok"><b>You will get:</b> {guide.achieve}</p>
            <ol className="mt-3 space-y-2.5">
              {guide.steps.map((s, i) => (
                <li key={i} className="flex gap-3 text-[13px]">
                  <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand/10 text-[11px] font-semibold text-brand">{i + 1}</span>
                  <span className="flex-1">{s.text}</span>
                  {s.show && <Button size="sm" variant="outline" onClick={() => show(s.show!)}><HelpCircle className="h-3.5 w-3.5" />Show me</Button>}
                </li>
              ))}
            </ol>
          </section>

          <section aria-labelledby="ask-title" className="rounded-xl border border-line p-3">
            <h3 id="ask-title" className="flex items-center gap-2 text-[13px] font-semibold"><Sparkles className="h-4 w-4 text-brand" />Ask a question about your project</h3>
            {pid ? (
              <>
                <p className="mt-1 text-xs text-muted">Answers come from your project's own numbers: costs, lengths, models, reviews and settings.</p>
                <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(); }}>
                  <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Why does this clip cost so much?" aria-label="Your question" />
                  <Button variant="primary" type="submit" loading={asking} disabled={!q.trim()}><Send className="h-3.5 w-3.5" />Ask</Button>
                </form>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {EXAMPLE_QUESTIONS.map((e) => <button key={e} onClick={() => { setQ(e); ask(e); }} className="rounded-full border border-line px-2.5 py-1 text-[11px] text-muted hover:text-ink">{e}</button>)}
                </div>
                <div aria-live="polite" className="mt-3">
                  {asking && <div className="flex items-center gap-2 text-xs text-muted"><Loader2 className="h-3.5 w-3.5 animate-spin" />Looking at your project…</div>}
                  {answer && <div className="whitespace-pre-wrap rounded-lg bg-sunken/70 p-3 text-[13px] leading-relaxed">{answer}</div>}
                </div>
              </>
            ) : <p className="mt-1 text-xs text-muted">Open a project to ask questions about it.</p>}
          </section>

          <section aria-labelledby="keys-title">
            <h3 id="keys-title" className="flex items-center gap-2 text-[13px] font-semibold"><Keyboard className="h-4 w-4" />Keyboard shortcuts</h3>
            <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
              {SHORTCUTS.map(([k, d]) => <div key={k} className="flex items-center justify-between gap-3"><dt className="text-muted">{d}</dt><dd><kbd className="rounded bg-sunken px-1.5 py-0.5 text-[11px]">{k}</kbd></dd></div>)}
            </dl>
          </section>
        </div>
      </div>
    </Dialog>
  );
}
