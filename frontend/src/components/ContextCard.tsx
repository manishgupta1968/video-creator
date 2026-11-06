import { AudioLines, Box, Building2, FileText, Film, Image as ImageIcon, MapPin, Mic, Palette, Play, Search, ShieldAlert, ShieldCheck, Trash2, User } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, Ctx, fileUrl } from "../api";
import { CTX_ROLES, CTX_TYPES, useP, useSettings } from "../lib";
import StockSearch from "./StockSearch";
import { RecordVoiceDialog } from "./VoiceRecorder";
import { Badge, Button, cn, Dialog, DropZone, Editable, HelpTip, Select, Switch, Tip } from "../ui";

export const typeIcon = (t: string) => ({
  actor: <User className="h-3.5 w-3.5" />, object: <Box className="h-3.5 w-3.5" />, entity: <Building2 className="h-3.5 w-3.5" />,
  location: <MapPin className="h-3.5 w-3.5" />, style: <Palette className="h-3.5 w-3.5" />, audio: <AudioLines className="h-3.5 w-3.5" />,
  text: <FileText className="h-3.5 w-3.5" />, media: <Film className="h-3.5 w-3.5" />,
} as Record<string, JSX.Element>)[t] || <FileText className="h-3.5 w-3.5" />;

const isImg = (f: string) => /\.(png|jpe?g|webp|gif)$/i.test(f);

export function ContextCard({ item, origin, inheritedOff, onToggle, compact }: {
  item: Ctx; origin?: string; inheritedOff?: boolean; onToggle?: (off: boolean) => void; compact?: boolean;
}) {
  const P = useP();
  const [open, setOpen] = useState(false);
  useEffect(() => {                       // "Your next step" can ask for this card to open
    const h = (e: Event) => { if ((e as CustomEvent).detail === item.id) setOpen(true); };
    window.addEventListener("vg-open-context", h);
    return () => window.removeEventListener("vg-open-context", h);
  }, [item.id]);
  const thumb = item.actor?.reference_sheet[0] || item.files.find(isImg);
  const inherited = origin && origin !== "this";
  const needsConsent = item.type === "actor" && (item.files.length > 0 || item.actor?.voice_sample) && ["real_person", "digital_twin"].includes(item.actor?.kind || "") && !item.consent.confirmed;
  const label = origin === "shared" ? "shared" : origin?.startsWith("node:") ? `from part ${origin.slice(5)}` : origin === "this" ? "this only" : undefined;
  return (
    <>
      <div className={cn("group flex items-start gap-2.5 rounded-xl border border-line bg-panel p-2 transition-opacity", inherited && "border-dashed", inheritedOff && "opacity-45")}>
        <button onClick={() => setOpen(true)} className="h-11 w-11 shrink-0 overflow-hidden rounded-lg bg-sunken text-muted grid place-items-center" aria-label={`Open ${item.title}`}>
          {thumb ? <img src={fileUrl(P.pid, thumb)} className="h-full w-full object-cover" alt="" /> : typeIcon(item.type)}
        </button>
        <div className="min-w-0 flex-1 cursor-pointer" onClick={() => setOpen(true)}>
          <div className="flex items-center gap-1.5">
            <span className="truncate text-xs font-medium">{item.title || "Untitled"}</span>
            {needsConsent && <Tip content="Consent needed before this person's face or voice is used"><ShieldAlert className="h-3.5 w-3.5 text-warn" /></Tip>}
            {item.consent.confirmed && <Tip content={`Consent recorded (${item.consent.statement === "self" ? "this is me" : "permission"})`}><ShieldCheck className="h-3.5 w-3.5 text-ok" /></Tip>}
          </div>
          <div className="truncate text-[11px] text-muted">{item.actor?.description || item.text || item.files.map((f) => f.split("/").pop()).join(", ") || "—"}</div>
          {!compact && !item.files.length && item.analysis?.auto_photo_error && (
            <div className="mt-1 text-[11px] text-warn">No photo found: {String(item.analysis.auto_photo_error).replace(/[.\s]+$/, "")}. Open this card and press “Find one for me”.</div>
          )}
          {!compact && (
            <div className="mt-1 flex flex-wrap gap-1">
              <Badge>{CTX_TYPES.find((t) => t.value === item.type)?.label}</Badge>
              <Badge tone="brand">{CTX_ROLES.find((r) => r.value === item.role)?.label}</Badge>
              {label && <Badge tone={inherited ? "neutral" : "info"}>{label}</Badge>}
              {item.analysis?.auto_photo && <Badge tone="info">photo found for you</Badge>}
            </div>
          )}
        </div>
        {inherited && onToggle && (
          <Tip content={inheritedOff ? "Switched off for this one — click to use it again" : "Inherited — switch off for this one"}>
            <span><Switch help="inherit-toggle" checked={!inheritedOff} onChange={(v) => onToggle(!v)} srLabel="Use this item here" /></span>
          </Tip>
        )}
      </div>
      <ContextDialog item={item} open={open} onOpenChange={setOpen} />
    </>
  );
}

export function ContextDialog({ item, open, onOpenChange }: { item: Ctx; open: boolean; onOpenChange: (v: boolean) => void }) {
  const P = useP();
  const p = P.view!.project;
  const save = (patch: any) => P.act("Save", () => api.patchContext(P.pid, item.id, patch));
  const langs = useQuery({ queryKey: ["languages"], queryFn: api.languages, staleTime: Infinity });
  const saveActor = (patch: any) => save({ actor: patch });
  const [playing, setPlaying] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [finding, setFinding] = useState(false);
  const settings = useSettings();
  const canClone = ["elevenlabs", "cartesia"].some((n) => settings.data?.plugins?.find((x: any) => x.name === n)?.configured);
  const a = item.actor;
  const isPerson = item.type === "actor" && (!a || ["ai_person", "real_person", "digital_twin"].includes(a.kind));
  const scopes = [{ value: "project", label: "Shared — all clips" },
    ...Object.entries(P.numbers).filter(([id, num]) => num && id !== p.root.id).map(([id, num]) => ({ value: `node:${id}`, label: `Part/clip ${num} and below` }))];
  const photos = item.analysis?.photos || {};
  const voiceCheck = item.analysis?.voice_check;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide title={<Editable value={item.title} onSave={(title) => save({ title })} ariaLabel="Title" />}
      description="Changes save automatically."
      footer={<Button variant="danger" onClick={() => { P.act("Delete", () => api.removeContext(P.pid, item.id), "Removed"); onOpenChange(false); }}><Trash2 className="h-3.5 w-3.5" />Remove</Button>}>
      <div className="space-y-4 text-xs">
        <div className="grid gap-3 sm:grid-cols-3">
          <div><div className="field-label mb-1">Type</div><Select value={item.type} onChange={(type) => save({ type, ...(type === "actor" && !a ? { actor: {} } : {}) })} options={CTX_TYPES} className="w-full" /></div>
          <div><div className="field-label mb-1">How it's used</div><Select value={item.role} onChange={(role) => save({ role })} options={CTX_ROLES} className="w-full" /></div>
          <div><div className="field-label mb-1">Applies to</div><Select value={item.scope.replace("clip:", "node:")} onChange={(scope) => save({ scope })} options={scopes} className="w-full" /></div>
        </div>

        <div>
          <div className="field-label mb-1">Files</div>
          <div className="flex flex-wrap gap-2">
            {item.files.map((f) => (
              <div key={f} className="group relative">
                {isImg(f) ? <img src={fileUrl(P.pid, f)} className="h-20 w-20 rounded-lg object-cover" alt="" />
                  : <div className="grid h-20 w-28 place-items-center rounded-lg bg-sunken px-2 text-center text-[11px]">{f.split("/").pop()}</div>}
                {photos[f.split("/").pop()!]?.problems?.length > 0 && <div className="absolute inset-x-0 bottom-0 rounded-b-lg bg-warn/90 px-1 text-[10px] text-white">{photos[f.split("/").pop()!].problems[0]}</div>}
                <button aria-label="Remove file" onClick={() => save({ files: item.files.filter((x) => x !== f) })}
                  className="absolute -right-1.5 -top-1.5 hidden h-5 w-5 place-items-center rounded-full bg-panel shadow group-hover:grid"><Trash2 className="h-3 w-3 text-bad" /></button>
              </div>
            ))}
            <DropZone compact className="h-20 w-28 grid place-items-center" label="+ Add files"
              onFiles={(files) => P.act("Upload", () => api.upload(P.pid, files, { ctx_id: item.id }), "Added")} />
          </div>
          {item.analysis?.auto_photo && (
            <div className="mt-2 rounded-lg bg-info/10 px-3 py-2 text-info">
              <div className="font-medium">The tool found this photo for you, because you did not add one.</div>
              <div className="mt-0.5 text-[11px]">Searched for “{item.analysis.auto_photo.query}”. Photo: {item.analysis.auto_photo.photo.title} by {item.analysis.auto_photo.photo.author} ({item.analysis.auto_photo.photo.license}). The credit is saved next to your video.</div>
              <div className="mt-1.5 flex gap-2">
                <Button help="choose-another-photo" size="sm" variant="outline" onClick={() => setFinding(true)}>Choose another photo</Button>
                <Button help="remove-auto-photo" size="sm" variant="ghost" onClick={() => save({ files: [] })}>Remove it</Button>
              </div>
            </div>
          )}
          {!item.analysis?.auto_photo && item.analysis?.auto_photo_error && item.files.length === 0 && (
            <div className="mt-2 rounded-lg bg-warn/10 px-3 py-2 text-warn">No photo was found automatically ({String(item.analysis.auto_photo_error).replace(/[.\s]+$/, "")}). Upload one, or pick one with Find a photo. Otherwise a picture is made with an AI image model.</div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button help="find-photo" size="sm" variant="outline" onClick={() => setFinding(true)}><Search className="h-3.5 w-3.5" />Find a photo</Button>
            {!isPerson && item.files.length === 0 && (
              <Button help="auto-photo" size="sm" variant="ghost" loading={P.busy.includes("Finding a photo")}
                onClick={() => P.act("Finding a photo", () => api.autoPhoto(P.pid, item.id), "Looking for a photo…")}>Find one for me</Button>
            )}
            {isPerson && <span className="text-[11px] text-muted">Photos of people must be uploaded (your own, or with permission).</span>}
          </div>
        </div>

        <div>
          <div className="field-label mb-1">{item.type === "actor" ? "Notes" : "Description / text"}</div>
          <Editable value={item.text} onSave={(text) => save({ text })} multiline placeholder={item.type === "text" ? "Facts to say, words to avoid, audience, tone…" : "Describe it in words (text alone is fine)"} />
        </div>

        {item.type === "actor" && (
          <div className="space-y-3 rounded-xl bg-sunken/60 p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div><div className="field-label mb-1">Kind</div>
                <Select value={a?.kind || "ai_person"} onChange={(kind) => saveActor({ kind })} className="w-full" options={[
                  { value: "ai_person", label: "AI-made person" }, { value: "real_person", label: "Real person (from photos/voice)" },
                  { value: "digital_twin", label: "My digital twin" }, { value: "animal", label: "Animal" }, { value: "product", label: "Product character" }]} /></div>
              <div><div className="field-label mb-1">Speaking speed (words/min)</div>
                <input type="number" defaultValue={a?.speaking_wpm || ""} placeholder="auto (~150)" onBlur={(e) => saveActor({ speaking_wpm: e.target.value ? Number(e.target.value) : null })}
                  className="h-7 w-full rounded-md border border-line bg-panel px-2" /></div>
            </div>
            <div><div className="field-label mb-1">Appearance</div><Editable value={a?.description || ""} onSave={(description) => saveActor({ description })} multiline placeholder="Age, build, skin tone, hair, features…" /></div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><div className="field-label mb-1">Clothing (default)</div><Editable value={a?.clothing || ""} onSave={(clothing) => saveActor({ clothing })} placeholder="e.g. blue kurta, white sneakers" /></div>
              <div><div className="field-label mb-1">Behaviour</div><Editable value={a?.behaviour || ""} onSave={(behaviour) => saveActor({ behaviour })} placeholder="Mannerisms, how they move and speak" /></div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <div className="field-label mb-1 flex items-center gap-1"><Mic className="h-3 w-3" />Voice sample</div>
                <div className="mb-1.5 text-[11px] text-muted">Used only to <b>copy the voice</b>. Your recording is not placed in the video; every script line is spoken fresh in that voice.</div>
                {a?.voice_sample && !canClone && (
                  <div className="mb-1.5 rounded-lg bg-warn/10 px-2 py-1.5 text-warn">
                    Not used yet: no voice-copying service is connected. A stock voice that matches the description is used instead.
                    <button className="ml-1 underline" onClick={() => { onOpenChange(false); P.openSettings("keys"); }}>Add an ElevenLabs key</button>
                  </div>
                )}
                {a?.voice_sample ? (
                  <div className="space-y-1">
                    <audio src={fileUrl(P.pid, a.voice_sample)} controls className="h-8 w-full" />
                    {voiceCheck?.problems?.map((x: string) => <div key={x} className="text-warn">{x}</div>)}
                    <div className="flex gap-3">
                      <button className="text-brand hover:underline" onClick={() => setRecording(true)}>Record again</button>
                      <button className="text-bad hover:underline" onClick={() => saveActor({ voice_sample: null, voice_id: null })}>Remove sample</button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <Button help="record-voice" size="sm" variant="primary" onClick={() => setRecording(true)}><Mic className="h-3.5 w-3.5" />Record my voice</Button>
                    <DropZone compact label="…or drop a voice file (30 s – 2 min)" accept="audio/*"
                      onFiles={(files) => P.act("Upload", () => api.upload(P.pid, files, { ctx_id: item.id }), "Voice sample added")} />
                  </div>
                )}
              </div>
              <div>
                <div className="field-label mb-1">Or describe the voice</div>
                <Editable value={a?.voice_description || ""} onSave={(voice_description) => saveActor({ voice_description })} placeholder="e.g. deep, warm, Indian English, slow" />
                <HelpTip id="voice-profile"><div className="field-label mb-1 mt-2">Voice profile</div></HelpTip>
                <div className="grid grid-cols-2 gap-1.5">
                  <Select value={a?.voice_gender || ""} onChange={(voice_gender) => saveActor({ voice_gender })} className="w-full" options={[
                    { value: "", label: "Gender: decide for me" }, { value: "male", label: "Male" }, { value: "female", label: "Female" }, { value: "neutral", label: "Neutral" }]} />
                  <Select value={a?.voice_age || ""} onChange={(voice_age) => saveActor({ voice_age })} className="w-full" options={[
                    { value: "", label: "Age: decide for me" }, { value: "child", label: "Child" }, { value: "teen", label: "Teen" }, { value: "young", label: "Young adult" },
                    { value: "adult", label: "Adult" }, { value: "older", label: "Older" }]} />
                  <Select value={a?.voice_pitch || ""} onChange={(voice_pitch) => saveActor({ voice_pitch })} className="w-full" options={[
                    { value: "", label: "Pitch: decide for me" }, { value: "low", label: "Low / deep" }, { value: "medium", label: "Medium" }, { value: "high", label: "High" }]} />
                  <Select value={a?.voice_pace || ""} onChange={(voice_pace) => saveActor({ voice_pace })} className="w-full" options={[
                    { value: "", label: "Pace: decide for me" }, { value: "slow", label: "Slow" }, { value: "normal", label: "Normal" }, { value: "fast", label: "Fast" }]} />
                </div>
                <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                  <Editable value={a?.voice_accent || ""} onSave={(voice_accent) => saveActor({ voice_accent })} placeholder="Accent, e.g. Indian English (every speaker needs one)" />
                  <Select title="The language this character speaks (their spoken words only; everything the tool writes stays English)" value={a?.language || ""} onChange={(language) => saveActor({ language })} className="w-full"
                    options={[{ value: "", label: "Speaks: the video's spoken language" }, ...(langs.data || []).map((l) => ({ value: l.code, label: `${l.name} (${l.code})` }))]} />
                </div>
                {a?.voice_accent_label && <div className="mt-1 text-[11px] text-muted">The chosen voice is labelled “{a.voice_accent_label}” by the voice service.</div>}
                {a?.voice_name && <div className="mt-1.5 text-[11px] text-muted">Voice chosen: <b>{a.voice_name}</b></div>}
                {a?.voice_note && <div className="mt-1 rounded-md bg-warn/10 px-2 py-1 text-[11px] text-warn">{a.voice_note}</div>}
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Button help="preview-voice" size="sm" variant="ghost" loading={P.busy.includes("Voice preview")}
                    onClick={async () => { const r: any = await P.act("Voice preview", () => api.voicePreview(P.pid, item.id)); if (r?.url) { setPlaying(r.url); } }}>
                    <Play className="h-3 w-3" />Preview voice</Button>
                  {!a?.voice_sample && (
                    <Button help="voice-next" size="sm" variant="ghost" loading={P.busy.includes("Another voice")}
                      onClick={() => P.act("Another voice", () => api.voiceNext(P.pid, item.id), "Switched to the next voice")}>Choose another voice</Button>
                  )}
                </div>
                {playing && <audio src={playing} autoPlay controls className="mt-1 h-8 w-full" />}
              </div>
            </div>
            {a?.reference_sheet?.length ? (
              <div><div className="field-label mb-1">Approved look (used in every clip)</div>
                <img src={fileUrl(P.pid, a.reference_sheet[0])} className="h-28 rounded-lg" alt="Reference sheet" />
                <button className="ml-2 text-muted hover:underline" onClick={() => saveActor({ reference_sheet: [] })}>Make a new one</button></div>
            ) : null}
            {(item.files.length > 0 || a?.voice_sample) && (
              <div className={cn("rounded-lg p-2.5", item.consent.confirmed ? "bg-ok/10" : "bg-warn/10")}>
                {item.consent.confirmed ? (
                  <div className="flex items-center gap-2 text-ok"><ShieldCheck className="h-4 w-4" />Consent recorded: {item.consent.statement === "self" ? "this is me" : "I have permission"} ({new Date(item.consent.confirmed_at).toLocaleDateString()})</div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-warn"><ShieldAlert className="h-4 w-4" />Before this face or voice is used, confirm one:</div>
                    <div className="flex gap-2">
                      <Button help="consent-self" size="sm" onClick={() => P.act("Consent", () => api.consent(P.pid, item.id, "self"), "Consent recorded")}>This is me</Button>
                      <Button help="consent-permission" size="sm" onClick={() => P.act("Consent", () => api.consent(P.pid, item.id, "permission"), "Consent recorded")}>I have this person's permission</Button>
                    </div>
                    <div className="text-[11px] text-muted">Realistic videos of public figures without consent are not allowed.</div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
      <RecordVoiceDialog item={item} open={recording} onOpenChange={setRecording} />
      <StockSearch item={item} open={finding} onOpenChange={setFinding} />
    </Dialog>
  );
}
