"""The AI brain: vendor-neutral tasks built on the LLM plugin interface.

Every task sends the same prompt template to whichever LLM plugin is
configured (Anthropic, OpenAI, Gemini, or the offline rules engine) and
validates the answer against the same pydantic schema.
"""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Literal, Optional, Type

from pydantic import BaseModel, Field

from . import languages
from .context import effective_context, summarize_for_llm
from .models import (ActorInShot, ClipScript, Continuity, ContextType, DialogueLine, Node, Project, ShotType)
from .plugins.base import PluginError, Usage
from .registry import Registry
from . import routes as routes_mod
from .tree import ancestors, numbering, outline, walk

SHOT_TYPES = [s.value for s in ShotType]


# =========================================================== response schemas
class ActorDraft(BaseModel):
    name: str
    kind: Literal["ai_person", "real_person", "digital_twin", "animal", "product"] = "ai_person"
    description: str = ""
    clothing: str = ""
    behaviour: str = ""
    voice_description: str = ""
    # voice profile for every speaker (people of any age, animals, mascots, robots, the narrator)
    voice_gender: str = ""            # male | female | neutral
    voice_age: str = ""               # child | teen | young | adult | older
    voice_pitch: str = ""             # low | medium | high
    voice_pace: str = ""              # slow | normal | fast
    voice_accent: str = ""            # decided from who the character is (origin, background); never left empty for a speaker
    language: str = ""                # the language this character speaks (a short code); "" = the video's language
    speaking_wpm: Optional[int] = None   # words per minute this speaker really speaks (normal speech is about 150; slow delivery far fewer)


class PlannedContinuity(BaseModel):
    """What the planner decides for a clip before any script exists (copied to Node.continuity)."""
    join: str = ""                    # continues | same_scene | cut: how it joins the clip BEFORE it ("" only for the very first clip)
    join_reason: str = ""
    place: str = ""
    present: list[str] = Field(default_factory=list)
    start_state: str = ""
    end_state: str = ""
    carry_over: str = ""


JOINS = ("continues", "same_scene", "cut")


def normalize_join(value: str) -> str:
    """The planner's word for a join as one of continues | same_scene | cut ('' when unclear)."""
    v = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if v in JOINS:
        return v
    if v in ("continue", "continuous", "continuing", "same_shot", "continues_from"):
        return "continues"
    if v in ("same", "same_location", "same_place", "same_scene_new_angle"):
        return "same_scene"
    if v in ("new", "new_scene", "jump", "scene_change"):
        return "cut"
    return ""


def to_continuity(d: PlannedContinuity) -> Continuity:
    return Continuity(join=normalize_join(d.join), join_reason=d.join_reason.strip(), place=d.place.strip(), present=[x for x in d.present if x.strip()],
                      start_state=d.start_state.strip(), end_state=d.end_state.strip(), carry_over=d.carry_over.strip())


class ClipDraft(PlannedContinuity):
    title: str
    goal: str
    seconds: float = 6


class PartDraft(BaseModel):
    title: str
    goal: str
    seconds: float = 20
    clips: list[ClipDraft] = Field(default_factory=list)


class StyleDraft(BaseModel):
    look: str = ""
    colour: str = ""
    mood: str = ""


class ProjectDraft(BaseModel):
    title: str
    language: str = ""                # the language spoken in the video, a short code (en, hi …); "" = not decided
    style: StyleDraft = Field(default_factory=StyleDraft)
    actors: list[ActorDraft] = Field(default_factory=list)
    parts: list[PartDraft] = Field(default_factory=list)
    music_advice: str = ""            # "none", "subtle" or "full", then the mood/genre and where it should enter and leave


class ChildDraft(PlannedContinuity):
    title: str
    goal: str
    seconds: float = 6
    kind: Literal["clip", "goal"] = "clip"


class TightenEdit(BaseModel):
    clip: str                                       # the clip number as shown (for example 2.1)
    action: Literal["shorten", "drop", "merge_with_next"] = "shorten"
    dialogue: list[str] = Field(default_factory=list)   # for shorten: the new text of every spoken line, same order and count
    narration: Optional[str] = None
    reason: str = ""
    kept: str = ""                                  # what meaning is kept


class Tightening(BaseModel):
    edits: list[TightenEdit] = Field(default_factory=list)
    note: str = ""


class Decomposition(BaseModel):
    children: list[ChildDraft]
    note: str = ""


class ShotActor(BaseModel):
    actor_name: str
    clothing: str = ""
    behaviour: str = ""


class Line(BaseModel):
    speaker_name: str
    text: str
    emotion: str = ""
    fixed: bool = False               # true when this line must be spoken exactly as written (given text: a quote, a slogan, a name)


class SplitPart(BaseModel):
    title: str
    goal: str = ""
    seconds: float = 4
    shot_type: str = "other"
    motion: str = ""                  # face | body | scene
    visual: str = ""
    action_beats: list[str] = Field(default_factory=list)
    dialogue: list[Line] = Field(default_factory=list)
    narration: str = ""
    sound_notes: str = ""
    start_state: str = ""
    end_state: str = ""


class ClipSplit(BaseModel):
    parts: list[SplitPart]
    note: str = ""


class ClipScriptDraft(BaseModel):
    shot_type: str = "other"
    visual: str
    action_beats: list[str] = Field(default_factory=list)
    camera: str = ""
    actors_in_shot: list[ShotActor] = Field(default_factory=list)
    dialogue: list[Line] = Field(default_factory=list)
    narration: str = ""
    narration_fixed: bool = False     # the narration must be spoken exactly as written
    on_camera_speech: bool = False
    sound_notes: str = ""
    motion: str = ""                  # face | body | scene: what must move in this clip
    start_state: str = ""
    end_state: str = ""
    negative: str = ""
    continues_from_previous: bool = False
    same_location_as_previous: bool = False
    change_summary: str = ""


class GoalRevision(BaseModel):
    title: str
    goal: str
    seconds: float = 0
    change_summary: str = ""


class DepDraft(BaseModel):
    from_number: str
    to_number: str
    type: Literal["continues_from", "same_location", "actor_state", "audio_carry", "reference"]
    note: str = ""


class DepList(BaseModel):
    dependencies: list[DepDraft] = Field(default_factory=list)


class PhotoQuery(BaseModel):
    query: str


class PhotoChoice(BaseModel):
    choice: int = 1        # 1-based; 0 = none acceptable
    reason: str = ""


class Explained(BaseModel):
    answer: str


class Op(BaseModel):
    op: Literal["set_title", "set_goal", "set_seconds", "set_script", "add_child", "remove",
                "set_actor", "set_style", "generate", "regenerate_scripts"]
    target: str = ""          # node number like "1.2", actor name, or "project"
    field: str = ""
    value: str = ""


class CommandPlan(BaseModel):
    summary: str
    ops: list[Op] = Field(default_factory=list)


class IssueDraft(BaseModel):
    check: str
    text: str
    at_s: Optional[float] = None
    severity: Literal["info", "minor", "major"] = "minor"


class Scores(BaseModel):
    """1-5 each. 0 means "cannot be checked from the evidence given" (never guess a high score)."""
    goal: int = 3
    script: int = 3
    actors: int = 3
    behaviour: int = 3
    realism: int = 3          # photoreal stills: skin, eyes, hands, fur/hair, no AI artifacts
    motion: int = 0           # real, natural, physically plausible movement (not a slideshow / zoom)
    consistency: int = 0      # same identity, clothing, lighting, background across frames (no morphing)
    fidelity: int = 0         # sharp, no blur / banding / compression blocks
    audio: int = 0            # voice natural, clear, right level, matches the mouth
    continuity: int = 3
    timing: int = 3
    lipsync: int = 3


class ReviewDraft(BaseModel):
    verdict: Literal["meets_goal", "minor_issues", "does_not_meet_goal"]
    scores: Scores = Field(default_factory=Scores)
    issues: list[IssueDraft] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str = ""


# =========================================================== prompt templates
def template(name: str) -> str:
    return resources.files("video_generator.prompts").joinpath(f"{name}.md").read_text()


def render(name: str, **values) -> str:
    text = template(name)
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


SYSTEM = None


def system_prompt() -> str:
    global SYSTEM
    if SYSTEM is None:
        SYSTEM = template("system")
    return SYSTEM


# =========================================================== brain
class Brain:
    def __init__(self, reg: Registry):
        self.reg = reg
        self.last_usage = Usage()

    async def ask(self, task: str, prompt: str, schema: Type[BaseModel], meta: dict,
                  images: Optional[list[Path]] = None, video: Optional[Path] = None) -> BaseModel:
        errors = []
        for name in self.reg.llm_fallback_order(task):
            plugin = self.reg.plugin(name)
            model = self.reg.llm_model(task, name)
            try:
                result, usage = await plugin.generate_json(system=system_prompt(), user=prompt, schema=schema,
                                                           model=model, images=images, video=video, meta={"task": task, **meta})
                usage.cost_usd = self._cost(task, name, usage)
                usage.raw["plugin"] = name
                usage.raw["model"] = model
                self.last_usage = usage
                return result
            except PluginError as exc:
                errors.append(f"{name}: {exc}")
                continue
        raise PluginError("AI brain failed: " + " | ".join(errors))

    def _cost(self, task: str, plugin: str, usage: Usage) -> float:
        """What this call cost: the tokens the vendor reported times the price of the model that really answered."""
        e = self.reg.llm_entry(task, plugin_name=plugin)
        if e:
            return usage.input_tokens / 1e6 * e.price.usd_in + usage.output_tokens / 1e6 * e.price.usd_out
        return 0.0

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _context_block(project: Project, node_id: str) -> str:
        return summarize_for_llm(effective_context(project, node_id))

    @staticmethod
    def _actor_list(project: Project, node_id: Optional[str] = None) -> str:
        items = effective_context(project, node_id) if node_id else []
        actors = [e.item for e in items] if node_id else [c for c in project.context]
        lines = []
        for a in actors:
            if a.type == ContextType.actor and a.actor:
                lines.append(f"- {a.title} (id {a.id}, {a.actor.kind}): {a.actor.description}; clothing: {a.actor.clothing}; "
                             f"behaviour: {a.actor.behaviour}; voice: {a.actor.voice_description}"
                             + (f" [{', '.join(x for x in (a.actor.voice_gender, a.actor.voice_age, a.actor.voice_pitch + ' pitch' if a.actor.voice_pitch else '', a.actor.voice_pace + ' pace' if a.actor.voice_pace else '', a.actor.voice_accent + ' accent' if a.actor.voice_accent else '', 'speaks ' + a.actor.language if a.actor.language else '') if x)}]"
                                if (a.actor.voice_gender or a.actor.voice_age or a.actor.voice_pitch or a.actor.voice_pace or a.actor.voice_accent or a.actor.language) else "")
                             + ("; has photos" if a.files else "") + ("; has voice sample" if a.actor.voice_sample else ""))
        return "\n".join(lines) or "(no actors yet)"

    # ------------------------------------------------------------- tasks
    @staticmethod
    def length_blocks(project: Project) -> tuple[str, str]:
        """(the LENGTH line, the length rules) for the draft prompt. Auto = no length was asked for."""
        s = project.settings
        if s.length_mode == "auto":
            return ("LENGTH: none was given. Make the video as short as the story allows without losing its meaning or quality.",
                    "every spoken line is heard in full and at a natural pace, every clip is only as long as its speech and action need, "
                    "and there is no filler. The video's length is the sum of the clip seconds you give.")
        return (f"TARGET LENGTH: {s.target_seconds:g} seconds",
                "the clip seconds MUST add up to TARGET LENGTH (do not plan more).")

    @staticmethod
    def language_block(project: Project) -> str:
        code = languages.normalise(project.settings.language)
        if not code:
            return ("LANGUAGE: not set. Decide from the goal which language the people in this video speak, and return it as `language` "
                    "(a short code such as en, hi, ta).")
        return (f"LANGUAGE: the people in this video speak {languages.name_of(code)} ({code}). Write every spoken line and narration in "
                f"it, in the language's own script. Return `language` as {code}.")

    @staticmethod
    def language_line(project: Project) -> str:
        code = languages.normalise(project.settings.language)
        return (f"{languages.name_of(code)} ({code}): write dialogue and narration in it, in its own script." if code
                else "decided by the plan: use the language the goal and the actors' voice profiles imply.")

    @staticmethod
    def contract(project: Project, node: Node) -> str:
        """What the plan decided for this clip, as fixed text for its script writer (see models.Continuity)."""
        c = node.continuity
        prev = _previous_leaf(project, node)
        how = {"continues": "continues (this clip begins on the very last picture of the previous clip: the same shot goes on)",
               "same_scene": "same_scene (the same place and people; a new angle or a later moment)", "cut": "cut (a new place or a jump in time)"}
        lines: list[str] = []
        if prev is not None and c.join:
            lines.append(f"- JOIN with the previous clip: {how[c.join]}" + (f". Why: {c.join_reason}" if c.join_reason else ""))
        prev_end = ""
        if prev is not None:
            prev_end = (prev.script.end_state if prev.script and prev.script.end_state.strip() else prev.continuity.end_state).strip()
        if c.join == "continues" and prev_end:
            lines.append(f"- START STATE (the previous clip ends like this; use it word for word): {prev_end}")
        elif c.start_state:
            lines.append(f"- START STATE (use it word for word): {c.start_state}")
        if c.place:
            lines.append(f"- Place and time: {c.place}")
        if c.present:
            lines.append(f"- Who is in it: {', '.join(c.present)}")
        if c.carry_over:
            lines.append(f"- Must stay exactly as before: {c.carry_over}")
        if c.end_state:
            lines.append(f"- END STATE (use it word for word; the next clip starts from it): {c.end_state}")
        return "\n".join(lines) or "(none planned: decide them yourself)"

    @staticmethod
    def so_far(project: Project, node: Node) -> str:
        """What the clips before this one established, in a line each (the last eight)."""
        nums = numbering(project)
        out: list[str] = []
        for n, _ in walk(project.root):
            if n.id == node.id:
                break
            if n.is_leaf:
                end = (n.script.end_state if n.script and n.script.end_state.strip() else n.continuity.end_state).strip() or n.goal
                out.append(f"{nums.get(n.id, '')} {n.title}: ends with {end}")
        return "\n".join(out[-8:]) or "(this is the first clip)"

    async def draft_project(self, project: Project) -> ProjectDraft:
        length_block, length_rules = self.length_blocks(project)
        prompt = render("draft", goal=project.goal, length_block=length_block, length_rules=length_rules,
                        language_block=self.language_block(project), routes=routes_mod.describe(self.reg),
                        aspect=project.settings.aspect, context=summarize_for_llm(effective_context(project, project.root.id)))
        return await self.ask("draft", prompt, ProjectDraft,
                              {"goal": project.goal, "seconds": project.settings.target_seconds,
                               "auto_length": project.settings.length_mode == "auto",
                               "language": project.settings.language,
                               "context": [c.model_dump() for c in project.context]})

    async def decompose(self, project: Project, node: Node) -> Decomposition:
        nums = numbering(project)
        before = _previous_leaf(project, node)
        prev_end = ((before.script.end_state if before and before.script and before.script.end_state.strip() else before.continuity.end_state).strip()
                    if before else "") or "(there is no clip before this one)"
        prompt = render("decompose", outline=outline(project), number=nums.get(node.id, ""), title=node.title, routes=routes_mod.describe(self.reg),
                        prev_end=prev_end,
                        goal=node.goal, seconds=node.duration.likely_s or node.target_seconds or 20,
                        context=self._context_block(project, node.id), actors=self._actor_list(project, node.id))
        return await self.ask("decompose", prompt, Decomposition,
                              {"goal": node.goal, "title": node.title,
                               "seconds": node.duration.likely_s or node.target_seconds or 20})

    async def tighten(self, project: Project, scope_label: str, goal_text: str, clips: list[Node]) -> Tightening:
        """Ask the AI for shorter lines, or clips to drop or merge, for these clips (the tool checks every suggestion afterwards)."""
        from . import policy as policy_mod
        nums = numbering(project)
        order = [n for n, _ in walk(project.root) if n.is_leaf]
        lines = []
        for c in clips:
            nxt = order[order.index(c) + 1] if c in order and order.index(c) + 1 < len(order) else None
            join = (nxt.continuity.join or "cut") if nxt and nxt.continuity else "cut"
            s = c.script
            said = [f"    {'EXACT ' if d.fixed else ''}[{d.speaker}] {d.text}" for d in s.dialogue if d.text.strip()]
            if s.narration.strip():
                said.append(f"    {'EXACT ' if s.narration_fixed else ''}[narration] {s.narration}")
            lines.append(f"- clip {nums.get(c.id, '')} · {c.title or c.goal[:40]} · {c.duration.likely_s:.0f} s · join with the next clip: {join}\n" + ("\n".join(said) or "    (nothing is said)"))
        pol = policy_mod.current()
        prompt = render("optimize", outline=outline(project), scope=scope_label, goal=goal_text, clips="\n".join(lines) or "(none)", max_cut=f"{pol.max_cut_ratio:.0%}")
        meta_clips = [{"number": nums.get(c.id, ""), "dialogue": [{"text": d.text, "fixed": d.fixed} for d in c.script.dialogue if d.text.strip()],
                       "narration": c.script.narration, "narration_fixed": c.script.narration_fixed} for c in clips]
        return await self.ask("optimize", prompt, Tightening, {"clips": meta_clips, "goal": goal_text})

    async def split_clip(self, project: Project, node: Node) -> ClipSplit:
        """Split one clip into consecutive clips that each need only what ONE route can do (the rule comes from the catalogue)."""
        nums = numbering(project)
        sc = node.script
        secs = node.target_seconds or (sc.target_seconds if sc else None) or node.duration.likely_s or 6
        prompt = render("split_clip", outline=outline(project), number=nums.get(node.id, ""), title=node.title, goal=node.goal,
                        seconds=f"{secs:g}", routes=routes_mod.describe(self.reg), actors=self._actor_list(project, node.id),
                        script=sc.model_dump_json(indent=1) if sc else "(none)", shot_types=", ".join(SHOT_TYPES))
        return await self.ask("split_clip", prompt, ClipSplit, {"title": node.title, "goal": node.goal, "seconds": secs,
                                                                  "script": sc.model_dump() if sc else {}})

    async def write_clip_script(self, project: Project, node: Node, feedback: str = "") -> ClipScriptDraft:
        nums = numbering(project)
        prev = _previous_leaf(project, node)
        parents = " > ".join(f"{a.title}: {a.goal}" for a in ancestors(project, node.id) if a.id != project.root.id)
        current = node.script.model_dump_json(indent=1) if node.script else "(none yet)"
        secs = node.target_seconds or (node.script.target_seconds if node.script else None) or node.duration.likely_s or 6
        prompt = render("clip_script", outline=outline(project), number=nums.get(node.id, ""), title=node.title, routes=routes_mod.describe(self.reg),
                        goal=node.goal, parents=parents or "(top level)", seconds=f"{secs:g}", max_beats=max(1, round(secs / 2.5)),
                        context=self._context_block(project, node.id), actors=self._actor_list(project, node.id),
                        previous=(f"{prev.title}: {prev.script.visual if prev.script else prev.goal}"
                                  + (f" | IT ENDS: {prev.script.end_state}" if prev and prev.script and prev.script.end_state else "")
                                  if prev else "(first clip)"),
                        current=current, feedback=feedback or "(none)", shot_types=", ".join(SHOT_TYPES),
                        style=json.dumps(_style(project, node)), language_line=self.language_line(project),
                        so_far=self.so_far(project, node), contract=self.contract(project, node))
        return await self.ask("write_clip_script", prompt, ClipScriptDraft,
                              {"goal": node.goal, "title": node.title, "seconds": secs,
                               "actors": [a.model_dump() for a in project.context if a.type == ContextType.actor],
                               "feedback": feedback, "current": node.script.model_dump() if node.script else None,
                               "has_previous": prev is not None,
                               "previous_end_state": (prev.script.end_state if prev and prev.script else "")})

    async def revise_goal(self, project: Project, node: Node, instruction: str) -> GoalRevision:
        prompt = render("revise_goal", outline=outline(project), title=node.title, goal=node.goal,
                        seconds=node.duration.likely_s, instruction=instruction)
        return await self.ask("revise", prompt, GoalRevision,
                              {"title": node.title, "goal": node.goal, "instruction": instruction,
                               "seconds": node.target_seconds or node.duration.likely_s})

    async def suggest_dependencies(self, project: Project) -> DepList:
        lines = []
        nums = numbering(project)
        for n, _ in walk(project.root):
            if n.is_leaf:
                vis = n.script.visual if n.script else n.goal
                lines.append(f"{nums[n.id]} {n.title}: {vis}")
        prompt = render("dependencies", outline=outline(project), clips="\n".join(lines))
        return await self.ask("suggest_dependencies", prompt, DepList,
                              {"clips": [{"number": nums[n.id], "title": n.title,
                                          "visual": (n.script.visual if n.script else n.goal)}
                                         for n, _ in walk(project.root) if n.is_leaf]})

    async def photo_query(self, title: str, description: str) -> PhotoQuery:
        prompt = render("photo_query", title=title, description=description or title)
        return await self.ask("photo_query", prompt, PhotoQuery, {"title": title, "description": description})

    async def pick_photo(self, project: Project, description: str, titles: list[str], images: list[Path]) -> PhotoChoice:
        prompt = render("pick_photo", description=description, style=json.dumps({k: v for k, v in project.style.model_dump().items() if v}),
                        candidates="\n".join(f"{i}: {t}" for i, t in enumerate(titles, start=1)))
        return await self.ask("pick_photo", prompt, PhotoChoice, {"titles": titles}, images=images)

    async def explain(self, question: str, facts: str) -> Explained:
        prompt = render("explain", question=question, facts=facts)
        return await self.ask("explain", prompt, Explained, {"question": question, "facts": facts})

    async def command(self, project: Project, instruction: str, focus: Optional[Node] = None) -> CommandPlan:
        nums = numbering(project)
        prompt = render("command", outline=outline(project), actors=self._actor_list(project),
                        instruction=instruction, focus=(f"{nums.get(focus.id, '')} {focus.title}" if focus else "(whole project)"))
        return await self.ask("command", prompt, CommandPlan, {"instruction": instruction,
                                                                "focus": nums.get(focus.id, "") if focus else "",
                                                                "numbers": {v: k for k, v in nums.items()}})

    async def review_take(self, project: Project, node: Node, frames: list[tuple[float, Path]],
                          transcript: str, measurements: dict, take_seconds: float,
                          video: Optional[Path] = None, history: str = "", pair_times: Optional[list[float]] = None) -> ReviewDraft:
        nums = numbering(project)
        script = node.script.model_dump_json(indent=1) if node.script else "{}"
        prompt = render("review", number=nums.get(node.id, ""), title=node.title, goal=node.goal,
                        parents=" > ".join(a.goal for a in ancestors(project, node.id) if a.id != project.root.id),
                        script=script, context=self._context_block(project, node.id),
                        transcript=transcript or "(no speech detected)", measurements=json.dumps(measurements),
                        target=node.duration.likely_s, actual=take_seconds,
                        frame_times=_frame_description(frames, pair_times or []), history=history or "(first review)")
        return await self.ask("review", prompt, ReviewDraft,
                              {"script": node.script.model_dump() if node.script else {}, "transcript": transcript,
                               "measurements": measurements, "target": node.duration.likely_s,
                               "actual": take_seconds},
                              images=[p for _, p in frames], video=video)

    async def review_node(self, project: Project, node: Node, summaries: str, actual_seconds: float,
                          frames: list[tuple[float, Path]], boundaries: str = "", boundary_images: Optional[list[Path]] = None) -> ReviewDraft:
        prompt = render("node_review", title=node.title or "Whole video", goal=node.goal or project.goal,
                        summaries=summaries, target=node.target_seconds or node.duration.likely_s,
                        actual=actual_seconds, context=self._context_block(project, node.id),
                        boundaries=boundaries or "(none: these clips are separate scenes)")
        return await self.ask("review", prompt, ReviewDraft,
                              {"node_review": True, "target": node.target_seconds or node.duration.likely_s,
                               "actual": actual_seconds, "summaries": summaries, "boundaries": boundaries},
                              images=[p for _, p in frames] + list(boundary_images or []))


def _frame_description(frames: list[tuple[float, Path]], pair_times: list[float]) -> str:
    singles = frames[: len(frames) - len(pair_times)] if pair_times else frames
    pairs = frames[len(frames) - len(pair_times):] if pair_times else []
    text = "single frames at " + ", ".join(f"{t:.1f}s" for t, _ in singles)
    if pairs:
        text += ("; then ADJACENT PAIRS (images come two by two, 0.25 s apart; compare the two images of each pair with each other) at "
                 + ", ".join(f"{pairs[i][0]:.1f}s→{pairs[i + 1][0]:.1f}s" for i in range(0, len(pairs) - 1, 2)))
    return text


# =========================================================== conversions
def _style(project: Project, node: Node) -> dict:
    from .tree import effective_style
    return effective_style(project, node.id)


def _previous_leaf(project: Project, node: Node) -> Optional[Node]:
    prev = None
    for n, _ in walk(project.root):
        if n.id == node.id:
            return prev
        if n.is_leaf:
            prev = n
    return None


def draft_to_script(project: Project, d: ClipScriptDraft) -> ClipScript:
    by_name = {}
    for c in project.context:
        if c.type == ContextType.actor:
            by_name[c.title.lower()] = c.id
            by_name[c.id] = c.id

    def resolve(name: str) -> str:
        if not name:
            return "narrator"
        key = name.lower().strip()
        if key in ("narrator", "voice over", "voiceover", "vo"):
            return "narrator"
        if key in by_name:
            return by_name[key]
        for n, cid in by_name.items():
            if key and (key in n or n in key):
                return cid
        return name

    shot = d.shot_type if d.shot_type in SHOT_TYPES else "other"
    return ClipScript(
        shot_type=ShotType(shot), visual=d.visual, action_beats=d.action_beats, camera=d.camera,
        actors_in_shot=[ActorInShot(actor_id=resolve(a.actor_name), clothing=a.clothing, behaviour=a.behaviour)
                        for a in d.actors_in_shot],
        dialogue=[DialogueLine(speaker=resolve(l.speaker_name), text=l.text, emotion=l.emotion, fixed=l.fixed) for l in d.dialogue],
        narration=d.narration, narration_fixed=d.narration_fixed and bool(d.narration.strip()),
        on_camera_speech=d.on_camera_speech and bool(d.dialogue),
        sound_notes=d.sound_notes, motion=d.motion if d.motion in ("face", "body", "scene") else "",
        start_state=d.start_state, end_state=d.end_state, negative=d.negative)


def preserve_fixed(old: Optional[ClipScript], new: ClipScript) -> list[str]:
    """A rewritten script must still hold every line that was marked "say exactly this". Lines marked fixed in the old script that are
    missing (or reworded) in the new one are put back at the same place; matching lines are marked fixed. Returns what was restored."""
    restored: list[str] = []
    if not old:
        return restored
    for i, line in enumerate(old.dialogue):
        if not line.fixed or not line.text.strip():
            continue
        match = next((x for x in new.dialogue if x.text.strip() == line.text.strip()), None)
        if match:
            match.fixed = True
        else:
            new.dialogue.insert(min(i, len(new.dialogue)), line.model_copy())
            restored.append(line.text)
    if old.narration_fixed and old.narration.strip():
        if new.narration.strip() != old.narration.strip():
            new.narration = old.narration
            restored.append(old.narration)
        new.narration_fixed = True
    return restored
