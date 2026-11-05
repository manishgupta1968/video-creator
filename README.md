# video-generator

Turn a goal into a finished video (`.mp4` or `.mov`).

You describe what you want. The tool:
1. makes a complete draft plan, with parts, clips, scripts, actors, and the length, cost and time of each;
2. lets you edit everything (or ask the AI to change it in plain words);
3. calls the best AI tools you have connected to make the clips, voices and music;
4. lets you watch the takes, read the Review Agent's suggestions and pick the best take;
5. joins everything into one video.

Example goals:
- "A 2-minute video that shows a lion being chased by a deer with long horns"
- "A 30-second advert for our travel bag, presented by me"

You stay in control at every step. **Nothing is paid for until you see the cost and press Generate.**

---

## 1. Install on your laptop

You need three things:

| What | Why | How to get it |
|---|---|---|
| Python 3.10 or newer | runs the tool | https://www.python.org/downloads/ |
| ffmpeg | cuts, joins and mixes video | macOS: `brew install ffmpeg` · Windows: `winget install ffmpeg` · Linux: `sudo apt install ffmpeg` |
| This folder | the tool itself | `git clone` this repository |

Optional:
- LibreOffice, only if you want to use PowerPoint/Keynote files directly. (A PDF of your slides works without it.)
- Node.js, only if you want to change the GUI code.

Then, inside this folder:

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

On Windows, use this instead of `source`:

```bash
.venv\Scripts\activate
```

```bash
pip install -e .
```

## 2. Start it

```bash
vg gui
```

Your browser opens at http://127.0.0.1:8765.

**It works straight away, for free, with no accounts.** Without any keys, it uses:
- a simple offline "brain";
- storyboard-card previews with gentle motion;
- your computer's own voice.

This is useful for trying the whole flow: goal → plan → clips → final video.

## 3. Connect the AI services you want (pay-as-you-go)

Open **Settings → Vendors & keys** in the app. Each vendor has a *Sign up / billing* link and a *Prices* link. Paste the key and press **Save**. Keys are stored only on your computer, in `~/.video-generator/.env`.

**Recommended starter set (3–4 accounts):**

| Vendor | What it does here | Sign up |
|---|---|---|
| Anthropic **or** OpenAI | the AI brain: plans, scripts, reviews | https://console.anthropic.com · https://platform.openai.com |
| fal.ai | one key for many video models (Kling, Seedance, Wan), images (Flux), avatars (VEED Fabric, Kling Avatar), lip-sync, music | https://fal.ai/dashboard |
| ElevenLabs | voices, cloning your voice, music | https://elevenlabs.io/app |
| Google Gemini API (optional) | Veo 3.1 (people speaking in scenes), Nano Banana images | https://aistudio.google.com |

Add these only if you need them:
- HeyGen, for a digital twin of yourself;
- Runway, Luma, Kling (direct), Cartesia, Replicate.

`vg vendors` prints the full list with links.

> Prices and model names change often. The tool keeps them in an editable **model catalogue** (Settings → Model catalogue). Each price has the date it was last checked. Check a vendor's pricing page before a big project.

## 4. How you use it (GUI)

1. **Type your goal** on the start page and press Enter. You may drop photos, slides, clips or a voice recording on the box.
   - If the goal says "30-second" or "2 minute", the length is set for you.
2. **Edit the draft.** The workspace has five areas:
   - **Left – Story:** the goal tree. Parts contain sub-parts, which contain clips. Drag to reorder. Use ••• → *Break down with AI*.
   - **Middle – Editor:** click any text to change it; it saves by itself. Or type in *Ask AI*, e.g. "make Rahul look more frustrated".
   - **Right – Context:** photos, voices, logos, sounds and notes. They can be **shared by all clips**, belong to **one part and everything below it**, or belong to **this clip only**. Inherited items can be switched off for one clip.
   - **Right – Cost & time:** the full breakdown, plus *What if…* options (change the model, takes or resolution and see the new cost at once).
   - **Bottom:** the timeline and run buttons.
3. **Actors** can be:
   - only a text description (age, look, clothing, behaviour, voice description); or
   - face photos and/or a voice recording.

   For real people, you confirm consent once: "This is me" or "I have permission".
4. **Links between clips.** The tool finds them and handles them for you.
   - Example: "clip 2.2 *continues from* 2.1" means 2.2 starts on 2.1's last frame.
   - See them under *Links*, or in the graph (branch icon at the top).
5. **Generate.** Every button first shows **cost, time and budget**.
   - **Generate entire video**: makes all clips, then stitches the video.
   - **Generate next**: makes one clip at a time.
   - **Continue to end**: after some one-by-one clips, finishes the rest.
   - **Pause / Resume / Stop** at any time. Finished clips are kept.
6. **Pick takes and use the Review Agent.**
   - Shots with people get 2–3 takes. You pick one (or switch on *Auto-pick*).
   - The Review Agent scores each take: goal, script, actors, realism, timing, lip-sync. It suggests fixes, but **only suggests**.
   - Tick the suggestions you like, add your own feedback (yours wins), and press **Re-make with feedback**. You see the before/after script and the new cost before anything runs.
   - Older versions are kept under *Versions*.
7. **Download** the final video (top right). Subtitles (`final.srt`) are made too.

Keyboard shortcuts:
- **Ctrl/⌘ K**: ask AI for any change
- **Ctrl/⌘ Z**: undo
- **Ctrl/⌘ Shift Z**: redo

### Things worth knowing

**Preview mode.** Without keys for a video or image service, the tool cannot make real footage. It makes *text-card previews* instead (each card says "PREVIEW — not real footage"). A banner at the top, a "preview" mark on each clip, and the Generate box all tell you this and what to add.

**A talking animal or object** (for example a lion that says "hello how are you"). The tool does it in three steps:
1. a picture of the lion: made by an image model (GPT Image, Nano Banana, Flux), or a real photo you choose;
2. the voice: spoken by a voice service (ElevenLabs, Cartesia), from your description such as "deep, growly";
3. the animation: a talking-animation model (Kling Avatar through fal.ai) moves the mouth to the voice.

With the fal.ai key (and ElevenLabs for the voice) this works. A presenter who is a person uses the same steps with HeyGen or VEED as an alternative.

**Real photos, found for you.** For an animal, an object or a place, you can add your own photo. If you add none, the tool **searches for a real photo by itself** (Wikimedia Commons needs no key; Pexels is optional) when the plan is drafted, so you see the picture before any money is spent. It uses a free search; if your AI brain can see pictures, it also looks at the best few and picks the one that fits. It never replaces a photo you supplied. It never searches for people or for your own product or brand (those must be supplied). You see what it found, who took it and the licence, with buttons *Choose another photo* and *Remove it*. If you remove it, it will not search again for that item. Credits are saved in `output/credits.txt`. If nothing suitable is found, a picture is made with an AI image model, or a preview card if none is connected.

**Record your voice in the tool.** On an actor press *Record my voice* (or *My voice* in the Context tab). Read the shown text for 30 seconds to 2 minutes. The recording is used **only to copy your voice**. It is not placed in the video: every line of the script is spoken fresh in the copied voice. Copying a voice needs ElevenLabs or Cartesia; without one, the tool warns you and uses a stock voice. If Safari blocks the microphone: Safari → Settings → Websites → Microphone.

**How the Review Agent judges quality.** It judges every take as *video*, to cinema quality, not only against your goal. It scores: goal, script, actors, behaviour, **realism** (skin, eyes, hands, fur, no AI artifacts), **motion** (real, natural movement, not a slideshow or zoom), **consistency** (same face, clothing, light and background across frames), **fidelity** (sharp, no blur or blocks), **audio** (natural, clear voice), continuity, timing and lip-sync. It looks at spread-out frames and at pairs of neighbouring frames, to catch warping and morphing. The tool also measures numbers itself, for free: how much moves, how sharp the clip is compared with its starting picture, loudness and silence. Some rules cannot be overruled by the AI: a free preview card, or a clip where almost nothing moves, can never pass as realistic animation. A score of 0 means "could not be checked" (for example the offline brain cannot see). The Review Agent only suggests; you decide.

**Where did the money go?** Click the *Budget* chip at the top. It shows your budget, what has been spent, what is still to spend, and every paid call grouped by type (AI brain, pictures, video, voices, music), with how each amount was counted. In the terminal: `vg budget`. The Budget is a safety limit; the default comes from Settings.

**Help is everywhere.** Hover any button, or tab to it, to see *what it does* and *what you get*. Press **?** (or the Help button) for step-by-step guides; each step has a **Show me** button that points at the real control. You can also ask questions in plain words (Ctrl/⌘ K, or Help): "Why does this clip cost so much?" The answer comes from your project's own numbers. In the terminal: `vg explain "why is the budget $0.23?"`.

**Is it working?** While anything runs you see a bar under the top menu: what is happening now ("Making clip 2.1 · Making video, take 2 of 3"), the time so far, how many clips are done, and Pause/Stop. The browser tab title shows ⏳ while working, 👆 when it needs your pick and ✅ when finished. The browser can also send a notification (it asks once).

**The final video.** When you use *Generate entire video* or *Continue to end*, the clips are joined automatically at the end. If you make clips one by one, use *Join clips into final video* (same size and speed, transitions, music, subtitles). If you change something afterwards, the final video is marked out of date and the button becomes *Update final video*.

## 5. Command line (same features)

Each command below is shown on its own line so you can copy it.

```bash
vg new "A 30-second advert for our travel bag, presented by me" --length 30 --add slides.pdf --add me.wav
```

```bash
vg show
```

The goal tree with length, cost and status.

```bash
vg tree decompose 2
```

Break part 2 into clips with AI.

```bash
vg revise 1.2 "make Rahul look more frustrated"
```

```bash
vg actor add Priya --photo priya1.jpg --photo priya2.jpg --voice priya.wav --clothing "blue kurta" --behaviour "calm, warm smile"
```

```bash
vg actor consent <actor-id> permission
```

```bash
vg context add logo.png --role must_appear
```

```bash
vg context add --text "Always mention it weighs 400 g" --scope project
```

```bash
vg deps add 2.1 2.2 --type continues_from
```

```bash
vg estimate 2.2
```

Cost and time before making anything.

```bash
vg render --next
```

```bash
vg render --continue
```

```bash
vg render --all
```

```bash
vg takes 2.2
```

The takes, plus the Review Agent's findings.

```bash
vg pick 2.2 2
```

```bash
vg remake 2.2 --feedback "slow motion when the strap breaks"
```

```bash
vg compare 2.2 --models veo_3_1,kling_3
```

```bash
vg cost
```

Estimated vs actual cost per clip.

```bash
vg config set llm.default openai
```

Switch the AI brain to OpenAI.

```bash
vg plugins
```

```bash
vg catalog --check
```

```bash
vg vendors
```

## 6. Adding a new AI tool later

Every tool is a plug-in. A new tool is:
1. a small Python package with one class;
2. one entry-point line in its `pyproject.toml`;
3. one row in the model catalogue.

No change to the core is needed. See [docs/writing-a-plugin.md](docs/writing-a-plugin.md) and the working example in `examples/vg-plugin-example`.

## 7. Where things are stored

```
~/.video-generator/
  config.yaml      your settings (AI brain, budget, quality)
  .env             your API keys (owner-only permissions)
  catalog.yaml     your edits to the model catalogue
  timings.json     real job times, used to improve time estimates
  projects/<id>/   project.json, history (undo), inputs, clips, output/final.mp4, ledger.jsonl (spending log)
```

## 8. Honest notes

- The free, offline mode makes **previews** (storyboard cards with motion and a robotic voice). Real footage needs a video vendor key.
- The cloud plug-ins follow each vendor's public API documentation. They were not run against live accounts while this was built (no keys were available). If a vendor changes an endpoint or model name, the fix is usually one row in the catalogue or one small plug-in file. Use **Settings → Test connection** after adding a key.
- Better local voices and checks are optional installs:
  - `pip install -e ".[local-voice]"`: Kokoro voices;
  - `pip install -e ".[transcribe]"`: Whisper, so the Review Agent hears the speech;
  - `pip install -e ".[face]"`: face-match scores.

## 9. Development

```bash
pip install -e ".[dev]"
```

```bash
pytest
```

The GUI is React + TypeScript (Vite, Tailwind, Radix, React Flow) in `frontend/`. Its build is committed in `video_generator/web/static`, so users do not need Node.

```bash
npm --prefix frontend install
```

```bash
npm --prefix frontend run dev
```

That runs the GUI with live reload on :5173. It talks to `vg gui` on :8765.

```bash
npm --prefix frontend run build
```

The design and the research behind the tool choices are in [docs/DESIGN.md](docs/DESIGN.md).
