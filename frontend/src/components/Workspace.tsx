import { ArrowLeft, Command, Download, GitBranch, Library, Loader2, Moon, Redo2, Settings2, Sun, Undo2 } from "lucide-react";
import { useCallback, useState } from "react";
import { api, fileUrl } from "../api";
import { useTheme } from "../App";
import { findNode, fmtSec, fmtUsd, ProjectProvider, useHotkey, useP } from "../lib";
import { Badge, Button, Editable, Meter, Tip } from "../ui";
import CommandBar from "./CommandBar";
import { RunProvider } from "./ConfirmRun";
import ContextLibrary from "./ContextLibrary";
import Editor from "./Editor";
import GraphView from "./GraphView";
import Inspector from "./Inspector";
import SettingsDialog from "./Settings";
import StoryTree from "./StoryTree";
import Timeline from "./Timeline";
import Tour from "./Tour";

export default function Workspace({ pid, onHome }: { pid: string; onHome: () => void }) {
  return (
    <ProjectProvider pid={pid}>
      <RunProvider>
        <Shell onHome={onHome} />
      </RunProvider>
    </ProjectProvider>
  );
}

function Shell({ onHome }: { onHome: () => void }) {
  const P = useP();
  const [cmd, setCmd] = useState(false);
  const [graph, setGraph] = useState(false);
  const [library, setLibrary] = useState(false);
  const [settings, setSettings] = useState(false);
  const [theme, setTheme] = useTheme();
  useHotkey(useCallback((e) => (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k", []), () => setCmd(true), true);
  useHotkey(useCallback((e) => (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z" && !e.shiftKey, []),
    () => P.act("Undo", () => api.undo(P.pid)));
  useHotkey(useCallback((e) => (e.metaKey || e.ctrlKey) && ((e.key.toLowerCase() === "z" && e.shiftKey) || e.key.toLowerCase() === "y"), []),
    () => P.act("Redo", () => api.redo(P.pid)));

  const v = P.view;
  if (!v) {
    return (
      <div className="grid h-full place-items-center text-muted">
        <div className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />Opening project…</div>
      </div>
    );
  }
  const p = v.project;
  const s = v.summary;
  const drafting = P.busy.some((b) => b.startsWith("Drafting"));
  const node = findNode(p, P.selected);
  const dark = document.documentElement.classList.contains("dark");

  return (
    <div className="flex h-full flex-col">
      {/* top bar */}
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-panel px-3">
        <Tip content="All projects"><Button variant="ghost" size="icon" onClick={onHome} aria-label="All projects"><ArrowLeft className="h-4 w-4" /></Button></Tip>
        <Editable value={p.name} onSave={(name) => P.act("Rename", () => api.patch(P.pid, { name }))}
          className="max-w-[28ch] truncate text-sm font-semibold" ariaLabel="Project name" />
        <Tip content="The AI that plans, writes and reviews. Change it in Settings.">
          <span><Badge tone={s.brain === "fake_llm" ? "warn" : "brand"}>AI: {s.brain === "fake_llm" ? "offline" : s.brain}</Badge></span>
        </Tip>
        <div className="flex-1" />
        <Tip content={`Spent ${fmtUsd(s.spent)} of your ${fmtUsd(s.budget)} budget. Estimated still to spend: ${fmtUsd(s.cost)}.`}>
          <div className="hidden w-44 items-center gap-2 md:flex" aria-label="Budget">
            <span className="text-[11px] text-muted whitespace-nowrap">Budget {fmtUsd(s.spent)}/{fmtUsd(s.budget)}</span>
            <Meter value={s.spent + s.cost} max={s.budget} />
          </div>
        </Tip>
        <Button variant="outline" size="sm" onClick={() => setCmd(true)} className="hidden sm:inline-flex text-muted">
          <Command className="h-3.5 w-3.5" />Ask AI… <kbd className="ml-1 rounded bg-sunken px-1 text-[10px]">Ctrl K</kbd>
        </Button>
        <Tip content="Undo (Ctrl+Z)"><Button variant="ghost" size="icon" aria-label="Undo" onClick={() => P.act("Undo", () => api.undo(P.pid))}><Undo2 className="h-4 w-4" /></Button></Tip>
        <Tip content="Redo (Ctrl+Shift+Z)"><Button variant="ghost" size="icon" aria-label="Redo" onClick={() => P.act("Redo", () => api.redo(P.pid))}><Redo2 className="h-4 w-4" /></Button></Tip>
        <Tip content="Links between clips (graph)"><Button variant="ghost" size="icon" aria-label="Graph" onClick={() => setGraph(true)}><GitBranch className="h-4 w-4" /></Button></Tip>
        <Tip content="Context library: every actor, photo, sound and note"><Button variant="ghost" size="icon" aria-label="Context library" onClick={() => setLibrary(true)}><Library className="h-4 w-4" /></Button></Tip>
        <Tip content="Light / dark"><Button variant="ghost" size="icon" aria-label="Theme" onClick={() => setTheme(dark ? "light" : "dark")}>{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button></Tip>
        <Tip content="Settings: AI brain, API keys, budget, model catalogue"><Button variant="ghost" size="icon" aria-label="Settings" onClick={() => setSettings(true)}><Settings2 className="h-4 w-4" /></Button></Tip>
        {p.final_output && (
          <a href={fileUrl(P.pid, p.final_output)} download>
            <Button variant="primary" size="sm"><Download className="h-3.5 w-3.5" />Download</Button>
          </a>
        )}
      </header>

      {drafting && (
        <div className="flex items-center gap-2 border-b border-line bg-brand/5 px-4 py-2 text-xs text-brand">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Drafting your plan: parts, clips, scripts, actors and estimates…
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-[300px] shrink-0 flex-col border-r border-line bg-panel md:flex" aria-label="Story">
          <StoryTree />
        </aside>
        <main className="min-w-0 flex-1 overflow-auto scroll-thin" aria-label="Editor">
          {node ? <Editor node={node} /> : null}
        </main>
        <aside className="hidden w-[340px] shrink-0 flex-col border-l border-line bg-panel lg:flex" aria-label="Inspector">
          {node && <Inspector node={node} />}
        </aside>
      </div>

      <Timeline />
      <CommandBar open={cmd} onOpenChange={setCmd} />
      <GraphView open={graph} onOpenChange={setGraph} />
      <ContextLibrary open={library} onOpenChange={setLibrary} />
      <SettingsDialog open={settings} onOpenChange={setSettings} />
      <Tour />
      <span className="sr-only" aria-live="polite">{p.run.message}</span>
      {false && fmtSec(0)}
    </div>
  );
}
