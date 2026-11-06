// Thin typed client for the local video-generator API.

export type NodeKind = "goal" | "clip" | "slides" | "user_clip";
export type Status = "draft" | "ready" | "waiting" | "queued" | "generating" | "needs_pick" | "done" | "stale" | "failed";
export type CtxType = "actor" | "object" | "entity" | "location" | "style" | "audio" | "text" | "media";
export type CtxRole = "must_appear" | "look_reference" | "start_frame" | "end_frame" | "voice" | "sound" | "music_reference" | "knowledge" | "include";

export interface CostLine { item: string; calc: string; cost: number }
export interface Cost { min_usd: number; likely_usd: number; max_usd: number; lines: CostLine[]; model: string; basis: string; actual_usd: number | null }
export interface Duration { min_s: number; likely_s: number; max_s: number; basis: "goal" | "script" | "actual"; explain: string }
export interface ActorInShot { actor_id: string; clothing: string; behaviour: string }
export interface Line { speaker: string; text: string; emotion: string; fixed?: boolean }
export interface Script {
  shot_type: string; visual: string; action_beats: string[]; camera: string; actors_in_shot: ActorInShot[];
  dialogue: Line[]; narration: string; narration_fixed?: boolean; on_camera_speech: boolean; sound_notes: string; start_state: string; end_state: string; negative: string; target_seconds: number | null;
}
export interface Take { id: string; version: number; index: number; video: string | null; keyframe: string | null; model: string; cost_usd: number; seconds: number; quality: Record<string, number>; review_id: string | null }
export type Join = "" | "continues" | "same_scene" | "cut";
export interface Continuity { join: Join; join_reason: string; place: string; present: string[]; start_state: string; end_state: string; carry_over: string; difference: number | null }
export interface Version { version: number; script: Script; feedback: string; created_at: string }
export interface Node {
  id: string; kind: NodeKind; title: string; goal: string; children: Node[]; target_seconds: number | null;
  style_overrides: Record<string, string>; context_add: string[]; context_off: string[]; context_override: Record<string, string>;
  script: Script | null; media: string | null; provider_override: string | null; takes_override: number | null; transition_in: string;
  status: Status; duration: Duration; cost: Cost; time: { likely_s: number; explain: string }; version: number; versions: Version[];
  takes: Take[]; chosen_take: string | null; voice_audio: string | null; voice_seconds: number | null; output: string | null;
  warnings: string[]; needs_split: boolean; review_enabled: boolean;
  locked?: boolean; quality_mode?: "best" | "balanced" | "budget" | "free" | null; ambience?: boolean | null; continuity?: Continuity; blocked?: string;
}
export interface Actor { kind: string; description: string; clothing: string; behaviour: string; voice_description: string; voice_gender: string; voice_age: string; voice_pitch: string; voice_pace: string; voice_accent: string; voice_accent_label?: string; language?: string; voice_name: string; voice_note: string; voice_sample: string | null; voice_provider: string | null; voice_id: string | null; speaking_wpm: number | null; props: string; reference_sheet: string[]; avatar_id: string | null }
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
export interface Settings { auto_photo: boolean; length_mode: "auto" | "fixed"; target_seconds: number; aspect: string; resolution: string; fps: number; format: "mp4" | "mov"; budget_usd: number; takes_people: number; takes_other: number; language: string; default_wpm: number; subtitles: boolean; auto_pick: boolean; review_enabled: boolean; music: boolean; ambience: boolean; fill: "blur" | "black" | "crop"; quality_mode: string }
export interface Project {
  id: string; name: string; goal: string; settings: Settings; style: { look: string; colour: string; mood: string; notes: string };
  root: Node; context: Ctx[]; dependencies: Dep[]; reviews: Review[];
  run: { mode: string; status: string; targets: string[]; message: string; started_at: string; spent_usd: number };
  music_advice: string; final_output: string | null; final_review_id: string | null; updated_at: string;
}
export interface GuideAction { kind: string; label: string; id?: string; ids?: string[]; node?: string; mode?: string; title?: string; targets?: string[]; help?: string }
export interface GuideStep { id: string; title: string; state: "done" | "current" | "attention" | "todo"; detail: string; action: GuideAction | null; also: { text: string; action: GuideAction }[] }
export interface Guide { headline: string; current: string | null; why: string; action: GuideAction | null; steps: GuideStep[]; issues: { text: string; action: GuideAction }[]; progress: { done: number; total: number } }
export interface PartRow {
  id: string; number: string; title: string; kind: NodeKind; depth: number; seconds: number; cost: number; cost_min: number; cost_max: number;
  time_s: number; quality: string; quality_own?: boolean; models: string[]; clips: number; done: number;
}
export interface FixAction { action: string; label: string; node?: string; join?: string; id?: string }
export interface Finding { code: string; node: string; number: string; severity: "problem" | "note"; text: string; fixes: FixAction[] }
export interface ScaleResult { requested: number; achieved: number; changed: { id: string; number: string; from: number; to: number }[]; kept: string[]; note: string }
export interface Summary {
  guide: Guide; continuity?: Finding[];
  length_mode: "auto" | "fixed"; language: string; quality_mode: string; parts: PartRow[];
  seconds: number; seconds_min: number; seconds_max: number; target_seconds: number; cost: number; cost_min: number; cost_max: number; cost_total: number;
  time_s: number; spent: number; budget: number; warnings: string[]; waiting_picks: number; review_flags: number; clips: number; done: number;
  numbers: Record<string, string>; brain: string;
  preview: { clips: Record<string, string[]>; causes: Record<string, Record<string, "pinned" | "no_key" | "free_mode" | "not_covered">>; pinned: string[]; jobs: Record<string, string>; all_preview: boolean; chosen_free_mode: boolean; voice_sample_unused: string[] };
  final_ready: boolean; final_stale: boolean; all_clips_done: boolean;
}
export interface Activity { node: string; step: string; elapsed_s: number; step_elapsed_s: number; started: number; since: number; now: number; expected_s: number }
export interface View { scale?: ScaleResult; project: Project; summary: Summary; engine: { active: boolean; running_clips: string[]; activity: Activity[] } }
export interface StockPhoto { source: string; title: string; thumb: string; url: string; width: number; height: number; author: string; license: string; source_url: string }
export interface Estimate { clips: string[]; extra_upstream: string[]; cost_usd: number; time_s: number; spent_usd: number; budget_usd: number; over_budget: boolean; blocked?: { id: string; number: string; why: string }[]; reuses?: string[] }
export interface OptMeasure { seconds: number; cost: number; cost_total: number; time_s: number; clips: number; to_make: number }
export interface OptDelta { seconds: number; cost: number; time_s: number }
export interface OptEdit { id: string; level: number; kind: string; nodes: string[]; numbers: string[]; value: any; label: string; loses: string; reason: string; kept: string; effect: OptDelta; checked: boolean }
export interface OptLevel { level: number; name: string; help: string; edits: string[]; after: OptMeasure; saves: OptDelta; meets_goal: boolean; available: boolean }
export interface OptProposal {
  scope: { id: string; number: string; title: string; is_whole_video: boolean }; goal: { length: number | null; cost: number | null; lowest: boolean };
  max_level: number; met: boolean; stopped_at: number; reason: string; notes: string[]; before: OptMeasure; after: OptMeasure; saves: OptDelta;
  levels: OptLevel[]; edits: OptEdit[]; joins: { kept: number; of: number; broken: string[] }; findings: Finding[]; protected: { numbers: string[]; count: number };
  ai: { available: boolean; clips: number; cost_low: number; cost_high: number; model?: string; why: string };
}
export interface OptRequest { scope?: string; length?: number | null; cost?: number | null; lowest?: boolean; max_level?: number; ticked?: string[]; protect?: string[]; ai_edits?: any[] }
export interface OptAi { edits: any[]; valid: any[]; skipped: string[]; note: string; cost_usd: number }
export interface ModeCost { cost: number; cost_todo: number; cost_min: number; cost_max: number; seconds: number; time_s: number; models: string[]; clips: number; to_make: number }
export interface ModeCosts { current: string; effective: string; inherits: string; is_whole_video: boolean; modes: Record<string, ModeCost> }
export interface BudgetRow { at: string; what: string; vendor: string; model: string; how: string; estimated: number; actual: number }
export interface BudgetGroup { key: string; label: string; calls: number; estimated: number; actual: number; rows: BudgetRow[] }
export interface BudgetReport {
  budget: number; spent: number; ledger_total: number; remaining_estimate: number; left_in_budget: number;
  groups: BudgetGroup[]; brain: { plugin: string; model: string; price: string }; explain: string[];
}
export interface ModelRow {
  id: string; job: string; plugin: string; model: string; vendor: string; enabled: boolean; quality: number; note: string;
  strengths: Record<string, number>; capabilities: Record<string, any>; price: { unit: string; usd: number; usd_in: number; usd_out: number };
  usable: boolean; why_not: string; price_text: string; unit_price: number; is_free: boolean; abilities: string[]; days_old: number;
  price_verified: boolean; last_checked: string; pricing_url: string; draft_cost_usd?: number; source: string;
}
export interface FoundModel { id: string; name: string; vendor: string; plugin: string | null; in_catalogue: boolean }
export interface MusicStatus {
  enabled: boolean; total_s: number; saved: boolean; reusable: boolean; why: string; made_for_s: number; model: string; free: boolean;
  cost_new_usd: number; cost_usd: number;
}
export interface ExportResult {
  needs_music_choice?: boolean; cost_usd?: number; model?: string; seconds?: number;
  path?: string; url?: string; srt?: string | null; srt_url?: string; filename?: string; with_music?: boolean; notes?: string[];
}
export interface Ballpark {
  mode: string; real: boolean; per_minute: { low: number; high: number }; total: { low: number; high: number } | null; seconds: number | null;
  lines: { item: string; low: number; high: number }[]; models: Record<string, string>;
}
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
  health: () => req<{ ok: boolean; ffmpeg: boolean; brain: string; default_budget: number; default_quality: string }>("GET", "/api/health"),
  languages: () => req<{ code: string; name: string }[]>("GET", "/api/languages"),
  ballpark: (seconds: number, quality: string) => req<Ballpark>("GET", `/api/ballpark?seconds=${seconds || 0}&quality=${encodeURIComponent(quality)}`),
  projects: () => req<{ id: string; name: string; goal: string; updated_at: string; final_output: string | null }[]>("GET", "/api/projects"),
  create: (fd: FormData) => req<{ id: string }>("POST", "/api/projects", fd),
  get: (pid: string) => req<View>("GET", P(pid)),
  patch: (pid: string, patch: any) => req<View>("PATCH", P(pid), patch),
  remove: (pid: string) => req<any>("DELETE", P(pid)),
  redraft: (pid: string) => req<any>("POST", `${P(pid)}/draft`),
  undo: (pid: string) => req<View>("POST", `${P(pid)}/undo`),
  redo: (pid: string) => req<View>("POST", `${P(pid)}/redo`),
  budget: (pid: string) => req<BudgetReport>("GET", `${P(pid)}/budget`),
  explain: (pid: string, question: string, focus?: string) => req<{ answer: string }>("POST", `${P(pid)}/explain`, { question, focus }),
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
  autoPhoto: (pid: string, cid: string) => req<any>("POST", `${P(pid)}/context/${cid}/auto-photo`),
  stockAdd: (pid: string, cid: string, photo: StockPhoto) => req<View>("POST", `${P(pid)}/context/${cid}/stock`, photo),
  voicePreview: (pid: string, cid: string) => req<{ url: string; name?: string }>("POST", `${P(pid)}/context/${cid}/voice-preview`),
  voiceNext: (pid: string, cid: string) => req<View>("POST", `${P(pid)}/context/${cid}/voice-next`),

  addDep: (pid: string, from_id: string, to_id: string, type: string) => req<View>("POST", `${P(pid)}/deps`, { from_id, to_id, type }),
  patchDep: (pid: string, did: string, type: string) => req<View>("PATCH", `${P(pid)}/deps/${did}`, { type }),
  removeDep: (pid: string, did: string) => req<View>("DELETE", `${P(pid)}/deps/${did}`),
  suggestDeps: (pid: string) => req<View>("POST", `${P(pid)}/deps/suggest`),

  estimate: (pid: string, body: { mode?: string; targets?: string[] }) => req<Estimate>("POST", `${P(pid)}/estimate`, body),
  run: (pid: string, mode: string, targets?: string[], auto_pick?: boolean) => req<View>("POST", `${P(pid)}/run`, { mode, targets, auto_pick }),
  pause: (pid: string) => req<View>("POST", `${P(pid)}/pause`),
  resume: (pid: string) => req<View>("POST", `${P(pid)}/resume`),
  stop: (pid: string) => req<View>("POST", `${P(pid)}/stop`),
  splitClip: (pid: string, nid: string) => req<View>("POST", `${P(pid)}/nodes/${nid}/split`),
  assemble: (pid: string, music: "auto" | "reuse" | "new" | "none" = "auto") => req<any>("POST", `${P(pid)}/assemble`, { music }),
  musicStatus: (pid: string) => req<MusicStatus>("GET", `${P(pid)}/music`),
  exportNode: (pid: string, nid: string, music: "auto" | "new" | "none" = "auto") => req<ExportResult>("POST", `${P(pid)}/nodes/${nid}/export`, { music }),
  setJoin: (pid: string, nid: string, join: Join, reason = "") => req<View>("POST", `${P(pid)}/nodes/${nid}/join`, { join, reason }),
  optimizePropose: (pid: string, body: OptRequest) => req<OptProposal>("POST", `${P(pid)}/optimize/propose`, body),
  optimizeAi: (pid: string, body: OptRequest) => req<OptAi>("POST", `${P(pid)}/optimize/ai`, body),
  optimizeApply: (pid: string, body: OptRequest) => req<View>("POST", `${P(pid)}/optimize/apply`, body),
  rewriteOffer: (pid: string, nid: string) => req<{ clips: number; numbers: string[]; kept: string[]; cost_usd: number }>("GET", `${P(pid)}/nodes/${nid}/rewrite-offer`),
  modeCosts: (pid: string, nid: string) => req<ModeCosts>("GET", `${P(pid)}/nodes/${nid}/mode-costs`),
  fixContinuity: (pid: string, body: { action: string; node?: string; join?: string }) => req<View>("POST", `${P(pid)}/continuity/fix`, body),
  unpin: (pid: string, ids?: string[]) => req<View>("POST", `${P(pid)}/unpin`, ids ? { ids } : {}),
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
  refreshModels: () => req<{ models: FoundModel[]; errors: Record<string, string>; skipped: string[] }>("POST", "/api/models/llm/refresh"),
  addModel: (plugin: string, model: string, usd_in: number, usd_out: number) => req<any>("POST", "/api/catalog/llm", { plugin, model, usd_in, usd_out }),
};

export const fileUrl = (pid: string, rel?: string | null) => (rel ? `/files/${encodeURIComponent(pid)}/${rel}` : "");
