// Thin typed client for the local video-generator API.

export type NodeKind = "goal" | "clip" | "slides" | "user_clip";
export type Status = "draft" | "ready" | "waiting" | "queued" | "generating" | "needs_pick" | "done" | "stale" | "failed";
export type CtxType = "actor" | "object" | "entity" | "location" | "style" | "audio" | "text" | "media";
export type CtxRole = "must_appear" | "look_reference" | "start_frame" | "end_frame" | "voice" | "sound" | "music_reference" | "knowledge" | "include";

export interface CostLine { item: string; calc: string; cost: number }
export interface Cost { min_usd: number; likely_usd: number; max_usd: number; lines: CostLine[]; model: string; basis: string; actual_usd: number | null }
export interface Duration { min_s: number; likely_s: number; max_s: number; basis: "goal" | "script" | "actual"; explain: string }
export interface ActorInShot { actor_id: string; clothing: string; behaviour: string }
export interface Line { speaker: string; text: string; emotion: string }
export interface Script {
  shot_type: string; visual: string; action_beats: string[]; camera: string; actors_in_shot: ActorInShot[];
  dialogue: Line[]; narration: string; on_camera_speech: boolean; sound_notes: string; negative: string; target_seconds: number | null;
}
export interface Take { id: string; version: number; index: number; video: string | null; keyframe: string | null; model: string; cost_usd: number; seconds: number; quality: Record<string, number>; review_id: string | null }
export interface Version { version: number; script: Script; feedback: string; created_at: string }
export interface Node {
  id: string; kind: NodeKind; title: string; goal: string; children: Node[]; target_seconds: number | null;
  style_overrides: Record<string, string>; context_add: string[]; context_off: string[]; context_override: Record<string, string>;
  script: Script | null; media: string | null; provider_override: string | null; takes_override: number | null; transition_in: string;
  status: Status; duration: Duration; cost: Cost; time: { likely_s: number; explain: string }; version: number; versions: Version[];
  takes: Take[]; chosen_take: string | null; voice_audio: string | null; voice_seconds: number | null; output: string | null;
  warnings: string[]; review_enabled: boolean;
}
export interface Actor { kind: string; description: string; clothing: string; behaviour: string; voice_description: string; voice_sample: string | null; voice_provider: string | null; voice_id: string | null; speaking_wpm: number | null; props: string; reference_sheet: string[]; avatar_id: string | null }
export interface Ctx {
  id: string; type: CtxType; title: string; text: string; files: string[]; role: CtxRole; scope: string; actor: Actor | null;
  consent: { confirmed: boolean; statement: string; confirmed_by: string; confirmed_at: string; files: string[] }; analysis: Record<string, any>;
}
export interface Dep { id: string; from_id: string; to_id: string; type: string; source: string; note: string; payload: Record<string, any> }
export interface Review {
  id: string; target: string; verdict: "meets_goal" | "minor_issues" | "does_not_meet_goal"; scores: Record<string, number>;
  issues: { check: string; text: string; at_s: number | null; frame: string | null; severity: string }[];
  suggestions: { id: string; text: string; accepted: boolean }[]; summary: string; reviewer_model: string; cost_usd: number;
}
export interface Settings { target_seconds: number; aspect: string; resolution: string; fps: number; format: "mp4" | "mov"; budget_usd: number; takes_people: number; takes_other: number; language: string; default_wpm: number; subtitles: boolean; auto_pick: boolean; review_enabled: boolean; music: boolean; quality_mode: string }
export interface Project {
  id: string; name: string; goal: string; settings: Settings; style: { look: string; colour: string; mood: string; notes: string };
  root: Node; context: Ctx[]; dependencies: Dep[]; reviews: Review[];
  run: { mode: string; status: string; targets: string[]; message: string; started_at: string; spent_usd: number };
  final_output: string | null; final_review_id: string | null; updated_at: string;
}
export interface Summary {
  seconds: number; seconds_min: number; seconds_max: number; target_seconds: number; cost: number; cost_min: number; cost_max: number;
  time_s: number; spent: number; budget: number; warnings: string[]; waiting_picks: number; review_flags: number; clips: number; done: number;
  numbers: Record<string, string>; brain: string;
  preview: { clips: Record<string, string[]>; jobs: Record<string, string>; all_preview: boolean; chosen_free_mode: boolean; voice_sample_unused: string[] };
  final_ready: boolean; final_stale: boolean; all_clips_done: boolean;
}
export interface Activity { node: string; step: string; elapsed_s: number; step_elapsed_s: number; started: number; since: number; now: number; expected_s: number }
export interface View { project: Project; summary: Summary; engine: { active: boolean; running_clips: string[]; activity: Activity[] } }
export interface StockPhoto { source: string; title: string; thumb: string; url: string; width: number; height: number; author: string; license: string; source_url: string }
export interface Estimate { clips: string[]; extra_upstream: string[]; cost_usd: number; time_s: number; spent_usd: number; budget_usd: number; over_budget: boolean }
export interface CommandPlan { summary: string; ops: { op: string; target: string; field: string; value: string }[] }

async function req<T>(method: string, url: string, body?: any): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as any)["Content-Type"] = "application/json";
  }
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

const P = (pid: string) => `/api/projects/${encodeURIComponent(pid)}`;

export const api = {
  health: () => req<any>("GET", "/api/health"),
  projects: () => req<{ id: string; name: string; goal: string; updated_at: string; final_output: string | null }[]>("GET", "/api/projects"),
  create: (fd: FormData) => req<{ id: string }>("POST", "/api/projects", fd),
  get: (pid: string) => req<View>("GET", P(pid)),
  patch: (pid: string, patch: any) => req<View>("PATCH", P(pid), patch),
  remove: (pid: string) => req<any>("DELETE", P(pid)),
  redraft: (pid: string) => req<any>("POST", `${P(pid)}/draft`),
  undo: (pid: string) => req<View>("POST", `${P(pid)}/undo`),
  redo: (pid: string) => req<View>("POST", `${P(pid)}/redo`),
  ledger: (pid: string) => req<any[]>("GET", `${P(pid)}/ledger`),

  addNode: (pid: string, body: any) => req<View & { new_id: string }>("POST", `${P(pid)}/nodes`, body),
  patchNode: (pid: string, nid: string, patch: any) => req<View>("PATCH", `${P(pid)}/nodes/${nid}`, patch),
  removeNode: (pid: string, nid: string) => req<View>("DELETE", `${P(pid)}/nodes/${nid}`),
  moveNode: (pid: string, nid: string, parent_id: string, index: number) => req<View>("POST", `${P(pid)}/nodes/${nid}/move`, { parent_id, index }),
  decompose: (pid: string, nid: string) => req<View>("POST", `${P(pid)}/nodes/${nid}/decompose`),
  writeScript: (pid: string, nid: string, feedback = "") => req<View>("POST", `${P(pid)}/nodes/${nid}/script`, { feedback }),
  revise: (pid: string, nid: string, instruction: string) => req<View>("POST", `${P(pid)}/nodes/${nid}/revise`, { instruction }),
  writeScripts: (pid: string, under?: string, overwrite = false) => req<View>("POST", `${P(pid)}/scripts`, { under, overwrite }),
  nodeContext: (pid: string, nid: string) => req<{ item: Ctx; origin: string; overridden_from: string | null }[]>("GET", `${P(pid)}/nodes/${nid}/context`),
  toggleContext: (pid: string, nid: string, cid: string, off: boolean) => req<View>("POST", `${P(pid)}/nodes/${nid}/context/${cid}/toggle`, { off }),

  planCommand: (pid: string, text: string, focus?: string) => req<CommandPlan>("POST", `${P(pid)}/command/plan`, { text, focus }),
  applyCommand: (pid: string, plan: CommandPlan) => req<View & { actions: any; run: any }>("POST", `${P(pid)}/command/apply`, { plan }),

  addContext: (pid: string, body: any) => req<View & { new_id: string }>("POST", `${P(pid)}/context`, body),
  upload: (pid: string, files: File[], opts: { scope?: string; ctx_id?: string; hint?: string; as_node?: boolean } = {}) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("scope", opts.scope || "project");
    if (opts.ctx_id) fd.append("ctx_id", opts.ctx_id);
    if (opts.hint) fd.append("hint", opts.hint);
    if (opts.as_node) fd.append("as_node", "1");
    return req<View & { new_ids: string[] }>("POST", `${P(pid)}/context/upload`, fd);
  },
  patchContext: (pid: string, cid: string, patch: any) => req<View>("PATCH", `${P(pid)}/context/${cid}`, patch),
  removeContext: (pid: string, cid: string) => req<View>("DELETE", `${P(pid)}/context/${cid}`),
  consent: (pid: string, cid: string, statement: "self" | "permission") => req<View>("POST", `${P(pid)}/context/${cid}/consent`, { statement }),
  voiceRecording: (pid: string, cid: string, blob: Blob, filename: string, consentSelf: boolean) => {
    const fd = new FormData();
    fd.append("file", blob, filename);
    fd.append("consent_self", consentSelf ? "true" : "");
    return req<View>("POST", `${P(pid)}/context/${cid}/voice-recording`, fd);
  },
  stockSearch: (q: string, source: string) => req<{ sources: string[]; results: StockPhoto[] }>("GET", `/api/stock/search?q=${encodeURIComponent(q)}&source=${source}`),
  stockAdd: (pid: string, cid: string, photo: StockPhoto) => req<View>("POST", `${P(pid)}/context/${cid}/stock`, photo),
  voicePreview: (pid: string, cid: string) => req<{ url: string }>("POST", `${P(pid)}/context/${cid}/voice-preview`),

  addDep: (pid: string, from_id: string, to_id: string, type: string) => req<View>("POST", `${P(pid)}/deps`, { from_id, to_id, type }),
  patchDep: (pid: string, did: string, type: string) => req<View>("PATCH", `${P(pid)}/deps/${did}`, { type }),
  removeDep: (pid: string, did: string) => req<View>("DELETE", `${P(pid)}/deps/${did}`),
  suggestDeps: (pid: string) => req<View>("POST", `${P(pid)}/deps/suggest`),

  estimate: (pid: string, body: { mode?: string; targets?: string[] }) => req<Estimate>("POST", `${P(pid)}/estimate`, body),
  run: (pid: string, mode: string, targets?: string[], auto_pick?: boolean) => req<View>("POST", `${P(pid)}/run`, { mode, targets, auto_pick }),
  pause: (pid: string) => req<View>("POST", `${P(pid)}/pause`),
  resume: (pid: string) => req<View>("POST", `${P(pid)}/resume`),
  stop: (pid: string) => req<View>("POST", `${P(pid)}/stop`),
  assemble: (pid: string) => req<any>("POST", `${P(pid)}/assemble`),
  pick: (pid: string, nid: string, take_id: string) => req<View>("POST", `${P(pid)}/nodes/${nid}/pick`, { take_id }),
  compare: (pid: string, nid: string, models: string[]) => req<any>("POST", `${P(pid)}/nodes/${nid}/compare`, { models }),

  patchSuggestion: (pid: string, rid: string, sid: string, patch: any) => req<View>("PATCH", `${P(pid)}/reviews/${rid}/suggestions/${sid}`, patch),
  remakePreview: (pid: string, nid: string, accepted: string[], feedback: string) => req<any>("POST", `${P(pid)}/nodes/${nid}/remake/preview`, { accepted, feedback }),
  remakeApply: (pid: string, nid: string, script: any, feedback: string) => req<View>("POST", `${P(pid)}/nodes/${nid}/remake/apply`, { script, feedback, generate: true }),
  revert: (pid: string, nid: string, version: number) => req<View>("POST", `${P(pid)}/nodes/${nid}/revert`, { version }),

  settings: () => req<any>("GET", "/api/settings"),
  patchSettings: (patch: any) => req<any>("PATCH", "/api/settings", patch),
  setKey: (name: string, value: string) => req<any>("POST", "/api/settings/keys", { name, value }),
  testPlugin: (plugin: string) => req<{ ok: boolean; message: string }>("POST", "/api/settings/test", { plugin }),
  patchCatalog: (id: string, patch: any) => req<any>("PATCH", `/api/catalog/${id}`, patch),
};

export const fileUrl = (pid: string, rel?: string | null) => (rel ? `/files/${encodeURIComponent(pid)}/${rel}` : "");
