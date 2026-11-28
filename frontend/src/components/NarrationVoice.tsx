import { Mic, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, Ctx, fileUrl, Node, Script } from "../api";
import { useP } from "../lib";
import { Button, Dialog, Select } from "../ui";
import { VoiceRecorder } from "./VoiceRecorder";

/** Who speaks a clip's narration (the Narrator, or any character — including a voice copied from a sample), or your
 *  own recording placed exactly as it is. */
export default function NarrationVoice({ node, script, actors, onSave }: { node: Node; script: Script; actors: Ctx[]; onSave: (patch: Partial<Script>) => void }) {
  const P = useP();
  const [recording, setRecording] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const own = script.narration_audio;
  const busy = P.busy.includes("Saving recording");
  const place = async (blob: Blob, filename: string) => {
    const r = await P.act("Saving recording", () => api.narrationRecording(P.pid, node.id, blob, filename),
      "Your recording is placed on this clip exactly as it is");
    if (r) { P.set(r); setRecording(false); }
  };
  const speakers = actors.filter((a) => a.actor);
  return (
    <div className="mt-2 space-y-1.5 text-[11px]">
      {!own && (
        <label className="flex flex-wrap items-center gap-1.5 text-muted">
          <span>Spoken by</span>
          <Select title="Who speaks this clip's narration" value={script.narration_by || ""} onChange={(narration_by) => onSave({ narration_by })}
            options={[{ value: "", label: "The Narrator" }, ...speakers.map((a) => ({ value: a.id, label: `${a.title}${a.actor?.voice_sample ? " (copied voice)" : ""}` }))]} />
          <span>· the voice is made from the text; its accent comes from the speaker's card</span>
        </label>
      )}
      {own ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-sunken p-2">
          <span className="font-medium">Your recording</span>
          <audio src={fileUrl(P.pid, own)} controls className="h-8" />
          {script.narration_seconds ? <span className="text-muted">{script.narration_seconds.toFixed(1)} s</span> : null}
          <Button size="sm" variant="ghost" onClick={() => P.act("Remove recording", () => api.clearNarrationRecording(P.pid, node.id), "Recording removed").then((r) => r && P.set(r))}>
            <Trash2 className="h-3.5 w-3.5" />Remove</Button>
          <span className="w-full text-muted">Placed exactly as you recorded it (no made voice). The clip's length follows it; the text above is used for the subtitles.</span>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setRecording(true)}><Mic className="h-3.5 w-3.5" />Record my voice for this clip</Button>
          <Button size="sm" variant="ghost" loading={busy} onClick={() => file.current?.click()}><Upload className="h-3.5 w-3.5" />Upload a recording</Button>
          <input ref={file} type="file" accept="audio/*,.m4a,.mp3,.wav,.aac,.ogg,.webm" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) place(f, f.name); e.target.value = ""; }} />
        </div>
      )}
      <Dialog open={recording} onOpenChange={setRecording} wide title="Record the narration for this clip"
        description="It is placed on the clip exactly as you record it. Nothing leaves this computer.">
        <VoiceRecorder onCancel={() => setRecording(false)} onUse={async (blob, filename) => { await place(blob, filename); }} />
      </Dialog>
    </div>
  );
}
