import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Clapperboard, FileText, Film, HelpCircle, Image as ImageIcon, Mic, Paperclip, Settings2, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useToast } from "../lib";
import { Badge, Button, Card, cn, DropZone, HelpTip, Select, Tip } from "../ui";
import HelpDrawer from "./HelpDrawer";
import SettingsDialog from "./Settings";

const LENGTHS = [{ s: 15, l: "15 s" }, { s: 30, l: "30 s" }, { s: 60, l: "1 min" }, { s: 120, l: "2 min" }, { s: 300, l: "5 min" }];
const EXAMPLES = [
  "A 2-minute video that shows a lion being chased by a deer with long horns",
  "A 30-second advert for our lightweight travel bag, presented by me",
  "A 1-minute explainer of our product using my slides, with a friendly narrator",
];

function fileIcon(f: File) {
  const t = f.type;
  if (t.startsWith("image")) return <ImageIcon className="h-3.5 w-3.5" />;
  if (t.startsWith("audio")) return <Mic className="h-3.5 w-3.5" />;
  if (t.startsWith("video")) return <Film className="h-3.5 w-3.5" />;
  return <FileText className="h-3.5 w-3.5" />;
}

export default function Start({ onOpen }: { onOpen: (id: string) => void }) {
  const [goal, setGoal] = useState("");
  const [seconds, setSeconds] = useState(60);
  const [aspect, setAspect] = useState("16:9");
  const [mode, setMode] = useState("balanced");
  const [files, setFiles] = useState<File[]>([]);
  const [creating, setCreating] = useState(false);
  const [settings, setSettings] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "?" && !(t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable))) { e.preventDefault(); setHelpOpen(true); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  const ref = useRef<HTMLTextAreaElement>(null);
  const toast = useToast();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  const onGoal = (text: string) => {
    setGoal(text);
    // "30-second", "2 minute", "90 sec" in the goal sets the length automatically
    const m = text.match(/(\d+(?:\.\d+)?)\s*-?\s*(seconds?|secs?|s\b|minutes?|mins?)/i);
    if (m) {
      const n = parseFloat(m[1]) * (/^m/i.test(m[2]) ? 60 : 1);
      if (n >= 5 && n <= 3600) setSeconds(n);
    }
  };

  const create = async () => {
    if (!goal.trim()) { ref.current?.focus(); return; }
    setCreating(true);
    try {
      const fd = new FormData();
      fd.append("goal", goal.trim());
      fd.append("seconds", String(seconds));
      fd.append("aspect", aspect);
      fd.append("quality_mode", mode);
      files.forEach((f) => fd.append("files", f));
      const r = await api.create(fd);
      onOpen(r.id);
    } catch (e: any) {
      toast({ text: e.message, tone: "bad" });
      setCreating(false);
    }
  };

  return (
    <div className="min-h-full overflow-auto">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2 font-semibold">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-brand-ink"><Clapperboard className="h-4 w-4" /></span>
          video-generator
        </div>
        <div className="flex items-center gap-2">
          {health.data && <Badge tone={health.data.brain === "fake_llm" ? "warn" : "ok"} title="The AI that plans and reviews">
            AI brain: {health.data.brain === "fake_llm" ? "offline (free)" : health.data.brain}</Badge>}
          <Button variant="ghost" help="help" onClick={() => setHelpOpen(true)}><HelpCircle className="h-4 w-4" />Help</Button>
          <Button variant="ghost" help="settings" onClick={() => setSettings(true)}><Settings2 className="h-4 w-4" />Settings</Button>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 pb-16 pt-10">
        <h1 className="text-center text-3xl font-semibold tracking-tight">What video do you want to make?</h1>
        <p className="mt-2 text-center text-sm text-muted">Describe your goal. You get a complete draft — parts, clips, scripts, actors, cost and time — to edit before anything is paid for.</p>

        <Card className="mt-8 p-1.5">
          <DropZone onFiles={(f) => setFiles((x) => [...x, ...f])} className="border-0 p-0 text-left hover:bg-transparent cursor-default" label="">
            <div onClick={(e) => e.stopPropagation()}>
              <textarea ref={ref} autoFocus data-help="goal-box" aria-describedby="goal-hint" value={goal} onChange={(e) => onGoal(e.target.value)} rows={3}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); create(); } }}
                placeholder="e.g. A 30-second advert for our new travel bag, presented by me…"
                className="w-full resize-none rounded-xl bg-transparent px-4 pt-3.5 text-[15px] text-ink placeholder:text-muted/60 focus:outline-none" />
              {files.length > 0 && (
                <div className="flex flex-wrap gap-1.5 px-3 pb-2">
                  {files.map((f, i) => (
                    <span key={i} className="inline-flex items-center gap-1 rounded-md bg-sunken px-2 py-1 text-xs">
                      {fileIcon(f)}{f.name}
                      <button aria-label={`Remove ${f.name}`} onClick={() => setFiles((x) => x.filter((_, j) => j !== i))}><X className="h-3 w-3 text-muted" /></button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2">
                <HelpTip id="attach-files">
                  <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted hover:bg-sunken hover:text-ink">
                    <Paperclip className="h-3.5 w-3.5" /> Add photos, slides, clips, voice
                    <input type="file" multiple hidden onChange={(e) => setFiles((x) => [...x, ...Array.from(e.target.files || [])])} />
                  </label>
                </HelpTip>
                <div className="mx-1 h-4 w-px bg-line" />
                <HelpTip id="length-picker"><div className="flex items-center gap-0.5" role="radiogroup" aria-label="Length">
                  {!LENGTHS.some((l) => l.s === seconds) && <span className="rounded-md bg-brand/10 px-2 py-1 text-xs font-medium text-brand">{seconds >= 60 ? `${+(seconds / 60).toFixed(1)} min` : `${seconds} s`}</span>}
                  {LENGTHS.map((l) => (
                    <button key={l.s} role="radio" aria-checked={seconds === l.s} onClick={() => setSeconds(l.s)}
                      className={cn("rounded-md px-2 py-1 text-xs", seconds === l.s ? "bg-brand/10 font-medium text-brand" : "text-muted hover:bg-sunken")}>{l.l}</button>
                  ))}
                </div></HelpTip>
                <Select value={aspect} onChange={setAspect} title="Shape" help="shape-picker" options={[
                  { value: "16:9", label: "16:9 wide" }, { value: "9:16", label: "9:16 vertical" }, { value: "1:1", label: "1:1 square" }]} />
                <Select value={mode} onChange={setMode} title="Quality" help="quality-picker" options={[
                  { value: "best", label: "Best quality" }, { value: "balanced", label: "Balanced" },
                  { value: "budget", label: "Budget" }, { value: "free", label: "Free preview" }]} />
                <div className="flex-1" />
                <Button variant="primary" size="lg" help="create-draft" onClick={create} loading={creating} className="h-9">
                  <Sparkles className="h-4 w-4" />Create draft<ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </DropZone>
        </Card>
        <p id="goal-hint" className="mt-2 text-center text-[11px] text-muted">Press Enter to create · drop files anywhere on the box · nothing is paid for until you approve</p>

        {!goal && (
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {EXAMPLES.map((e) => (
              <button key={e} onClick={() => onGoal(e)} className="rounded-full border border-line px-3 py-1.5 text-xs text-muted hover:border-brand/50 hover:text-ink">{e}</button>
            ))}
          </div>
        )}

        {(projects.data?.length || 0) > 0 && (
          <section className="mt-14">
            <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-muted">Recent projects</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {projects.data!.map((p) => (
                <Card key={p.id} className="group flex cursor-pointer items-start gap-3 p-3.5 hover:border-brand/40" onClick={() => onOpen(p.id)}>
                  <div className="grid h-10 w-14 shrink-0 place-items-center rounded-md bg-sunken text-muted">
                    {p.final_output ? <Film className="h-4 w-4 text-ok" /> : <Clapperboard className="h-4 w-4" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{p.name}</div>
                    <div className="truncate text-xs text-muted">{p.goal}</div>
                    <div className="mt-1 text-[11px] text-muted/80">{new Date(p.updated_at).toLocaleString()}</div>
                  </div>
                  <button aria-label="Delete project" className="opacity-0 group-hover:opacity-100 text-muted hover:text-bad"
                    onClick={async (e) => { e.stopPropagation(); if (confirm(`Delete “${p.name}” and its files?`)) { await api.remove(p.id); projects.refetch(); } }}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </Card>
              ))}
            </div>
          </section>
        )}
      </main>
      <SettingsDialog open={settings} onOpenChange={setSettings} />
      <HelpDrawer open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  );
}
