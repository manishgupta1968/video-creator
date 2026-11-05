"""`vg smoke-test`: a tiny REAL test of every vendor the tool depends on, for about a dollar or less.

It runs on your own computer with your own keys (nothing is sent to anyone else) and prints one short report
you can paste when something fails. It uses the same engine code as a real run, so what passes here passes there.

Steps (each one is independent: a failure is reported and the next step still runs):
  1 keys       free   asks OpenAI / ElevenLabs / fal.ai whether the keys work
  2 voice      cents  one short sentence
  3 picture    cents  one picture of a lion
  4 video      <$1    a few seconds of video from that picture (the model your quality mode would pick)
  5 talking    <$1    the lion says the sentence (Kling Avatar)
  6 join       free   the video and the talking clip are joined into smoke-test.mp4
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import doctor, media
from .plugins.base import AvatarRequest, ImageRequest, VideoRequest, VoiceSpec

SENTENCE = "Hello, how are you?"
PICTURE_PROMPT = ("Photoreal portrait of an adult male African lion with a full golden mane, facing the camera, mouth closed, "
                  "golden hour light, shallow depth of field, sharp eyes.")
VIDEO_PROMPT = "The lion slowly turns its head toward the camera and blinks. Natural motion, golden hour light."
AVATAR_PROMPT = "A talking lion: natural mouth movement in sync with the speech, subtle head movement, looking at the camera."
VOICE_WORDS = "deep, warm, slow male voice"
AUDIO_SECONDS_GUESS = 2.0


@dataclass
class Result:
    step: str
    status: str                  # ok | warn (worked, but only after another model took over) | bad | skip
    model: str = ""
    detail: str = ""
    cost: float = 0.0
    seconds: float = 0.0


@dataclass
class Planned:
    step: str
    model: str
    est: float
    what: str


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)
    spent: float = 0.0
    limit: float = 1.0
    output: Optional[Path] = None

    def text(self) -> str:
        mark = {"ok": "✓", "warn": "!", "bad": "✗", "skip": "-"}
        lines = ["Smoke test report"]
        for r in self.results:
            extra = " · ".join(x for x in (r.model, f"{r.seconds:.0f} s" if r.seconds else "", f"${r.cost:.3f}" if r.cost else "") if x)
            lines.append(f"{mark[r.status]} {r.step}" + (f" ({extra})" if extra else "") + (f": {r.detail}" if r.detail else ""))
        lines.append(f"Spent about ${self.spent:.2f} of your ${self.limit:.2f} limit.")
        if self.output:
            lines.append(f"Test video saved as {self.output}")
        bad = [r for r in self.results if r.status == "bad"]
        warn = [r for r in self.results if r.status == "warn"]
        tested = [r for r in self.results if r.status in ("ok", "warn") and r.step != "Keys"]
        if not tested and not bad:
            lines.append("Nothing was tested: no key could be used yet. Save your keys in the GUI (Settings), then run this again.")
        elif bad:
            lines.append(f"{len(bad)} step(s) failed. Please send this whole report.")
        elif warn:
            lines.append(f"Everything worked, but {len(warn)} step(s) needed another model to take over. "
                         "Please send this report so the first model's name can be corrected.")
        else:
            lines.append("All steps worked. A real project should work too.")
        return "\n".join(lines)


def plan_steps(reg, mode: str, all_video: bool = False) -> list[Planned]:
    """What would be run, with the estimated cost of each paid step (from the catalogue prices; no network)."""
    out: list[Planned] = []

    def pick(job, *a, **k):
        try:
            e = reg.choose(job, *a, mode=mode, **k)
        except LookupError:
            return None
        return None if e.is_free else e
    v = pick("voice")
    if v:
        out.append(Planned("Voice", v.id, len(SENTENCE) / 1000 * v.unit_price, f"say “{SENTENCE}”"))
    i = pick("image")
    if i:
        out.append(Planned("Picture", i.id, i.unit_price, "one picture of a lion"))
    vids = reg.candidates("video", "wildlife", {"start_frame": True}, mode)
    vids = [e for e in vids if not e.is_free][: (3 if all_video else 1)]
    for e in vids:
        secs = e.billed_seconds(float((e.params.get("durations") or [4])[0]))
        out.append(Planned("Video" if len(vids) == 1 else f"Video {e.id}", e.id, secs * e.unit_price, f"{secs:.0f} s of video from the picture"))
    a = pick("avatar", need={"non_human": True})
    if a:
        out.append(Planned("Talking lion", a.id, AUDIO_SECONDS_GUESS * a.unit_price, f"about {AUDIO_SECONDS_GUESS:.0f} s of speech"))
    return out


async def run(svc, max_usd: float = 1.0, ask: Optional[Callable[[str], bool]] = None, say: Callable[[str], None] = print,
              workdir: Optional[Path] = None, all_video: bool = False) -> Report:
    """Run the test. `ask(question)` must return True before anything is spent (None = already agreed)."""
    from .runner import Engine
    reg = svc.reg
    mode = svc.config.quality_mode
    workdir = Path(workdir or Path.cwd())
    rep = Report(limit=max_usd)
    steps = plan_steps(reg, mode, all_video)
    total = sum(s.est for s in steps)
    if steps:
        say("This test makes real, paid calls with your own keys:")
        for s in steps:
            say(f"  • {s.step} ({s.model}): {s.what}: about ${s.est:.3f}")
        say(f"  Estimated total about ${total:.2f}; the limit is ${max_usd:.2f}.")
    else:
        say("No paid model is usable yet (no key found), so there is nothing to spend. Only the free key check will run.")
    if steps and ask is not None and not ask(f"Spend up to about ${total:.2f}?"):
        rep.results.append(Result("Cancelled", "skip", detail="nothing was spent"))
        return rep

    p = svc.new_project("Smoke test (deleted afterwards)", seconds=10)
    pid = p.id
    eng = Engine(svc)
    tmp = Path(tempfile.mkdtemp(prefix="vg-smoke-"))
    from .project import ProjectStore

    def spent() -> float:
        return round(sum(float(r.get("actual_usd", 0)) for r in ProjectStore.ledger(pid)), 4)

    def room(step: str, est: float) -> Optional[Result]:
        if spent() + est > max_usd + 1e-9:
            return Result(step, "skip", detail=f"skipped: it would pass your ${max_usd:.2f} limit (spent ${spent():.2f}, this needs about ${est:.2f})")
        return None

    def done(step: str, entry, t_before: float, secs: float = 0.0, detail: str = "") -> Result:
        # if the first model failed and another one took over, say so: that is something to fix
        kind = {"Voice": "voice", "Picture": "image", "Talking lion": "avatar"}.get(step, "video")
        first_failures = [f for r in ProjectStore.ledger(pid) if r.get("kind") == kind for f in r.get("failed_first", [])]
        if first_failures:
            return Result(step, "warn", entry.id, "the first choice failed and this model took over. " + first_failures[-1][:240],
                          round(spent() - t_before, 4), secs)
        return Result(step, "ok", entry.id, detail, round(spent() - t_before, 4), secs)

    def fail(step: str, exc: Exception, model: str = "") -> Result:
        return Result(step, "bad", model, " ".join(str(exc).split())[:300] or type(exc).__name__)

    try:
        # 1 keys (free)
        checks = await doctor.run_checks(catalog=svc.catalog)
        bad_keys = [c for c in checks if c.status == doctor.BAD]
        if all(c.status == doctor.SKIP for c in checks):
            rep.results.append(Result("Keys", "skip", detail="no keys found"))
        else:
            rep.results.append(Result("Keys", "bad" if bad_keys else "ok",
                                      detail="; ".join(f"{c.name}: {c.message}" for c in bad_keys) or "accepted by the vendors that were checked"))
        for c in checks:
            if c.status == doctor.WARN:
                rep.results.append(Result(c.name, "skip", detail=c.message[:200]))

        # 2 voice
        voice_wav: Optional[Path] = None
        planned = {s.step: s for s in steps}
        if "Voice" in planned:
            st = planned["Voice"]
            if (r := room("Voice", st.est)):
                rep.results.append(r)
            else:
                before = spent()
                entry = reg.catalog.get(st.model)
                try:
                    out = tmp / "voice.wav"

                    async def call_voice(e):
                        plugin = reg.plugin(e.plugin)
                        vid = await plugin.match(VOICE_WORDS)
                        _, u = await plugin.synthesize(SENTENCE, VoiceSpec(voice_id=vid, description=VOICE_WORDS), out, e.model)
                        return u
                    entry, _ = await eng._with_fallback(pid, entry, reg.candidates("voice", mode=mode), call_voice, "voice", "smoke voice",
                                                        cost_of=lambda e: len(SENTENCE) / 1000 * e.unit_price,
                                                        expected_of=lambda e: 5, any_error=True)
                    voice_wav = out
                    rep.results.append(done("Voice", entry, before, media.probe_duration(out)))
                except Exception as exc:
                    rep.results.append(fail("Voice", exc, entry.id))
        else:
            rep.results.append(Result("Voice", "skip", detail="no paid voice model is usable (add ELEVENLABS_API_KEY)"))

        # 3 picture
        photo: Optional[Path] = None
        if "Picture" in planned:
            st = planned["Picture"]
            if (r := room("Picture", st.est)):
                rep.results.append(r)
            else:
                before = spent()
                try:
                    out = tmp / "lion.png"
                    entry, _ = await eng._make_image(pid, reg.catalog.get(st.model), lambda e: ImageRequest(
                        prompt=PICTURE_PROMPT, out=out, model=e.model, aspect="16:9", label="smoke test"), "smoke picture")
                    photo = out
                    rep.results.append(done("Picture", entry, before))
                except Exception as exc:
                    rep.results.append(fail("Picture", exc, st.model))
        else:
            rep.results.append(Result("Picture", "skip", detail="no paid picture model is usable (add OPENAI_API_KEY or FAL_KEY)"))
        start = photo
        if start is None:                                    # a failed picture step must not hide a video problem
            start = media.placeholder_image("Smoke test", tmp / "start.png", (1280, 720), label="start picture")

        # 4 video
        video_clip: Optional[Path] = None
        for st in [s for s in steps if s.step.startswith("Video")]:
            if (r := room(st.step, st.est)):
                rep.results.append(r)
                continue
            before = spent()
            entry = reg.catalog.get(st.model)
            secs = entry.billed_seconds(float((entry.params.get("durations") or [4])[0]))
            out = tmp / f"video_{entry.id}.mp4"
            try:
                used = await eng._video_parts(pid, entry, VideoRequest(
                    prompt=VIDEO_PROMPT, out=out, model=entry.model, seconds=secs, aspect="16:9", resolution="720p",
                    start_frame=start, audio=bool(entry.capabilities.get("native_audio")), params=dict(entry.params)),
                    "smoke", [e for e in reg.candidates("video", "wildlife", {"start_frame": True}, mode) if e.id != entry.id], None)
                video_clip = video_clip or out
                rep.results.append(done(st.step, used, before, media.probe_duration(out)))
            except Exception as exc:
                rep.results.append(fail(st.step, exc, entry.id))
        if not [s for s in steps if s.step.startswith("Video")]:
            rep.results.append(Result("Video", "skip", detail="no paid video model is usable (add FAL_KEY)"))

        # 5 talking lion
        talking: Optional[Path] = None
        if "Talking lion" in planned:
            st = planned["Talking lion"]
            secs = media.probe_duration(voice_wav) if voice_wav else AUDIO_SECONDS_GUESS
            if photo is None or voice_wav is None:
                rep.results.append(Result("Talking lion", "skip", detail="needs the picture and the voice from the steps above"))
            elif (r := room("Talking lion", secs * reg.catalog.get(st.model).unit_price)):
                rep.results.append(r)
            else:
                before = spent()
                out = tmp / "talking.mp4"
                try:
                    async def call_avatar(e):
                        _, u = await reg.plugin(e.plugin).generate(AvatarRequest(photo=photo, audio=voice_wav, out=out, model=e.model,
                                                                                 prompt=AVATAR_PROMPT, aspect="16:9", label="smoke test"))
                        return u
                    entry, _ = await eng._with_fallback(
                        pid, reg.catalog.get(st.model), reg.candidates("avatar", mode=mode, need={"non_human": True}), call_avatar,
                        "avatar", "smoke talking lion", cost_of=lambda e: secs * e.unit_price, expected_of=lambda e: 60 + 8 * secs)
                    talking = out
                    rep.results.append(done("Talking lion", entry, before, media.probe_duration(out)))
                except Exception as exc:
                    rep.results.append(fail("Talking lion", exc, st.model))
        else:
            rep.results.append(Result("Talking lion", "skip", detail="no talking-animation model is usable (add FAL_KEY)"))

        # 6 join (free)
        parts = [c for c in (video_clip, talking) if c]
        if parts:
            try:
                fitted = []
                for i, c in enumerate(parts):
                    f = tmp / f"fit_{i}.mp4"
                    media.normalize_clip(c, f, (1280, 720), 24, keep_audio=media.has_audio(c))
                    fitted.append(f)
                final = workdir / "smoke-test.mp4"
                media.join_clips(fitted, ["cut"] * len(fitted), final, (1280, 720), 24)
                rep.output = final
                rep.results.append(Result("Join", "ok", detail=f"{len(parts)} clip(s) joined into {final.name}"))
            except Exception as exc:
                rep.results.append(fail("Join", exc))
        else:
            rep.results.append(Result("Join", "skip", detail="no clip was made"))
        rep.spent = spent()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            ProjectStore.delete(pid)
        except Exception:
            pass
    try:
        (workdir / "smoke-test-report.txt").write_text(rep.text() + "\n")
    except OSError:
        pass
    return rep
