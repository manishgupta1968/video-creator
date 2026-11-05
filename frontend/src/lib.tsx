import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Circle, CircleDashed, Clock, Hourglass, Loader2, MousePointerClick, RefreshCw, XCircle } from "lucide-react";
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, Node, Project, Status, View } from "./api";

/** lets any component open the final-video player without prop drilling */
export const finalPlayer = { open: () => {} };

export const fmtSec = (s?: number | null) => {
  const v = Math.round(s || 0);
  return v < 60 ? `${v}s` : `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
};
export const fmtUsd = (v?: number | null) => (v === null || v === undefined ? "–" : v === 0 ? "Free" : v < 0.01 ? "<$0.01" : `$${v.toFixed(2)}`);
export const fmtRange = (a: number, b: number) => (Math.abs(a - b) < 0.01 ? fmtUsd(a) : `${fmtUsd(a)}–${fmtUsd(b)}`);
export const fmtTime = (s?: number) => {
  const v = Math.round(s || 0);
  if (v < 60) return `${v}s`;
  if (v < 3600) return `${Math.round(v / 60)} min`;
  return `${(v / 3600).toFixed(1)} h`;
};

export function walk(n: Node, out: Node[] = []): Node[] { out.push(n); n.children.forEach((c) => walk(c, out)); return out; }
export const leaves = (p: Project) => walk(p.root).filter((n) => n.kind !== "goal");
export const findNode = (p: Project, id: string) => walk(p.root).find((n) => n.id === id);
export function parentOf(p: Project, id: string): Node | undefined {
  return walk(p.root).find((n) => n.children.some((c) => c.id === id));
}

export const STATUS: Record<Status, { label: string; tone: "neutral" | "ok" | "warn" | "bad" | "info" | "brand"; icon: React.ReactNode; dot: string }> = {
  draft: { label: "Draft", tone: "neutral", icon: <CircleDashed className="h-3.5 w-3.5" />, dot: "bg-line" },
  ready: { label: "Ready", tone: "neutral", icon: <Circle className="h-3.5 w-3.5" />, dot: "bg-muted/50" },
  waiting: { label: "Waiting for earlier clip", tone: "info", icon: <Hourglass className="h-3.5 w-3.5" />, dot: "bg-info/60" },
  queued: { label: "Queued", tone: "info", icon: <Clock className="h-3.5 w-3.5" />, dot: "bg-info/60" },
  generating: { label: "Making…", tone: "brand", icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, dot: "bg-brand pulse" },
  needs_pick: { label: "Pick a take", tone: "warn", icon: <MousePointerClick className="h-3.5 w-3.5" />, dot: "bg-warn" },
  done: { label: "Done", tone: "ok", icon: <CheckCircle2 className="h-3.5 w-3.5" />, dot: "bg-ok" },
  stale: { label: "Out of date", tone: "warn", icon: <RefreshCw className="h-3.5 w-3.5" />, dot: "bg-warn/70" },
  failed: { label: "Failed", tone: "bad", icon: <XCircle className="h-3.5 w-3.5" />, dot: "bg-bad" },
};
export const warnIcon = <AlertTriangle className="h-3.5 w-3.5" />;

export const SHOT_TYPES = [
  { value: "talking_head", label: "Presenter to camera" }, { value: "dialogue_scene", label: "People talking in a scene" },
  { value: "human_motion", label: "People moving / hands" }, { value: "wildlife", label: "Animals / nature" },
  { value: "landscape", label: "Landscape / effects" }, { value: "product", label: "Product shot" }, { value: "other", label: "Other" },
];
export const CTX_TYPES = [
  { value: "actor", label: "Actor" }, { value: "object", label: "Object / prop" }, { value: "entity", label: "Brand / entity" },
  { value: "location", label: "Location" }, { value: "style", label: "Style / look" }, { value: "audio", label: "Audio" },
  { value: "text", label: "Text note" }, { value: "media", label: "Slides / footage" },
];
export const CTX_ROLES = [
  { value: "must_appear", label: "Must appear" }, { value: "look_reference", label: "Look reference" },
  { value: "start_frame", label: "Start frame" }, { value: "end_frame", label: "End frame" }, { value: "voice", label: "Voice" },
  { value: "sound", label: "Sound to use" }, { value: "music_reference", label: "Music reference" },
  { value: "knowledge", label: "Knowledge for AI" }, { value: "include", label: "Include as-is" },
];
export const DEP_TYPES = [
  { value: "continues_from", label: "Continues from (start on last frame)" }, { value: "same_location", label: "Same location" },
  { value: "actor_state", label: "Actor state carries over" }, { value: "audio_carry", label: "Sound carries across" },
  { value: "reference", label: "Shows something from" }, { value: "order_only", label: "Story order only" },
];
export const depLabel = (t: string) => DEP_TYPES.find((d) => d.value === t)?.label.split(" (")[0] || t;
export const TRANSITIONS = [
  { value: "cut", label: "Cut" }, { value: "crossfade", label: "Crossfade" }, { value: "fade_black", label: "Fade to black" },
  { value: "dissolve", label: "Dissolve" }, { value: "whip", label: "Whip" }, { value: "wipe", label: "Wipe" },
];

// ------------------------------------------------------------------- toasts
type Toast = { id: number; text: string; tone: "ok" | "bad" | "info"; action?: { label: string; run: () => void } };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastHost({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-3), { ...t, id }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), t.tone === "bad" ? 9000 : 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-24 right-4 z-[200] flex w-80 flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 text-xs shadow-pop bg-panel ${t.tone === "bad" ? "border-bad/40" : "border-line"}`}>
            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${t.tone === "bad" ? "bg-bad" : t.tone === "ok" ? "bg-ok" : "bg-info"}`} />
            <span className="flex-1">{t.text}</span>
            {t.action && <button className="font-medium text-brand" onClick={t.action.run}>{t.action.label}</button>}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ------------------------------------------------------------------- project state
export interface ProjectApi {
  pid: string; view: View | undefined; busy: string[]; selected: string; select: (id: string) => void;
  set: (v: View) => void; act: <T extends View | any>(label: string, fn: () => Promise<T>, okText?: string) => Promise<T | undefined>;
  numbers: Record<string, string>; online: boolean; fetchedAt: number;
  settings: { open: boolean; tab: string }; openSettings: (tab?: string) => void; closeSettings: () => void;
}
const PCtx = createContext<ProjectApi | null>(null);
export const useP = () => useContext(PCtx)!;

export function ProjectProvider({ pid, children }: { pid: string; children: React.ReactNode }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [online, setOnline] = useState(true);
  const [settings, setSettingsState] = useState({ open: false, tab: "keys" });
  const q = useQuery({ queryKey: ["project", pid], queryFn: () => api.get(pid), refetchInterval: (query) => {
    const d = query.state.data as View | undefined;
    return d && (d.engine.active || d.project.run.status === "running") ? 4000 : 15000;
  } });
  const set = useCallback((v: View) => qc.setQueryData(["project", pid], v), [qc, pid]);

  // live events
  const wsRef = useRef<WebSocket | null>(null);
  useEffect(() => {
    let closed = false;
    let timer: any;
    const connect = () => {
      const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${encodeURIComponent(pid)}`);
      wsRef.current = ws;
      ws.onopen = () => setOnline(true);
      ws.onmessage = (m) => {
        const ev = JSON.parse(m.data);
        if (ev.type === "busy") setBusy((b) => (ev.busy ? [...b, ev.label] : b.filter((x) => x !== ev.label)));
        if (ev.type === "error") toast({ text: ev.message, tone: "bad" });
        if (ev.type === "final") toast({ text: "Your final video is ready", tone: "ok" });
        if (ev.type === "clip" && ev.status === "failed") toast({ text: `A clip failed: ${ev.message}`, tone: "bad" });
        clearTimeout(timer);
        timer = setTimeout(() => qc.invalidateQueries({ queryKey: ["project", pid] }), 150);
      };
      ws.onclose = () => { if (!closed) { setOnline(false); setTimeout(connect, 1500); } };
    };
    connect();
    return () => { closed = true; wsRef.current?.close(); };
  }, [pid, qc, toast]);

  const act = useCallback(async <T,>(label: string, fn: () => Promise<T>, okText?: string) => {
    setBusy((b) => [...b, label]);
    try {
      const r = await fn();
      if (r && typeof r === "object" && "project" in (r as any) && "summary" in (r as any)) set(r as any);
      if (okText) toast({ text: okText, tone: "ok", action: { label: "Undo", run: async () => set(await api.undo(pid)) } });
      return r;
    } catch (e: any) {
      toast({ text: e.message || String(e), tone: "bad" });
      return undefined;
    } finally {
      setBusy((b) => { const i = b.indexOf(label); return i < 0 ? b : [...b.slice(0, i), ...b.slice(i + 1)]; });
    }
  }, [pid, set, toast]);

  const view = q.data;
  useEffect(() => {
    if (view && (!selected || !findNode(view.project, selected))) {
      const first = view.project.root.children[0];
      setSelected(first ? first.id : view.project.root.id);
    }
  }, [view, selected]);

  return (
    <PCtx.Provider value={{ pid, view, busy, selected, select: setSelected, set, act, numbers: view?.summary.numbers || {}, online, fetchedAt: q.dataUpdatedAt,
      settings, openSettings: (tab = "keys") => setSettingsState({ open: true, tab }), closeSettings: () => setSettingsState((s) => ({ ...s, open: false })) }}>
      {children}
    </PCtx.Provider>
  );
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: 30000 });
}
export function useSettingsMutation() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.patchSettings, onSuccess: (d) => qc.setQueryData(["settings"], d) });
}

export function useHotkey(combo: (e: KeyboardEvent) => boolean, fn: (e: KeyboardEvent) => void, allowInInputs = false) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if (typing && !allowInInputs) return;
      if (combo(e)) { e.preventDefault(); fn(e); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [combo, fn, allowInInputs]);
}
