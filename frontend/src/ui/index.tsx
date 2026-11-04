// Small design system (shadcn-style, on Radix primitives).
import * as DialogP from "@radix-ui/react-dialog";
import * as SwitchP from "@radix-ui/react-switch";
import * as TabsP from "@radix-ui/react-tabs";
import * as TooltipP from "@radix-ui/react-tooltip";
import { clsx, type ClassValue } from "clsx";
import { Loader2, X } from "lucide-react";
import React, { forwardRef, useEffect, useRef, useState } from "react";
import { twMerge } from "tailwind-merge";

export const cn = (...c: ClassValue[]) => twMerge(clsx(c));

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "outline";
  size?: "sm" | "md" | "lg" | "icon";
  loading?: boolean;
};
export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = "secondary", size = "md", loading, className, children, disabled, ...rest }, ref) {
  return (
    <button ref={ref} disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-all select-none whitespace-nowrap",
        "disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98]",
        size === "sm" && "h-7 px-2.5 text-xs", size === "md" && "h-8 px-3 text-[13px]", size === "lg" && "h-11 px-5 text-sm",
        size === "icon" && "h-8 w-8",
        variant === "primary" && "bg-brand text-brand-ink hover:brightness-110 shadow-card",
        variant === "secondary" && "bg-sunken text-ink hover:bg-line/70",
        variant === "outline" && "border border-line bg-panel hover:bg-sunken",
        variant === "ghost" && "text-muted hover:text-ink hover:bg-sunken",
        variant === "danger" && "bg-bad/10 text-bad hover:bg-bad/20",
        className)}
      {...rest}>
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
});

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn("h-8 w-full rounded-lg border border-line bg-panel px-2.5 text-[13px] placeholder:text-muted/70 focus:border-brand focus:outline-none", className)} {...p} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} className={cn("w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-[13px] placeholder:text-muted/70 focus:border-brand focus:outline-none resize-none", className)} {...p} />;
});

export function Select({ value, onChange, options, className, title }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; className?: string; title?: string;
}) {
  return (
    <select title={title} value={value} onChange={(e) => onChange(e.target.value)}
      className={cn("h-7 rounded-md border border-line bg-panel px-1.5 text-xs text-ink focus:border-brand focus:outline-none cursor-pointer", className)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function Badge({ children, tone = "neutral", className, title }: { children: React.ReactNode; tone?: "neutral" | "ok" | "warn" | "bad" | "info" | "brand"; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium leading-none",
      tone === "neutral" && "bg-sunken text-muted", tone === "ok" && "bg-ok/10 text-ok", tone === "warn" && "bg-warn/15 text-warn",
      tone === "bad" && "bg-bad/10 text-bad", tone === "info" && "bg-info/10 text-info", tone === "brand" && "bg-brand/10 text-brand", className)}>
      {children}
    </span>
  );
}

export function Card({ className, children, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-xl border border-line bg-panel shadow-card", className)} {...p}>{children}</div>;
}

export function Tip({ content, children, side = "top" }: { content: React.ReactNode; children: React.ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  if (!content) return <>{children}</>;
  return (
    <TooltipP.Root delayDuration={250}>
      <TooltipP.Trigger asChild>{children}</TooltipP.Trigger>
      <TooltipP.Portal>
        <TooltipP.Content side={side} sideOffset={6} className="z-[100] max-w-xs rounded-lg bg-ink px-2.5 py-1.5 text-xs text-bg shadow-pop">
          {content}
        </TooltipP.Content>
      </TooltipP.Portal>
    </TooltipP.Root>
  );
}
export const TipProvider = TooltipP.Provider;

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer select-none text-xs">
      <SwitchP.Root checked={checked} onCheckedChange={onChange}
        className="relative h-4 w-7 rounded-full bg-line data-[state=checked]:bg-brand transition-colors" aria-label={label}>
        <SwitchP.Thumb className="block h-3 w-3 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-3.5" />
      </SwitchP.Root>
      {label && <span>{label}</span>}
    </label>
  );
}

export function Dialog({ open, onOpenChange, title, description, children, wide, footer }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: React.ReactNode; description?: React.ReactNode; children?: React.ReactNode; wide?: boolean | "xl"; footer?: React.ReactNode;
}) {
  return (
    <DialogP.Root open={open} onOpenChange={onOpenChange}>
      <DialogP.Portal>
        <DialogP.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px]" />
        <DialogP.Content className={cn("fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[calc(100vw-32px)] max-h-[88vh] flex flex-col rounded-2xl border border-line bg-panel shadow-pop",
          wide === "xl" ? "max-w-6xl" : wide ? "max-w-3xl" : "max-w-md")}>
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div>
              <DialogP.Title className="text-[15px] font-semibold">{title}</DialogP.Title>
              {description && <DialogP.Description className="mt-0.5 text-xs text-muted">{description}</DialogP.Description>}
            </div>
            <DialogP.Close className="rounded-md p-1 text-muted hover:bg-sunken hover:text-ink" aria-label="Close"><X className="h-4 w-4" /></DialogP.Close>
          </div>
          <div className="overflow-auto scroll-thin px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
        </DialogP.Content>
      </DialogP.Portal>
    </DialogP.Root>
  );
}

export const Tabs = TabsP.Root;
export function TabList({ tabs }: { tabs: { value: string; label: React.ReactNode; count?: number }[] }) {
  return (
    <TabsP.List className="flex gap-0.5 overflow-x-auto scroll-thin border-b border-line px-2">
      {tabs.map((t) => (
        <TabsP.Trigger key={t.value} value={t.value}
          className="relative whitespace-nowrap px-2.5 py-2 text-xs font-medium text-muted hover:text-ink data-[state=active]:text-ink data-[state=active]:after:absolute data-[state=active]:after:inset-x-2 data-[state=active]:after:-bottom-px data-[state=active]:after:h-0.5 data-[state=active]:after:bg-brand">
          {t.label}{t.count ? <span className="ml-1 rounded bg-sunken px-1 text-[10px]">{t.count}</span> : null}
        </TabsP.Trigger>
      ))}
    </TabsP.List>
  );
}
export const TabPanel = TabsP.Content;

/** Click-to-edit text that saves on blur / Enter (no Save buttons, autosave). */
export function Editable({ value, onSave, placeholder, multiline, className, inputClassName, ariaLabel }: {
  value: string; onSave: (v: string) => void; placeholder?: string; multiline?: boolean; className?: string; inputClassName?: string; ariaLabel?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef<any>(null);
  useEffect(() => { if (!editing) setDraft(value); }, [value, editing]);
  useEffect(() => { if (editing) { ref.current?.focus(); ref.current?.select?.(); } }, [editing]);
  const commit = () => { setEditing(false); if (draft !== value) onSave(draft); };
  if (!editing)
    return (
      <div role="button" tabIndex={0} aria-label={ariaLabel || "Edit"} onClick={() => setEditing(true)}
        onKeyDown={(e) => { if (e.key === "Enter") setEditing(true); }}
        className={cn("editable whitespace-pre-wrap", !value && "text-muted/70 italic", className)}>
        {value || placeholder || "Click to add"}
      </div>
    );
  const common = {
    ref, value: draft, onChange: (e: any) => setDraft(e.target.value), onBlur: commit,
    onKeyDown: (e: any) => {
      if (e.key === "Escape") { setDraft(value); setEditing(false); }
      if (e.key === "Enter" && (!multiline || e.metaKey || e.ctrlKey)) { e.preventDefault(); commit(); }
    },
  };
  return multiline
    ? <Textarea {...common} rows={Math.min(10, Math.max(3, draft.split("\n").length + 1))} className={inputClassName} />
    : <Input {...common} className={inputClassName} />;
}

/** Drop files anywhere in an area. */
export function DropZone({ onFiles, children, className, accept, label = "Drop files here or click to choose", compact }: {
  onFiles: (f: File[]) => void; children?: React.ReactNode; className?: string; accept?: string; label?: string; compact?: boolean;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = Array.from(e.dataTransfer.files); if (f.length) onFiles(f); }}
      onClick={() => input.current?.click()} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter") input.current?.click(); }}
      className={cn("cursor-pointer rounded-xl border border-dashed border-line text-center text-xs text-muted transition-colors hover:border-brand/60 hover:bg-brand/5",
        over && "border-brand bg-brand/10 text-brand", compact ? "px-3 py-2" : "px-4 py-5", className)}>
      <input ref={input} type="file" multiple hidden accept={accept} onChange={(e) => { const f = Array.from(e.target.files || []); if (f.length) onFiles(f); e.target.value = ""; }} />
      {children || label}
    </div>
  );
}

export function Meter({ value, max, tone }: { value: number; max: number; tone?: "ok" | "warn" | "bad" }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const t = tone || (pct > 100 ? "bad" : pct > 85 ? "warn" : "ok");
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-sunken">
      <div className={cn("h-full rounded-full transition-all", t === "ok" && "bg-ok", t === "warn" && "bg-warn", t === "bad" && "bg-bad")} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
      {icon && <div className="text-muted/60">{icon}</div>}
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="max-w-xs text-xs text-muted">{children}</div>}
    </div>
  );
}
