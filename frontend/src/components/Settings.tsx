import { CheckCircle2, ExternalLink, KeyRound, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { fmtUsd, useSettings, useSettingsMutation, useToast } from "../lib";
import { Badge, Button, Dialog, Input, Select, Switch, TabList, TabPanel, Tabs } from "../ui";

const BRAINS = [{ value: "auto", label: "Automatic (first with a key)" }, { value: "anthropic", label: "Anthropic Claude" },
  { value: "openai", label: "OpenAI GPT" }, { value: "gemini", label: "Google Gemini" }, { value: "fake_llm", label: "Offline (free, simple)" }];

export default function SettingsDialog({ open, onOpenChange, tab: initialTab }: { open: boolean; onOpenChange: (v: boolean) => void; tab?: string }) {
  const [tab, setTab] = useState(initialTab || "keys");
  useEffect(() => { if (open) setTab(initialTab || "keys"); }, [open, initialTab]);
  const q = useSettings();
  const m = useSettingsMutation();
  const qc = useQueryClient();
  const toast = useToast();
  const d = q.data;
  const patch = async (p: any) => { await m.mutateAsync(p); qc.invalidateQueries({ queryKey: ["project"] }); toast({ text: "Saved", tone: "ok" }); };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide="xl" title="Settings" description="Saved on this computer in ~/.video-generator">
      {!d ? <div className="skeleton h-40 rounded-lg" /> : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabList tabs={[{ value: "keys", label: "Vendors & keys" }, { value: "brain", label: "AI brain" }, { value: "budget", label: "Budget & quality" },
            { value: "catalog", label: "Model catalogue" }, { value: "plugins", label: "Plugins" }]} />
          <div className="pt-4">
            <TabPanel value="keys"><Keys d={d} /></TabPanel>
            <TabPanel value="brain">
              <div className="grid max-w-xl gap-4 text-xs">
                <Row label="AI brain for planning & scripts" hint={`Now using: ${d.brain}`}>
                  <Select value={d.config.llm.default} onChange={(v) => patch({ llm: { default: v } })} options={BRAINS} />
                </Row>
                <Row label="AI for the Review Agent" hint={`Now using: ${d.reviewer}. Gemini can watch whole clips.`}>
                  <Select value={d.config.llm.reviewer} onChange={(v) => patch({ llm: { reviewer: v } })} options={[{ value: "same", label: "Same as above" }, ...BRAINS.slice(1)]} />
                </Row>
                {["anthropic", "openai", "gemini"].map((k) => (
                  <Row key={k} label={`${k} model`} hint="Exact model id from the vendor">
                    <Input defaultValue={d.config.llm.models[k]} onBlur={(e) => e.target.value !== d.config.llm.models[k] && patch({ llm: { models: { ...d.config.llm.models, [k]: e.target.value } } })} className="w-56" />
                  </Row>
                ))}
                <Row label="Claude effort" hint="Higher = more careful, more tokens">
                  <Select value={d.config.llm.anthropic_effort} onChange={(v) => patch({ llm: { anthropic_effort: v } })}
                    options={["low", "medium", "high", "xhigh", "max"].map((x) => ({ value: x, label: x }))} />
                </Row>
                <Row label="Claude refusal fallback" hint="If Claude declines, retry on another Claude model automatically">
                  <Switch checked={d.config.llm.anthropic_fallbacks} onChange={(v) => patch({ llm: { anthropic_fallbacks: v } })} />
                </Row>
              </div>
            </TabPanel>
            <TabPanel value="budget">
              <div className="grid max-w-xl gap-4 text-xs">
                <Row label="Default budget for new projects ($)">
                  <Input type="number" defaultValue={d.config.budget_usd} onBlur={(e) => patch({ budget_usd: Number(e.target.value) })} className="w-28" />
                </Row>
                <Row label="Default quality" hint="Best · Balanced (quality per dollar) · Budget · Free preview">
                  <Select value={d.config.quality_mode} onChange={(v) => patch({ quality_mode: v })}
                    options={[{ value: "best", label: "Best" }, { value: "balanced", label: "Balanced" }, { value: "budget", label: "Budget" }, { value: "free", label: "Free preview" }]} />
                </Row>
                <Row label="Clips made at the same time">
                  <Select value={String(d.config.max_parallel_jobs)} onChange={(v) => patch({ max_parallel_jobs: Number(v) })} options={[1, 2, 3, 4, 6, 8].map((n) => ({ value: String(n), label: String(n) }))} />
                </Row>
                <Row label="Your name" hint="Recorded with consent confirmations">
                  <Input defaultValue={d.config.user_name} onBlur={(e) => patch({ user_name: e.target.value })} className="w-56" />
                </Row>
              </div>
            </TabPanel>
            <TabPanel value="catalog"><Catalog d={d} /></TabPanel>
            <TabPanel value="plugins">
              <div className="grid gap-1.5 text-xs sm:grid-cols-2">
                {d.plugins.map((p: any) => (
                  <div key={p.name} className="flex items-start gap-2 rounded-lg border border-line p-2">
                    {p.configured ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 text-ok" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 text-muted" />}
                    <div className="min-w-0"><div className="font-medium">{p.name} <span className="text-muted">· {p.job}</span></div>
                      <div className="text-[11px] text-muted">{p.description}</div>{!p.configured && <div className="text-[11px] text-warn">{p.status}</div>}</div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[11px] text-muted">New tools are added as Python packages (entry point group <code>video_generator.plugins</code>) plus one row in the model catalogue. See docs/writing-a-plugin.md.</p>
            </TabPanel>
          </div>
        </Tabs>
      )}
    </Dialog>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-4"><div><div className="font-medium">{label}</div>{hint && <div className="text-[11px] text-muted">{hint}</div>}</div>{children}</div>;
}

function Keys({ d }: { d: any }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [vals, setVals] = useState<Record<string, string>>({});
  const save = async (name: string) => {
    const r = await api.setKey(name, vals[name] || "");
    qc.setQueryData(["settings"], r);
    qc.invalidateQueries({ queryKey: ["project"] });
    toast({ text: `${name} saved`, tone: "ok" });
    setVals((v) => ({ ...v, [name]: "" }));
  };
  const test = async (plugin: string) => { const r = await api.testPlugin(plugin); toast({ text: `${plugin}: ${r.message}`, tone: r.ok ? "ok" : "bad" }); };
  const pluginFor: Record<string, string> = { anthropic: "anthropic", openai: "openai", google: "gemini", fal: "fal", elevenlabs: "elevenlabs", heygen: "heygen", runway: "runway", luma: "luma", kling: "kling", cartesia: "cartesia", replicate: "replicate" };
  return (
    <div className="space-y-2 text-xs">
      <p className="text-muted">Open pay-as-you-go accounts only for what you need. Start with: one AI brain (Anthropic or OpenAI) + fal.ai + ElevenLabs. Keys are stored only on this computer.</p>
      {d.vendors.filter((v: any) => v.id !== "local").map((v: any) => (
        <div key={v.id} className="rounded-xl border border-line p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{v.name}</span>
            {v.configured ? <Badge tone="ok">connected</Badge> : <Badge>{v.need}</Badge>}
            <div className="flex-1" />
            {v.signup_url && <a className="inline-flex items-center gap-1 text-brand hover:underline" href={v.signup_url} target="_blank" rel="noreferrer">Sign up / billing<ExternalLink className="h-3 w-3" /></a>}
            {v.pricing_url && <a className="inline-flex items-center gap-1 text-muted hover:underline" href={v.pricing_url} target="_blank" rel="noreferrer">Prices<ExternalLink className="h-3 w-3" /></a>}
          </div>
          <div className="mt-0.5 text-[11px] text-muted">{v.used_for}</div>
          {v.keys.map((k: any) => (
            <div key={k.name} className="mt-2 flex items-center gap-2">
              <KeyRound className="h-3.5 w-3.5 text-muted" />
              <code className="w-44 shrink-0 text-[11px]">{k.name}</code>
              <Input type="password" placeholder={k.set ? "•••••••• (set)" : "paste key"} value={vals[k.name] || ""} onChange={(e) => setVals({ ...vals, [k.name]: e.target.value })} className="h-7" />
              <Button help="save-key" size="sm" onClick={() => save(k.name)} disabled={!vals[k.name]}>Save</Button>
              {k.set && <Button size="sm" variant="ghost" onClick={() => { setVals({ ...vals, [k.name]: "" }); api.setKey(k.name, "").then((r) => qc.setQueryData(["settings"], r)); }}>Remove</Button>}
            </div>
          ))}
          {v.configured && pluginFor[v.id] && <Button help="test-connection" size="sm" variant="ghost" className="mt-1.5" onClick={() => test(pluginFor[v.id])}>Test connection</Button>}
        </div>
      ))}
    </div>
  );
}

function Catalog({ d }: { d: any }) {
  const qc = useQueryClient();
  const [job, setJob] = useState("video");
  const rows = d.catalog.filter((e: any) => e.job === job);
  const patch = async (id: string, p: any) => qc.setQueryData(["settings"], await api.patchCatalog(id, p));
  return (
    <div className="text-xs">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {["video", "image", "voice", "avatar", "lipsync", "music", "llm", "transcribe"].map((j) => (
          <button key={j} onClick={() => setJob(j)} className={`rounded-full px-2.5 py-1 ${job === j ? "bg-brand/10 font-medium text-brand" : "text-muted hover:bg-sunken"}`}>{j}</button>
        ))}
        <span className="ml-auto text-[11px] text-muted">Prices change often — update them from each vendor's page. Older than 30 days is marked.</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="text-left text-[11px] text-muted"><tr><th className="py-1">Model</th><th>Via</th><th>Price</th><th>Usable</th><th>On</th><th>Checked</th><th /></tr></thead>
          <tbody>
            {rows.map((e: any) => (
              <tr key={e.id} className="border-t border-line">
                <td className="py-1.5"><div className="font-medium">{e.id}</div><div className="text-[10px] text-muted">{e.model}</div></td>
                <td>{e.plugin}</td>
                <td>
                  {e.price.unit === "1m_tokens" ? <span>${e.price.usd_in} / ${e.price.usd_out} per 1M</span> : (
                    <span className="inline-flex items-center gap-1">$<input type="number" step="0.001" defaultValue={e.price.usd} className="h-6 w-20 rounded border border-line bg-panel px-1"
                      onBlur={(ev) => Number(ev.target.value) !== e.price.usd && patch(e.id, { price: { usd: Number(ev.target.value) }, last_checked: new Date().toISOString().slice(0, 10) })} />/{e.price.unit.replace("_", " ")}</span>
                  )}
                </td>
                <td>{e.usable ? <Badge tone="ok">yes</Badge> : <Badge>no key</Badge>}</td>
                <td><Switch checked={e.enabled} onChange={(v) => patch(e.id, { enabled: v })} /></td>
                <td className={e.days_old > 30 && e.vendor !== "local" ? "text-warn" : "text-muted"}>{e.last_checked}</td>
                <td>{e.pricing_url && <a href={e.pricing_url} target="_blank" rel="noreferrer" className="text-brand"><ExternalLink className="h-3 w-3" /></a>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {false && fmtUsd(0)}
    </div>
  );
}
