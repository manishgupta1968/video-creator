import * as TooltipP from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { HELP, HelpEntry } from "../helpContent";

/** Rich help card: what it does, what you get, good to know. */
export function HelpCard({ entry }: { entry: HelpEntry }) {
  return (
    <div className="space-y-1.5 text-left">
      <div className="text-[13px] font-semibold">{entry.title}</div>
      <div><span className="font-semibold opacity-70">What it does: </span>{entry.does}</div>
      <div><span className="font-semibold opacity-70">You get: </span>{entry.gets}</div>
      {entry.note && <div className="opacity-80"><span className="font-semibold">Good to know: </span>{entry.note}</div>}
    </div>
  );
}

/** Wraps one element. Shows the help on hover AND on keyboard focus, and marks it so "Show me" can find it. */
export function HelpTip({ id, children, side = "top", extra }: { id: string; children: React.ReactElement; side?: "top" | "bottom" | "left" | "right"; extra?: string }) {
  const entry = HELP[id];
  if (!entry) return children;
  const child = React.cloneElement(children, { "data-help": id } as any);
  return (
    <TooltipP.Root delayDuration={350}>
      <TooltipP.Trigger asChild>{child}</TooltipP.Trigger>
      <TooltipP.Portal>
        <TooltipP.Content side={side} sideOffset={8} collisionPadding={12}
          className="z-[100] max-w-[19rem] rounded-xl bg-ink px-3 py-2.5 text-xs leading-relaxed text-bg shadow-pop">
          <HelpCard entry={extra ? { ...entry, note: [entry.note, extra].filter(Boolean).join(" ") } : entry} />
        </TooltipP.Content>
      </TooltipP.Portal>
    </TooltipP.Root>
  );
}

// ------------------------------------------------------------------------------------------ spotlight
type Spot = { id: string; rect: DOMRect } | null;
let current: Spot = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function visible(el: Element): boolean {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

/** Scrolls to the control, dims the rest of the screen, and explains it. Returns false when it is not on this screen. */
export function spotlight(id: string): boolean {
  const el = Array.from(document.querySelectorAll(`[data-help="${id}"]`)).find(visible) as HTMLElement | undefined;
  if (!el) return false;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ block: "center", inline: "center", behavior: reduce ? "auto" : "smooth" });
  setTimeout(() => { current = { id, rect: el.getBoundingClientRect() }; emit(); }, reduce ? 0 : 350);
  return true;
}
export const closeSpotlight = () => { current = null; emit(); };

export function SpotlightHost() {
  const [spot, setSpot] = useState<Spot>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const l = () => setSpot(current);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  useEffect(() => {
    if (!spot) return;
    const recompute = () => {
      const el = Array.from(document.querySelectorAll(`[data-help="${spot.id}"]`)).find(visible);
      if (!el) { closeSpotlight(); return; }
      current = { id: spot.id, rect: el.getBoundingClientRect() };
      setSpot(current);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeSpotlight(); };
    window.addEventListener("resize", recompute);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("resize", recompute); window.removeEventListener("keydown", onKey); };
  }, [spot?.id]); // eslint-disable-line
  useLayoutEffect(() => { if (spot) btn.current?.focus(); }, [spot?.id]); // eslint-disable-line
  if (!spot) return null;
  const entry = HELP[spot.id];
  const r = spot.rect;
  const pad = 6;
  const below = r.bottom + 220 < window.innerHeight;
  const width = 340;
  const left = Math.min(Math.max(12, r.left + r.width / 2 - width / 2), window.innerWidth - width - 12);
  return (
    <div className="fixed inset-0 z-[300]" role="dialog" aria-modal="true" aria-label={`Help: ${entry?.title || "this control"}`} onClick={closeSpotlight}>
      <div className="pointer-events-none absolute rounded-xl ring-2 ring-brand transition-all"
        style={{ left: r.left - pad, top: r.top - pad, width: r.width + pad * 2, height: r.height + pad * 2, boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.5)" }} />
      <div className="absolute rounded-2xl border border-line bg-panel p-4 text-xs shadow-pop" onClick={(e) => e.stopPropagation()}
        style={{ left, width, top: below ? r.bottom + pad + 10 : undefined, bottom: below ? undefined : window.innerHeight - r.top + pad + 10 }}>
        <button onClick={closeSpotlight} aria-label="Close help" className="absolute right-2 top-2 rounded-md p-1 text-muted hover:bg-sunken hover:text-ink"><X className="h-3.5 w-3.5" /></button>
        {entry && <HelpCard entry={entry} />}
        <button ref={btn} onClick={closeSpotlight} className="mt-3 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-brand-ink hover:brightness-110">Got it</button>
        <span className="ml-2 text-[11px] text-muted">or press Esc</span>
      </div>
    </div>
  );
}
