import { ArrowLeft, Command, Download, GitBranch, HelpCircle, Library, Loader2, Moon, Redo2, Settings2, Sun, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, fileUrl } from "../api";
import { useTheme } from "../App";
import { commandBus, findNode, finalPlayer, fmtSec, fmtUsd, ProjectProvider, useHotkey, useP } from "../lib";
import { Badge, Button, Editable, HelpTip, Tip } from "../ui";
import ActivityBar, { TopLine, useTabStatus } from "./ActivityBar";
import { FinalVideoDialog, PreviewBanner } from "./Banners";
import CommandBar from "./CommandBar";
import { RunProvider } from "./ConfirmRun";
import NextStep from "./NextStep";
import { JoinProvider } from "./JoinDialog";
import SummaryStrip from "./SummaryStrip";
import ContinuityBar from "./ContinuityDialog";
import OptimizeHost from "./OptimizeDialog";
import BudgetDialog from "./BudgetDialog";
import ContextLibrary from "./ContextLibrary";
import HelpDrawer from "./HelpDrawer";
import Editor from "./Editor";
import GraphView from "./GraphView";
import Inspector from "./Inspector";
import SettingsDialog from "./Settings";
import StoryTree from "./StoryTree";
import Timeline from "./Timeline";
import Tour from "./Tour";

function FinalOpenBridge({ open }: { open: () => void }) {
  finalPlayer.open = open;
  return null;
}

export default function Workspace({ pid, onHome }: { pid: string; onHome: () => void }) {
  return (
    <ProjectProvider pid={pid}>
      <RunProvider>
        <JoinProvider>
          <Shell onHome={onHome} />
        </JoinProvider>
      </RunProvider>
    </ProjectProvider>
  );
}

function Shell({ onHome }: { onHome: () => void }) {
  const P = useP();
  const [cmd, setCmd] = useState(false);
  const [cmdText, setCmdText] = useState("");
  commandBus.open = (t) => { setCmdText(t || ""); setCmd(true); };
  const [graph, setGraph] = useState(false);
  const [library, setLibrary] = useState(false);
  const [finalOpen, setFinalOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [budgetOpen, setBudgetOpen] = useState(false);
  useEffect(() => {                       // the next-step guide can open the budget breakdown
    const open = () => setBudgetOpen(true);
    window.addEventListener("vg-open-budget", open);
    return () => window.removeEventListener("vg-open-budget", open);
  }, []);
  useHotkey(useCallback((e) => e.key === "?", []), () => setHelpOpen(true));
  useTabStatus();
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
      <TopLine />
      {/* top bar */}
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-panel px-3">
        <Button help="back-home" variant="ghost" size="icon" onClick={onHome} aria-label="All projects"><ArrowLeft className="h-4 w-4" /></Button>
        <HelpTip id="project-name"><span><Editable value={p.name} onSave={(name) => P.act("Rename", () => api.patch(P.pid, { name }))}
          className="max-w-[28ch] truncate text-sm font-semibold" ariaLabel="Project name" /></span></HelpTip>
        <Tip content="The AI that plans, writes and reviews. Change it in Settings.">
          <HelpTip id="ai-badge"><span><Badge tone={s.brain === "fake_llm" ? "warn" : "brand"}>AI: {s.brain === "fake_llm" ? "offline" : s.brain}</Badge></span></HelpTip>
        </Tip>
        <div className="flex-1" />
        <Button help="ask-ai" variant="outline" size="sm" onClick={() => setCmd(true)} className="hidden sm:inline-flex text-muted">
          <Command className="h-3.5 w-3.5" />Ask AI… <kbd className="ml-1 rounded bg-sunken px-1 text-[10px]">Ctrl K</kbd>
        </Button>
        <Button help="undo" variant="ghost" size="icon" aria-label="Undo" onClick={() => P.act("Undo", () => api.undo(P.pid))}><Undo2 className="h-4 w-4" /></Button>
        <Button help="redo" variant="ghost" size="icon" aria-label="Redo" onClick={() => P.act("Redo", () => api.redo(P.pid))}><Redo2 className="h-4 w-4" /></Button>
        <Button help="graph" variant="ghost" size="icon" aria-label="Graph" onClick={() => setGraph(true)}><GitBranch className="h-4 w-4" /></Button>
        <Button help="library" variant="ghost" size="icon" aria-label="Context library" onClick={() => setLibrary(true)}><Library className="h-4 w-4" /></Button>
        <Button help="help" variant="ghost" size="icon" aria-label="Help" onClick={() => setHelpOpen(true)}><HelpCircle className="h-4 w-4" /></Button>
        <Button help="theme" variant="ghost" size="icon" aria-label="Theme" onClick={() => setTheme(dark ? "light" : "dark")}>{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
        <Button help="settings" variant="ghost" size="icon" aria-label="Settings" onClick={() => P.openSettings("keys")}><Settings2 className="h-4 w-4" /></Button>
        {s.final_ready && (
          <a href={fileUrl(P.pid, p.final_output)} download>
            <Button help="download" variant={s.final_stale ? "outline" : "primary"} size="sm"><Download className="h-3.5 w-3.5" />{s.final_stale ? "Download (out of date)" : "Download"}</Button>
          </a>
        )}
      </header>

      <SummaryStrip />
      <ContinuityBar />
      <OptimizeHost />
      <ActivityBar />
      <PreviewBanner />
      <NextStep />

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-[320px] shrink-0 flex-col border-r border-line bg-panel md:flex" aria-label="Story">
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
      <CommandBar open={cmd} onOpenChange={setCmd} initialText={cmdText} />
      <GraphView open={graph} onOpenChange={setGraph} />
      <ContextLibrary open={library} onOpenChange={setLibrary} />
      <SettingsDialog open={P.settings.open} onOpenChange={(o) => (o ? P.openSettings(P.settings.tab) : P.closeSettings())} tab={P.settings.tab} />
      <FinalVideoDialog open={finalOpen} onOpenChange={setFinalOpen} />
      <BudgetDialog open={budgetOpen} onOpenChange={setBudgetOpen} />
      <HelpDrawer open={helpOpen} onOpenChange={setHelpOpen} pid={P.pid} />
      <FinalOpenBridge open={() => setFinalOpen(true)} />
      <Tour />
      <span className="sr-only" aria-live="polite">{p.run.message}</span>
      {false && fmtSec(0)}
    </div>
  );
}
