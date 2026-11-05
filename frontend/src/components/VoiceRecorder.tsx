import { Check, Mic, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, Ctx } from "../api";
import { useP, useSettings } from "../lib";
import { Button, Dialog, Meter } from "../ui";

const SCRIPT = `Please read this aloud in your normal speaking voice, about a metre from the microphone, in a quiet room.

"Good morning, and thank you for having me. Today I would like to tell you a short story. It begins on a quiet street, just after the rain, when the whole city smells fresh and new. Have you ever noticed how a simple hello can change the mood of an entire day? I think about that often. Sometimes I speak softly. Sometimes I get excited and the words come quickly! And sometimes, I simply pause, and let the silence do the talking. Numbers help too: one, two, three, four, five, ten, twenty, one hundred. Now, let me ask you a question: how are you, and what would you like to create today?"`;

type Phase = "idle" | "recording" | "review";
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function friendlyError(e: any): string {
  const name = e?.name || "";
  if (!navigator.mediaDevices?.getUserMedia)
    return `This address cannot use the microphone. Open the app at http://localhost:${location.port || 8765} instead, and try again.`;
  if (name === "NotAllowedError" || name === "SecurityError")
    return "The microphone is blocked. In Safari: Safari menu → Settings → Websites → Microphone → set this site to Allow. In Chrome: click the lock icon next to the address.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone was found. Connect one and try again.";
  if (name === "NotReadableError") return "The microphone is being used by another app. Close it and try again.";
  return e?.message || "Could not start the microphone.";
}

export function VoiceRecorder({ onUse, onCancel }: { onUse: (blob: Blob, filename: string, consentSelf: boolean) => Promise<void>; onCancel?: () => void }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [secs, setSecs] = useState(0);
  const [level, setLevel] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState("");
  const [ext, setExt] = useState("webm");
  const [consent, setConsent] = useState(false);
  const [saving, setSaving] = useState(false);
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const raf = useRef(0);
  const timer = useRef<any>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const started = useRef(0);

  const cleanup = () => {
    cancelAnimationFrame(raf.current);
    clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    audioCtx.current?.close().catch(() => {});
    audioCtx.current = null;
    setLevel(0);
  };
  useEffect(() => () => { cleanup(); if (url) URL.revokeObjectURL(url); }, []); // eslint-disable-line

  const start = async () => {
    setError("");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
      stream.current = s;
      const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
      const mime = types.find((t) => (window as any).MediaRecorder?.isTypeSupported?.(t)) || "";
      const r = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
      const chunks: Blob[] = [];
      r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      r.onstop = () => {
        const type = r.mimeType || mime || "audio/webm";
        const b = new Blob(chunks, { type });
        setExt(type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm");
        setBlob(b);
        if (url) URL.revokeObjectURL(url);
        setUrl(URL.createObjectURL(b));
        setPhase("review");
        cleanup();
      };
      // live level meter
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
      audioCtx.current = ctx;
      const an = ctx.createAnalyser();
      an.fftSize = 1024;
      ctx.createMediaStreamSource(s).connect(an);
      const buf = new Uint8Array(an.fftSize);
      const loop = () => {
        an.getByteTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) { const x = (v - 128) / 128; sum += x * x; }
        setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
        raf.current = requestAnimationFrame(loop);
      };
      loop();
      r.start(250);
      rec.current = r;
      started.current = Date.now();
      setSecs(0);
      timer.current = setInterval(() => setSecs((Date.now() - started.current) / 1000), 200);
      setPhase("recording");
    } catch (e: any) {
      cleanup();
      setError(friendlyError(e));
    }
  };
  const stop = () => { if (rec.current && rec.current.state !== "inactive") rec.current.stop(); };
  const again = () => { setBlob(null); setPhase("idle"); setSecs(0); setConsent(false); };
  const use = async () => {
    if (!blob) return;
    setSaving(true);
    try { await onUse(blob, `recording.${ext}`, consent); } finally { setSaving(false); }
  };

  const tooShort = secs < 10;
  const good = secs >= 30;
  return (
    <div className="space-y-4 text-xs">
      <div className="rounded-xl bg-brand/10 px-3 py-2 text-brand">
        <b>What this is for:</b> your recording is used only to <b>copy your voice</b>. It is not placed in the video. Every line of the script is spoken fresh in a copy of this voice.
      </div>
      <div className="whitespace-pre-wrap rounded-xl bg-sunken/70 p-3 leading-relaxed text-[13px]">{SCRIPT}</div>

      {phase !== "review" && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            {phase === "idle" ? (
              <Button help="start-recording" variant="primary" size="lg" onClick={start} className="bg-bad hover:brightness-110"><Mic className="h-4 w-4" />Start recording</Button>
            ) : (
              <Button size="lg" onClick={stop} variant="primary" className="bg-bad"><Square className="h-4 w-4" />Stop</Button>
            )}
            <div className="flex-1">
              <div className="flex items-center justify-between text-xs">
                <span className="inline-flex items-center gap-1.5">
                  {phase === "recording" && <span className="h-2 w-2 animate-pulse rounded-full bg-bad" />}
                  <span className="tabular-nums font-medium">{clock(secs)}</span>
                </span>
                <span className="text-muted">Aim for 30 seconds to 2 minutes</span>
              </div>
              <div className="mt-1" aria-label="Microphone level"><Meter value={level * 100} max={100} tone={level > 0.9 ? "bad" : "ok"} /></div>
              {phase === "recording" && <div className="mt-1 text-[11px] text-muted">{secs < 30 ? "Keep reading… the longer, the better the copy." : "Good length. Stop whenever you like."}</div>}
              {phase === "recording" && level < 0.03 && secs > 2 && <div className="mt-1 text-warn">We cannot hear you. Check that the right microphone is selected.</div>}
            </div>
          </div>
        </div>
      )}

      {phase === "review" && blob && (
        <div className="space-y-3">
          <audio src={url} controls className="h-9 w-full" />
          <div className={tooShort ? "text-warn" : good ? "text-ok" : "text-muted"}>
            {tooShort ? `Only ${clock(secs)} — a copy needs at least 10 seconds; 30 seconds or more is best.` : good ? `${clock(secs)} — a good length.` : `${clock(secs)} — usable. 30 seconds or more gives a better copy.`}
          </div>
          <label className="flex items-start gap-2 rounded-lg bg-warn/10 p-2.5">
            <input type="checkbox" className="mt-0.5 accent-[rgb(var(--brand))]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>This is my own voice (or I have the speaker's permission to copy it). A copy of a voice must never be made without permission.</span>
          </label>
          <div className="flex gap-2">
            <Button help="use-recording" helpExtra={!consent ? "Tick the box above first." : undefined} variant="primary" onClick={use} loading={saving} disabled={!consent}><Check className="h-3.5 w-3.5" />Use this recording</Button>
            <Button onClick={again}><RotateCcw className="h-3.5 w-3.5" />Record again</Button>
            {onCancel && <Button variant="ghost" onClick={onCancel}>Cancel</Button>}
          </div>
        </div>
      )}
      {error && <div className="rounded-lg bg-bad/10 px-3 py-2 text-bad">{error}</div>}
    </div>
  );
}

export function RecordVoiceDialog({ item, open, onOpenChange }: { item: Ctx | undefined; open: boolean; onOpenChange: (v: boolean) => void }) {
  const P = useP();
  const settings = useSettings();
  if (!item) return null;
  const canClone = ["elevenlabs", "cartesia"].some((n) => settings.data?.plugins?.find((p: any) => p.name === n)?.configured);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide title={`Record a voice sample for ${item.title}`}
      description="Record in your browser. Nothing leaves this computer until a voice service copies it.">
      {settings.data && !canClone && (
        <div className="mb-3 rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn">
          No voice-copying service is connected yet, so this sample will not be used for now. Add an ElevenLabs key in Settings and it will be.
          <button className="ml-2 underline" onClick={() => { onOpenChange(false); P.openSettings("keys"); }}>Open Settings</button>
        </div>
      )}
      <VoiceRecorder onCancel={() => onOpenChange(false)}
        onUse={async (blob, filename, consent) => {
          const r = await P.act("Saving recording", () => api.voiceRecording(P.pid, item.id, blob, filename, consent), "Voice sample saved");
          if (r) onOpenChange(false);
        }} />
    </Dialog>
  );
}
