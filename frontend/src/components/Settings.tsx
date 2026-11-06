import { CheckCircle2, ExternalLink, KeyRound, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, FoundModel, ModelRow } from "../api";
import { fmtUsd, useSettings, useSettingsMutation, useToast } from "../lib";
import { Badge, Button, Dialog, HelpTip, Input, Select, Switch, TabList, TabPanel, Tabs } from "../ui";
import { BrainPicker } from "./ModelPicker";

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
            <TabPanel value="brain"><BrainTab d={d} patch={patch} goKeys={() => setTab("keys")} /></TabPanel>
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

/** Settings → AI brain: every brain model is a choice (with its price and what one plan draft costs), for three kinds of work. */
function BrainTab({ d, patch, goKeys }: { d: any; patch: (p: any) => Promise<void>; goKeys: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const llm = d.config.llm;
  const pt: Record<string, string> = llm.per_task_model || {};
  const models: Record<string, string> = llm.models || {};
  const [found, setFound] = useState<FoundModel[]>([]);
  const [info, setInfo] = useState<{ errors: Record<string, string>; skipped: string[]; checked: boolean } | null>(null);
  const [pending, setPending] = useState<{ kind: string; m: FoundModel } | null>(null);
  const [price, setPrice] = useState({ usd_in: "", usd_out: "" });
  const [refreshing, setRefreshing] = useState(false);

  const planning = pt.default || (llm.default === "auto" ? "auto" : `${llm.default}:${models[llm.default] || ""}`);
  const review = pt.review || (llm.reviewer === "same" ? "same" : `${llm.reviewer}:${models[llm.reviewer] || ""}`);
  const simple = pt.simple || "same";

  const apply = async (kind: "default" | "review" | "simple", v: string) => {
    const next = { ...pt };
    const [plugin, ...rest] = v.split(":");
    const model = rest.join(":");
    if (v === "auto" || v === "same") delete next[kind]; else next[kind] = v;
    if (kind === "default") {
      await patch({ llm: v === "auto" ? { default: "auto", per_task_model: next } : { default: plugin, models: { ...models, [plugin]: model }, per_task_model: next } });
    } else if (kind === "review") {
      await patch({ llm: v === "same" ? { reviewer: "same", per_task_model: next } : { reviewer: plugin, per_task_model: next } });
    } else {
      await patch({ llm: { per_task_model: next } });
    }
  };
  const unusable = (r: ModelRow) => { toast({ text: `${r.model} is not connected (${r.why_not}). Add what is missing on the “Vendors & keys” tab.`, tone: "info" }); goKeys(); };
  const refresh = async () => {
    setRefreshing(true);
    try {
      const r = await api.refreshModels();
      setFound(r.models);
      setInfo({ errors: r.errors, skipped: r.skipped, checked: true });
      const fresh = r.models.filter((m) => !m.in_catalogue).length;
      toast({ text: fresh ? `${fresh} model(s) found that are not in your catalogue yet. They are at the end of each list.` : "Your catalogue already has every model your keys can use.", tone: "ok" });
    } catch (e: any) { toast({ text: e.message, tone: "bad" }); } finally { setRefreshing(false); }
  };
  const addFound = async () => {
    if (!pending) return;
    const r = await api.addModel(pending.m.plugin as string, pending.m.id, Number(price.usd_in), Number(price.usd_out)).catch((e: any) => { toast({ text: e.message, tone: "bad" }); return null; });
    if (!r) return;
    qc.setQueryData(["settings"], r);
    await apply(pending.kind as any, `${pending.m.plugin}:${pending.m.id}`);
    setPending(null);
    setPrice({ usd_in: "", usd_out: "" });
    toast({ text: `${pending.m.id} added with the price you entered`, tone: "ok" });
  };
  const kinds: { kind: "default" | "review" | "simple"; label: string; hint: string; value: string; same?: string; auto?: string }[] = [
    { kind: "default", label: "AI for planning & scripts", hint: `Now using: ${d.brain}. This does most of the thinking, so it sets most of the AI cost.`, value: planning, auto: "Automatic (the first connected vendor)" },
    { kind: "review", label: "AI for the Review Agent", hint: `Now using: ${d.reviewer}. Gemini models can watch whole clips.`, value: review, same: "Same as the planning AI" },
    { kind: "simple", label: "AI for simple jobs", hint: "Answering questions, choosing a photo, typed commands. A cheaper model is usually enough.", value: simple, same: "Same as the planning AI" },
  ];
  return (
    <div className="grid max-w-3xl gap-5 text-xs">
      <p className="text-muted">Every model is listed with its price. A model that is not connected is shown with what is missing. Prices are per 1 million tokens (a token is a small piece of a word).</p>
      {kinds.map((k) => (
        <Row key={k.kind} label={k.label} hint={k.hint}>
          <BrainPicker title={k.label} value={k.value} found={found} autoLabel={k.auto} sameLabel={k.same}
            onPick={(v) => apply(k.kind, v)} onUnusable={unusable} onFound={(m) => { setPending({ kind: k.kind, m }); setPrice({ usd_in: "", usd_out: "" }); }} />
        </Row>
      ))}
      {pending && (
        <div className="rounded-xl border border-warn/50 bg-warn/5 p-3">
          <div className="font-medium">{pending.m.id} is not in your catalogue yet</div>
          <p className="mt-0.5 text-muted">Type its price from the vendor's pricing page. It is how every AI call and every estimate is counted, so please check it.</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span>$</span><Input type="number" min={0} step="0.01" placeholder="in" aria-label="Price per 1M input tokens" value={price.usd_in} onChange={(e) => setPrice({ ...price, usd_in: e.target.value })} className="h-7 w-24" />
            <span className="text-muted">in and $</span><Input type="number" min={0} step="0.01" placeholder="out" aria-label="Price per 1M output tokens" value={price.usd_out} onChange={(e) => setPrice({ ...price, usd_out: e.target.value })} className="h-7 w-24" />
            <span className="text-muted">out, per 1M tokens</span>
            <Button size="sm" variant="primary" disabled={price.usd_in === "" || price.usd_out === ""} onClick={addFound}>Add and use it</Button>
            <Button size="sm" variant="ghost" onClick={() => setPending(null)}>Cancel</Button>
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <HelpTip id="refresh-models"><Button size="sm" variant="outline" loading={refreshing} onClick={refresh}><RefreshCw className="h-3.5 w-3.5" />Refresh from vendor</Button></HelpTip>
        <span className="text-muted">Asks each connected vendor which models your key can use. Free; it only reads a list.</span>
      </div>
      {info && (Object.keys(info.errors).length > 0 || info.skipped.length > 0) && (
        <ul className="space-y-0.5 text-[11px] text-muted">
          {Object.entries(info.errors).map(([v, why]) => <li key={v}>{v}: {why}</li>)}
          {info.skipped.length > 0 && <li>Not asked (no key set): {info.skipped.join(", ")}</li>}
        </ul>
      )}
      <Row label="Claude effort" hint="Higher = more careful, more tokens">
        <Select value={llm.anthropic_effort} onChange={(v) => patch({ llm: { anthropic_effort: v } })} options={["low", "medium", "high", "xhigh", "max"].map((x) => ({ value: x, label: x }))} />
      </Row>
      <Row label="Claude refusal fallback" hint="If Claude declines, retry on another Claude model automatically">
        <Switch checked={llm.anthropic_fallbacks} onChange={(v) => patch({ llm: { anthropic_fallbacks: v } })} />
      </Row>
      <details className="rounded-xl border border-line p-3">
        <summary className="cursor-pointer font-medium">Type an exact model name (advanced)</summary>
        <p className="mt-1 text-muted">Only if a model is missing from the lists above. This is the model each vendor uses for planning when you chose “Automatic”.</p>
        <div className="mt-2 grid gap-2">
          {["anthropic", "openai", "gemini"].map((k) => (
            <Row key={k} label={`${k} model`} hint="Exact model id from the vendor">
              <Input defaultValue={models[k]} onBlur={(e) => e.target.value !== models[k] && patch({ llm: { models: { ...models, [k]: e.target.value } } })} className="w-56" />
            </Row>
          ))}
        </div>
      </details>
    </div>
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
