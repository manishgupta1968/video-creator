# Plan: video-generator

## Context
The user wants **video-generator**, a tool that turns a goal into a finished video file (`.mp4` / `.mov`). Two example goals:
- "a 2-minute video of a lion chased by a deer with long horns"
- "an advert for our product"

What the user asked for:
1. **A goal tree in a graphical interface (GUI).**
   - The overall goal is broken into sub-goals, and each sub-goal can be broken down again, to any depth.
   - Each bottom-level goal becomes **one video clip** with a detailed script.
   - The clips are made and then **stitched** together.
2. **Actors**, each defined by face photos *or* a purely written description. A profile can also include clothing, behaviour, a voice sample or a voice description, and so on.
3. **Links between clips (dependencies).**
   - If a clip needs something from an earlier clip, for example "start where the last clip ended", the tool handles it automatically.
   - The GUI shows these links clearly.
4. **Length estimates** for every clip and every sub-goal.
5. **Best-of-breed tools**, chosen from many sources, not one article. **Any new tool can be plugged in later.**
6. **People must look realistic.**
   - The user can appear as a **digital twin**.
   - For people shots, the tool makes **2–3 takes and the user picks one**.
7. The user can add **slides and their own video clips**.
8. The script is reviewed and revised, and **nothing costly runs until the user approves**.

Decisions the user made: Python; command line plus a local GUI.

Starting point: the repository `manishgupta1968/video-creator` (branch `claude/stoic-pasteur-76elrs`) is empty. The machine has ffmpeg, Python 3 and Node 22.

## Research findings (cross-checked, Nov 2026)
**Sources:**
- Independent blind-vote leaderboards: Artificial Analysis and Arena (formerly LMArena). The live sites are blocked from this session, so I used copies dated Sept–Nov 2026.
- The Hugging Face Open TTS Leaderboard.
- Research papers.
- Several hands-on tests by different testers.
- Official vendor documentation.

A vendor's claim was counted only when another source agreed.

1. **No model stays "the best", and sources disagree.**
   - The leaders named include Wan 3.0, Gemini Omni, Kling v3/4, Seedance 2.x and FLUX 3 Video, depending on the board and the month.
   - Design response: an editable **model catalogue**, plus a built-in **compare** feature.
2. **The best model depends on the type of shot.** These points agree across several testers:
   - **People moving or using their hands:** Kling 3.x/4 and Seedance 2.x. Veo 3.1 is weaker at physical motion; at least two tests found this.
   - **People speaking with lip movement in the same clip:** Veo 3.1 has the most consistent support. Seedance 2.x is the strongest challenger, especially for non-English languages.
   - **Presenter talking to camera / digital twin:** dedicated avatar tools look the most realistic. Examples: HeyGen Avatar IV, VEED Fabric, Kling Avatar, OmniHuman.
   - **Fixing lip movement afterwards:** Sync.so (lipsync-2-pro). The open-source alternative, LatentSync, needs about 18 GB of graphics-card memory.
3. **How people get realistic humans today.** All sources agree:
   1. Start from a photoreal still image.
   2. Turn it into motion with image-to-video.
   3. Reuse the same reference image in every shot.
   4. Keep shots short (drift starts after 5–10 seconds).
   5. Make several takes.
   6. Avoid heavy upscaling.
4. **Images.** The top group includes Nano Banana Pro/2, GPT Image 2.x and Flux 2. The order changes between snapshots.
5. **Voice.**
   - Eleven v4 and Cartesia Sonic 3.6 are at or near the top on several boards.
   - Cloning: ElevenLabs offers an instant clone, and its professional clone needs about 30 minutes of audio. Cartesia needs about 10 seconds for an instant clone.
   - Open models: Fish S2 Pro (licence must be checked), Voxtral, Chatterbox (MIT), Qwen3-TTS (Apache-2.0), Kokoro (no cloning, runs on CPU).
6. **Music.** ElevenLabs Music is trained on licensed music and allowed for commercial use. Suno has no official API.
7. **Facts about the platforms:**
   - The Sora API was shut down in September 2026.
   - Wan 3.0 is API-only. The newest open model is Wan 2.2 (Apache-2.0).
   - Gemini Omni has an API, but access to the preview is restricted.
   - fal.ai and Replicate give one key for many models.
8. **Continuity between clips.** Many video models accept a **start frame** and some accept an **end frame**. This is how one clip can begin exactly where the previous clip ended.

## Core concept 1: the goal tree
```
Project goal: "3-min launch video for our lightweight bag"
├── 1 Hook: "busy Mumbai morning, people struggle with heavy bags"     ~20 s
│   ├── 1.1 "crowded train platform, wide shot"                [clip] ~6 s
│   └── 1.2 "Rahul's shoulder strap snaps"                      [clip] ~7 s
├── 2 Introduce product: "Priya presents the bag"                       ~45 s
│   ├── 2.1 "Priya walks into frame holding the bag"            [clip] ~8 s
│   └── 2.2 "Priya explains three features to camera"           [clip] ~35 s
├── 3 Features (user slides features.pdf)                       [slides] ~60 s
├── 4 Testimonial (user clip review.mov)                          [user clip] 28 s
└── 5 Call to action, logo, music                               [clip] ~12 s
```
- **Nodes:**
  - A **goal node** has a goal text and children.
  - A **clip node** is a leaf, the bottom of a branch. It holds a detailed script for one clip: shot description, camera, actors, dialogue or narration, sound.
  - A leaf can also be a **slides** node or a **user clip** node.
- **Breaking down:** on any node, the user can:
  - click "Break down with AI": Claude proposes child sub-goals, which the user then edits
  - write the children by hand
  - mix both

  The tree can have any depth.
- **Turning a leaf into a clip:**
  - "Write detailed script" (by Claude) fills the clip script.
  - The user can edit any field.
  - "Revise with AI" takes plain instructions, for example "make Rahul look more frustrated".
- **What Claude sees:** Claude always works with the **parent goals, the neighbouring nodes and the actor list**, so each piece fits the whole story.
- **Inheritance:** style, actors, location and mood are set on a parent and **inherited** by its children, and any child can override them.
  - Example: node 1 sets "early morning, cool blue light". Clips 1.1 and 1.2 inherit it.
- **Long clips:** if a leaf is longer than any model can make in one go (about 8–15 seconds), the tool suggests splitting it.
  - The parts are linked automatically with "continue from previous" dependencies, so they play as one smooth clip.
  - Exception: a talking-to-camera clip that uses an avatar tool can run long.

## Core concept 1b: context, shared by all clips or specific to one clip
"Context" means any material that guides how the video is made. Every context item has a **type**, a **scope** (where it applies) and a **role** (how it is used).

**Context types** (each item can have files and/or text; a text-only item is always allowed)

| Type | Examples | Files accepted |
|---|---|---|
| Actor (see concept 2) | Priya, Rahul, a narrator | face photos, voice sample, video of the person |
| Object / prop | the bag, a coffee cup, a car | stills from several angles |
| Entity / brand | company logo, brand colours, product name, mascot | logo files, brand guide PDF |
| Location / set | "Mumbai train platform at dawn", the user's shop | stills, short video |
| Style / look | "warm cinematic, film grain", a reference frame from a film | stills, short clips |
| Audio | voice samples, sound effects (train horn), music reference ("like this track") | wav, mp3, m4a |
| Text notes / brief | target audience, tone, facts to say ("weighs 400 g"), words to avoid | text, docs, PDF |
| Media to include | slides, existing footage | pdf, pptx, mp4, mov |

**Scope: three levels, which follow the goal tree**
1. **Shared (project level):** applies to **all clips**. Examples: the brand logo, the style, the narrator voice, the "facts to say" brief.
2. **Node level:** applies to a goal node **and everything below it**. Example: "Mumbai platform" set on node 1 (Hook) applies to clips 1.1 and 1.2 only.
3. **Clip level:** applies to **one clip only**. Examples: a train-horn sound for clip 1.1, or a close-up photo of the broken strap for 1.2.

- **Lower levels can add, override or switch off.**
  - A clip can **add** its own items.
  - A clip can **override** a shared item. Example: a different outfit photo for Priya in clip 5.
  - A clip can **switch off** an inherited item. Example: hide the logo watermark in clip 4.
- **Effective context:** for any clip, the GUI shows the **effective context**, meaning everything that applies, marked "shared", "inherited from node 1" or "this clip only". The user can see exactly what the AI will use.

**Role: how each item is used** (set automatically, and the user can change it)

| Role | Meaning | Where it goes |
|---|---|---|
| Must appear | It has to be seen or heard in the clip | reference images given to the image and video models; the review agent checks that it is there |
| Look reference | Copy the style, not the content | the style input of the image model and the prompt |
| Start / end frame | Clip begins or ends on this picture | the video model's first or last frame input |
| Voice | Speak with this voice | voice cloning, set on the actor |
| Sound to use | Mix this audio in | mixer track (sound effect, music) |
| Music reference | Make music *like* this | prompt for the music model |
| Knowledge | Facts and instructions for the AI brain | script writing and review prompts |
| Include as-is | Use the footage or slides directly | assembly |

**How context is used automatically**
- **When planning:** the AI brain reads all shared and node context when it breaks down goals and writes scripts.
  - Example: the brief says "mention 400 g". The AI brain puts it in a script line.
- **When generating:** the router passes each item to the right input of the chosen model (reference images, start frame, prompt text, voice id, audio track).
  - If a model cannot accept a type, for example it allows only 3 reference images, the tool warns the user and picks the most relevant items. Or it suggests a model that can take them all.
- **When reviewing:** the review agent checks the clip against its effective context.
  - Example: "The logo (must appear) is not visible."
- **Estimates:** adding context can change the cost and time (for example a voice clone, or a model with reference input). The estimates update live.

**GUI (few clicks)**
- **Shared context:**
  - a **Context** tab in the inspector with two sections: **"Shared – all clips"** and **"This clip"** (for a goal node, the second section reads "This part and below")
  - files are dropped onto the tab; the type and role are guessed automatically. Examples: a face photo is treated as an actor, a logo file as a brand item, a wav file as audio
  - typing into "Add a note…" creates a text item
- **Clip context:**
  - each item shows as a small card with a thumbnail, its type, its role and its scope
  - inherited items are shown slightly faded, each with a switch to turn it off
  - an item is moved between scopes by dragging it, or by right-clicking and choosing "Move to shared"
- **Seeing and reusing context:**
  - the story tree shows a small 📎 count on nodes that have their own context
  - the **context library** (a full-page view) lists every item, with filters by type and scope, and "used in clips…" links
  - items can be reused across projects. Example: the brand kit

## Core concept 2: actors (photos and/or text)
Each actor is kept in a project **actor library**, and the profile can be reused across projects.

| Field | Options |
|---|---|
| Identity | name, role in the story |
| Appearance | **face photos** (optional) **or/and text description** (age, build, skin tone, hair, features) |
| Clothing | default outfit (text and/or photo). **Per-node override**, for example office clothes in node 2 and gym wear in node 5 |
| Behaviour | personality, mannerisms, body language, walking style, how they speak (fast, calm, gestures) |
| Voice | **voice sample** (clone) **or text description** (for example "deep, warm, Indian English, slow") → matching stock voice, which the user can preview and change |
| Props | items they usually carry |
| Kind | AI person, real person (from uploads), digital twin, animal, product |
| Consent | required whenever real photos or a real voice are uploaded |

- **Text only works fully.** The tool makes a photoreal reference sheet (front, ¾ view, full body) from the description alone. The user approves it, and that look is then locked for every clip.
- **With photos:**
  - The photos are checked for blur, angles and resolution.
  - The reference sheet is made from the photos with a multi-reference image model.
  - The quality score of each take compares the face with these photos.
- **With a voice sample:**
  - The sample is checked for length and noise, cleaned if needed, then cloned.
  - Every line marked with that actor's name uses the cloned voice.
- **Behaviour and clothing** are written into every clip prompt that includes the actor. This keeps how the actor acts and dresses the same throughout.
- **Consent:**
  - For uploaded real photos or a real voice, the user must confirm "this is me" or "I have permission". The tool stores this record.
  - The tool also passes on the provider's own checks.
  - The tool blocks realistic videos of public figures who have not given consent.

## Core concept 3: dependencies between clips (automatic, shown in GUI)
| Dependency type | What it means | How the tool handles it automatically |
|---|---|---|
| `continues_from` | Clip B starts exactly where A ended | Takes A's **chosen take's last frame** and uses it as B's **start frame** |
| `same_location` | B uses A's set or background | Reuses A's keyframe or set reference image |
| `actor_state` | Clothing, injury, props or position carry over | Copies A's ending state for each actor into B's prompt |
| `audio_carry` | Music or speech flows across | The mixer lets the sound carry across the join |
| `reference` | B shows something made in A (for example the product close-up) | Passes that image as a reference |
| `order_only` | Plain story order | Affects the final stitch only |

- **Detection:**
  - Claude suggests dependencies when it writes the scripts. Example: clip 2.2 says "continues as Priya stops walking" → `continues_from 2.1`.
  - Simple rules add the obvious ones. Example: clips cut from one long leaf.
  - The user can add, remove or change any dependency in the GUI.
- **Scheduling:**
  - The links between clips form a graph that runs one way, with no loops. The tool checks that there are no loops.
  - Clips that do not depend on each other are **made at the same time**.
  - A dependent clip **waits** for the take chosen for the clip before it.
  - If the user chooses another take, or remakes a clip, **every clip after it is marked "out of date"** and shown in the GUI. The tool then remakes only those clips, after confirming with the user.
- **GUI display:**
  - A **dependency graph view**: the clips are boxes, joined by arrows labelled with the link type.
  - In the tree view, each clip shows small "depends on" and "used by" icons.
  - The status of each clip is shown in colour: waiting, ready, generating, needs pick, done, out of date.
  - Clicking an arrow shows exactly what is passed. Example: a picture of the hand-off frame.

## Core concept 5: cost estimate for every clip — worked out live by the tool
The tool **calculates the cost itself, automatically, the moment a clip node is created**. The cost then **updates live** with every change, exactly as the length estimate does. Nothing is a fixed number written by hand. Goal nodes add up their children live, and the project shows a running grand total.

**When the cost is calculated, and how accurate it is** (it follows the length estimate):

| Stage | What triggers it | What the cost is based on | Shown as |
|---|---|---|---|
| 1. Clip created | the user adds a node, or the AI brain breaks down a goal | length range from the goal × likely model (from the shot type) × takes | range, for example "$2–$5" |
| 2. Script written or edited | any edit to the script, actors, model, resolution or takes | length from words + actions; the chosen model's price | narrower range, for example "≈ $3.10 (±15%)" |
| 3. Voice made | real audio length is known | exact seconds × price | single figure, for example "$3.09" |
| 4. Clip made | provider calls finish | **actual charge** from the provider response (or catalogue price) | "actual $3.21 (est. $3.09)" |

- **What causes a recalculation:**
  - editing goal or script text
  - adding or removing an actor, or dialogue
  - changing the shot type, model, resolution or number of takes
  - adding a lip-sync need
  - a price update
  - a change in an earlier clip that this clip depends on

  The GUI updates the clip, its parent nodes and the project total straight away, over WebSocket.
- **Where the cost is shown:** in the goal tree, next to the length (for example `2.2  ~35 s  ≈ $4.80`), in the node editor (full breakdown), and in the estimate bar (total against budget).
- **Live price data:** the tool fetches prices from each vendor's pricing or usage source where one exists, through a plugin method `price_lookup()`.
  - Examples: an aggregator's model pricing information, or the credits a provider reports.
  - Where no vendor source exists, the tool uses the catalogue price and shows its "last checked" date.
  - Prices are cached for 24 hours.
  - When a price changes, every affected clip is recalculated and highlighted.
- **Breakdown for each clip** (worked out by the tool; the table below is just an example of what the GUI would show):

Example cost breakdown for clip 1.2, "Rahul's strap snaps" (7 s, people in motion, routed to Kling 3.0 at 1080p with audio):

| Item | Calculation | Est. cost |
|---|---|---|
| Keyframe images | 3 takes × 1 image × ~$0.04 | $0.12 |
| Video | 3 takes × 7 s × ~$0.14/s | $2.94 |
| Voice (1 line, 12 words) | ~70 characters × Eleven v4 rate | <$0.01 |
| Lip-sync fix | not needed (no on-camera speech) | $0.00 |
| Share of music bed | 7 s of a 180 s track | $0.03 |
| **Clip total** | | **≈ $3.09** |

These prices are examples only. Real prices come from `catalog.yaml`, and each price carries the date it was last checked.

How the estimate works:
- The formula for each item is **unit price × units × takes**. The units come from the length estimate: seconds, images, characters or minutes.
- **The cost changes as the length estimate changes** (goal → script → real audio length).
- **"What-if" options in the GUI:**
  - change the model (for example Kling → Veo 3.1 Fast)
  - change the resolution
  - change the number of takes

  The cost of the clip and of all its parent nodes updates straight away. The GUI also shows the cheapest model that fits the shot.
- **After generation:** the tool records the **actual cost** of each provider call. It uses the provider's own usage response where the provider gives one, and otherwise the catalogue price.
  - These records go into a spending log (`ledger.jsonl`).
  - The GUI shows estimated against actual cost for each clip, and the money spent so far against the budget.
- **Budget guard:**
  - It stops before any clip whose estimate would take the spending past the set budget.
  - Retries and extra takes count against the budget.
- **Price refresh:** `vg catalog check` lists the prices that are more than 30 days old. The user can then update them from each vendor's pricing page (links are stored in the catalogue).

## Core concept 6: estimate before making, and run controls
### Cost and time are known before anything is paid for
- **Before** the user presses any Generate button, every clip (and every goal node) already shows:
  - the **estimated cost**
  - the **estimated time to make**

  These come from the live estimator (stages 1–3 above), which uses only the plan and the script. No paid model is called. The only exception is the AI brain writing the script, which costs fractions of a cent and is shown too.
- **How the time estimate is calculated**, for each step:
  - the provider's average queue wait plus generation time per output second, taken from the catalogue
  - this is **corrected by the tool's own history**: the real times of recent jobs per provider, kept in the spending log
  - steps that run at the same time are counted once; steps that must wait for an earlier clip are added up

  Example: "Clip 2.1: ≈ $2.60, ≈ 6 min. Whole video: ≈ $41, ≈ 38 min (12 clips, 4 run at the same time)."
- **Confirmation box** on every Generate button:
  - the cost and time for the clips that will be made
  - which earlier clips must be made first
  - money spent so far against the budget
  - the user confirms or cancels
- **Free trial run:** a "Preview with free tools" option makes a rough draft in a few minutes, at no cost:
  - placeholder keyframes
  - the local voice (Kokoro)
  - slide-style motion
  - the real timings

  This lets the user check pacing and length before paying.

### Generation controls (GUI buttons + command line)
| Button | What it does |
|---|---|
| **Generate entire video** | Makes every clip in dependency order, running independent clips at the same time, then stitches the final video |
| **Generate this clip** | Makes only the selected clip. If an earlier clip it depends on is not made yet, the tool asks: "Clip 2.2 needs 2.1 first (+$2.60, +6 min). Generate both?" |
| **Generate next** | Makes the next clip in story/dependency order. Pressing it again makes the one after |
| **Continue to the end** | After making a few clips one by one, this runs **all remaining clips** to completion |
| **Pause / Resume** | Pause stops new jobs from starting. Jobs already running finish and are saved. Resume continues from the same point |
| **Stop** | Cancels jobs that are still waiting. Finished clips are kept |
| **Re-make** | Re-makes one clip. Later clips that depend on it are marked "out of date", with their extra cost shown |

- **Example flow:**
  1. The user presses **Generate next** three times (clips 1.1, 1.2, 2.1).
  2. The user watches each one and is happy.
  3. The user presses **Continue to the end**. The remaining 9 clips run, and the final video is stitched.
- **Picking takes during a long run:** the user chose to pick takes themselves.
  - In "Continue to the end" mode, the run **keeps making all independent clips** while it waits for the user to pick.
  - Only the clips that depend on a not-yet-picked clip wait.
  - The GUI shows a "3 takes waiting for your pick" alert.
  - Optional switch: **"Auto-pick best take for this run"**. It uses the quality score, so the run can finish unattended. The user can change any pick afterwards, which marks the dependent clips as out of date.
- **Live progress:**
  - each clip's status
  - a progress bar
  - estimated time left, updated as each job finishes
  - cost so far against the estimate
- **Budget guard:** if the next clip would take spending past the budget, the run pauses and asks the user.
- **Command line equivalents:**
  - `vg render --all`
  - `vg render <clip>`
  - `vg render --next`
  - `vg render --continue`
  - `vg pause`, `vg resume`, `vg stop`
  - `vg estimate [node]`, which shows cost and time before any run

The run state is saved in `project.json`. If the computer restarts in the middle of a run, `vg resume` continues from where it stopped.

## Core concept 7: Review Agent (AI checks quality and goal; the user always decides)
After each take is made, a **Review Agent** watches the clip and judges it. It then writes feedback for making the clip again. **The user is always in the loop:**
- The agent only *suggests*.
- Nothing is made again until the user reviews the feedback, adds or edits their own, and presses **Re-make with feedback**.

**What the agent looks at:**
- **Frames:** sampled frames, about 1 per second plus every scene change, and the first and last frames.
- **Audio:** the speech in the clip is turned into text with a speech-to-text plugin (local `faster-whisper` by default, free; cloud Whisper or Gemini optional). This text is compared with the script.
- **Video as a whole:** where the brain supports full video understanding (for example a Gemini plugin), the whole clip is sent.
- **The context:**
  - the clip's goal and its parent goals
  - the script
  - the actor references (face, clothing, behaviour)
  - the dependency hand-off (does it really continue from the previous clip?)
  - the target length

**What it checks, with a score of 1–5 and a written comment for each:**

| Check | Example finding |
|---|---|
| Goal met | "Goal says the strap *snaps*; in the clip the strap only slips." |
| Script followed | "The line 'This bag weighs 400 g' is missing from the audio." |
| Actor match | "Priya's face matches (0.82 face similarity), but she wears a red top; her profile says blue kurta." |
| Behaviour | "Rahul is described as frustrated; he smiles throughout." |
| Realism and technical quality | "Left hand shows 6 fingers at 00:04; slight face flicker at 00:05; skin looks waxy." |
| Continuity | "Clip 2.1 ended with the bag in the right hand; 2.2 starts with it in the left." |
| Timing | "Clip is 9 s, script estimated 7 s; speech ends at 6 s, leaving 3 s of dead air." |
| Lip-sync | "Mouth movement lags speech by about 0.3 s." |

The agent also uses the automatic checks from the `QualityScorer` plugins (face similarity, flicker), so its comments rest on measurements as well as judgement.

**Its output (a structured `Review`):**
- an overall verdict: `meets goal` / `minor issues` / `does not meet goal`
- the scores for each check
- issues with time stamps, each with a frame thumbnail
- **a suggested fix**: specific changes to the clip's prompt, settings or model.
  - Example: "add 'strap tears apart at the stitching, bag drops to the floor'; switch to Kling 4 for better hand motion; negative prompt: extra fingers"
- the **estimated cost and time** of making the clip again with the fix

**How the user stays in control (the review screen in the GUI):**
1. The takes are shown side by side, each with the agent's verdict, scores and issue markers on its timeline. Clicking a marker jumps to that moment.
2. The user can:
   - **accept** a take
   - **reject** a take
   - **edit the agent's suggestions**: tick or untick each one, or change the text
   - **add their own feedback**, for example "make it slow motion when the strap breaks"
3. **Re-make with feedback:**
   - The AI brain **combines the agent's accepted suggestions and the user's feedback** into a revised clip script and prompt.
   - If the two conflict, the user's feedback wins.
   - The user sees the revised script **as a before/after comparison** and the new cost and time, then confirms.
4. Each version is kept: **v1 → v2 → v3**, with the feedback that led to it.
   - The user can compare versions or go back to an older one.
   - The agent sees the earlier feedback, so it does not repeat the same advice.

**How the agent works with the run modes:**
- With **Generate next** and **Generate this clip**: the review appears straight after the takes are made.
- With **Continue to the end**: reviews are queued up.
  - Clips the agent rates `does not meet goal` are flagged in red.
  - With auto-pick on, the agent's score is used together with the quality score.
  - **The tool never makes a clip again on its own.** It collects the suggestions for the user to approve at the end, or at any time.
- **Higher-level reviews:** once all the clips under a goal node are assembled, the agent reviews that node against the node's goal (story flow, pacing, consistency). At the end, it reviews the final video against the project goal.
  - Example: "The hook is 31 s against the 20 s goal; the call to action does not show the price."
  - These reviews also lead to suggestions that the user approves.

**Plug-in design:**
- New interfaces:
  - `Reviewer`, the review agent. It is vendor-neutral and uses the configured brain (Anthropic, OpenAI, or a Gemini plugin, which can watch full videos).
  - `Transcriber`, for speech-to-text.
- Settings: the reviewer model can be set separately from the script brain, for example `reviewer: openai` and `llm.default: anthropic`.
- The review can be switched off for each clip or each run. Its small cost is shown in the cost breakdown and the estimates.

## Vendor accounts the user must set up (pay-as-you-go)
Not every vendor is needed. Recommended **starter set: 3–4 accounts**, which reach most of the models through the aggregator fal.ai.

| # | Vendor | Used for | Sign up / billing | Pricing / docs | Needed? |
|---|---|---|---|---|---|
| 1a | Anthropic (Claude API) | AI brain: breaking down goals, scripts, estimates, continuity | https://console.anthropic.com | https://www.anthropic.com/pricing | **One of 1a / 1b required** |
| 1b | OpenAI API (GPT models) | the same AI-brain jobs as 1a (also GPT Image) | https://platform.openai.com | https://openai.com/api/pricing | **One of 1a / 1b required** |
| 2 | fal.ai (aggregator) | Kling, Seedance, Wan, Veo, Flux images, VEED Fabric, MiniMax music, lip-sync, through **one key** | https://fal.ai/dashboard | https://fal.ai/pricing | **Recommended** |
| 3 | ElevenLabs | voices, voice cloning, music | https://elevenlabs.io/app | https://elevenlabs.io/pricing/api | **Recommended** |
| 4 | Google AI Studio / Gemini API | Veo 3.1 direct, Nano Banana images, Gemini Omni | https://aistudio.google.com (billing via Google Cloud) | https://ai.google.dev/gemini-api/docs/pricing | Recommended for people speaking in scenes and for images |
| 5 | HeyGen API | digital twin / presenter avatars | https://www.heygen.com/api (prepaid wallet, minimum top-up $5) | https://www.heygen.com/api-pricing | Only if digital twin is used |
| 6 | Kling AI (official) | Kling direct | https://app.klingai.com/global/dev | https://app.klingai.com/global/dev/document-api | Optional (fal is simpler; the official API has needed prepaid packages) |
| 7 | BytePlus ModelArk | Seedance direct | https://console.byteplus.com/ark | https://www.byteplus.com/activity/modelark | Optional (also on fal) |
| 8 | Alibaba Cloud Model Studio | Wan 3.0 direct | https://www.alibabacloud.com/product/modelstudio | https://www.alibabacloud.com/help/en/model-studio/video-generation | Optional (also on fal / OpenRouter) |
| 9 | Runway API | Gen-4.5, camera control | https://dev.runwayml.com | https://docs.dev.runwayml.com/guides/pricing | Optional ($0.01 per credit) |
| 10 | Luma AI API | Ray video | https://lumalabs.ai/api | https://docs.agents.lumalabs.ai/guides/pricing/ | Optional |
| 11 | Cartesia | voice (alternative to ElevenLabs, cheaper) | https://play.cartesia.ai | https://cartesia.ai/pricing | Optional |
| 12 | Sync.so | lip-sync fix | https://sync.so | https://sync.so/pricing | Optional (also on fal) |
| 14 | Replicate (aggregator) | another route to many models | https://replicate.com/account/billing | https://replicate.com/pricing | Optional |

- **Free, no account needed:** ffmpeg, Kokoro, Chatterbox, Qwen3-TTS, and the local face-similarity scorer.
- **`vg vendors`** prints this table with each vendor's status: configured or not, and which shot types become available when that key is added.
  - Example: "Add HEYGEN_API_KEY to enable the digital twin".
- **Before building:** each URL and price is re-checked on the vendor's official page. Sign-up rules change. Example: the official Kling API once needed a large prepaid commitment.

## Core concept 4: length estimates
Every clip and goal node shows an **estimated length**. Parent nodes add up their children's estimates.

The length is estimated in three stages, each more accurate than the one before:
1. **From the goal** (before any script exists): Claude gives a target range based on the goal and the length it has been given.
   - Example: "Hook ~15–25 s".
2. **From the script:**
   - Speech time = number of words ÷ speaking rate. The speaking rate depends on the language and on how the actor speaks. Example: 150 words per minute for calm English, faster for an excited actor.
   - The time needed for actions is added. Example: "walks into frame" ≈ 3 s.
   - The pauses between lines are added.
   - The result is limited by the maximum clip length of the chosen model.
   - Example: 2.2 has 80 words at 140 words per minute ≈ 34 s, plus 1 s pause ≈ **35 s**.
3. **After voice generation:** the real length of the generated audio replaces the estimate. The clip length is then set to match it.

Rules:
- **Fixed lengths:** user clips use their actual length, read with ffprobe. Slides use a time per slide that the user can change.
- **Warnings:**
  - when the total is more than 10% above or below the target. Example: "Project is ~3:40 vs target 3:00. Node 3 is the largest contributor."
  - when a leaf is too long for one model clip, with a suggestion to split it
- **Shown next to the length:** the **estimated cost** and the **estimated time to generate** each node. Cost and time take the takes into account (3 takes for clips with people) and come from the catalogue prices.

## Pipeline (for each clip leaf; run in dependency order)
```
Goal tree built & approved (scripts per leaf)  ◄ approve
 ─► Actors: reference sheets + voice clones / stock voice picks ◄ approve
 ─► per clip, in dependency order (parallel where independent):
      Voice (sets exact length) → Keyframe (uses inherited style, actor sheets,
      hand-off frame from dependency) ◄ approve → cost check → Motion (routed by
      shot type; 2–3 takes for people) ◄ pick take → Lip-sync fix if needed
      → clip ready → dependents unlocked
 ─► Assemble each goal node bottom-up (children joined with transitions)
 ─► Final stitch: make everything match (resolution, frame rate, loudness), music bed, subtitles
 ─► continuity check by Claude ─► final.mp4 / final.mov + .srt
```

## Choosing tools: catalogue + shot-type routing (all editable)
`catalog.yaml` lists each model with:
- shot-type strengths
- capabilities (start frame, end frame, reference images, own audio, maximum length)
- price per second
- licence
- date last checked

| Shot type | Default first choice → fallbacks |
|---|---|
| Digital twin / presenter to camera | HeyGen Avatar → VEED Fabric → Kling Avatar |
| Person speaking in a scene | Veo 3.1 → Seedance 2.x → Kling + Sync.so lip fix |
| People moving, hands, objects | Kling 3.x/4 → Seedance 2.x |
| Animals, nature, landscape, effects | Veo 3.1 / Gemini Omni → Wan 3.0 → Kling |
| Product shot from real photo | Kling / Runway → Veo |
| `continues_from` clip | only models that accept a **start frame** |
| Slides / user clip | ffmpeg only |

- `vg compare <clip> --models veo,kling,seedance` makes the same clip with each model, so the user can judge them on their own content.

## The AI "brain" (language model) is swappable: Anthropic, OpenAI, or others
*Note: wherever this plan says "Claude", it means "the configured AI brain". That can be Claude, GPT, or any other model added later.*

All of the text tasks go through one `ScriptWriter` interface, never through a specific company's SDK. The text tasks are:
- break down a goal
- write a clip script
- revise
- suggest dependencies
- estimate lengths
- check continuity
- write image and video prompts

How the switch works:
- **Two built-in plugins with equal support:**
  - `anthropic` (Claude models)
  - `openai` (GPT models)
  - Each one translates the same request into its vendor's API.
- **Prompts do not depend on the vendor.** The prompt templates live in `video_generator/prompts/`, and both plugins use the same templates.
- **Answers do not depend on the vendor.** Every answer must match the same pydantic JSON schema, for example `GoalTree`, `ClipScript` or `DependencyList`. Both vendors support schema-based structured output. If an answer fails the check, the tool sends it back once with the error so the model can fix it.
- **Switching is one line in `config.yaml`:**
  ```yaml
  llm:
    default: openai          # or: anthropic
    models: { anthropic: claude-opus-5-5, openai: <chosen GPT model> }
    per_task:                # optional: mix vendors per task
      decompose: anthropic
      write_clip_script: openai
  ```
  The same choice is available in the GUI (Settings → AI model) and on the command line (`vg config set llm.default openai`).
- **Fallback:** if the default vendor fails or has no key, the router tries the other configured vendor.
- **Later additions:** Gemini, or a local model through Ollama, can be added as more plugins in the same way. No core change is needed.
- **Fair comparison:** `vg compare-llm <node>` runs the same task with both vendors. The two results are shown side by side.
- **Tests:** the same tests run against both plugins (one shared test suite), so the two are kept equal.

## Plug-in design (any new tool later)
- `plugins/base.py` defines one interface per job:
  - `ScriptWriter` (with `decompose`, `write_clip_script`, `revise`, `suggest_dependencies`, `estimate_duration`)
  - `ImageGenerator`
  - `VideoGenerator`
  - `AvatarGenerator`
  - `VoiceSynth` (+ `clone_voice`, `match_voice(description)`)
  - `LipSync`
  - `MusicGenerator`
  - `Ingestor`
  - `QualityScorer`
  - `Assembler`
- Each plugin declares its `name`, `capabilities`, `licence`, `cost_estimate()`, `time_estimate()` and `is_configured()`.
- New plugins are **found automatically** through Python entry points (`video_generator.plugins`). Example: `pip install vg-plugin-x`, add one line to `catalog.yaml`, and the tool uses it. No core change is needed.
- A shared `JobPlugin` base class gives every cloud service the same submit → poll/webhook → download flow, with retries.
- The aggregator plugins `fal` and `replicate` give access to many models through one key.

**Version 1 plugins:**
- **AI brain (ScriptWriter):** `anthropic` (Claude, for example `claude-opus-5-5`), `openai` (GPT model set in config)
- **Image:** `nano_banana`, `gpt_image`, `flux`
- **Video:** `veo`, `kling`, `seedance`, `runway`, `wan`, `gemini_omni`, `luma`
- **Avatar:** `heygen`, `veed_fabric`, `kling_avatar`
- **Voice:** `elevenlabs`, `cartesia`, `chatterbox`, `qwen3_tts`, `kokoro`
- **Lip-sync:** `sync_so`
- **Music:** `elevenlabs_music`, `local_file`
- **Aggregators:** `fal`, `replicate`
- **Ingest:** `pdf_slides`, `pptx_slides`, `video_clip`, `audio_sample`, `photo_set`
- **Quality:** `face_similarity`, `flicker`
- **Review agent:** `reviewer` (uses the anthropic, openai or gemini brain)
- **Speech-to-text:** `faster_whisper` (local), `openai_transcribe`
- **Assemble:** `ffmpeg`
- **Fake:** offline test versions of every interface

## Data model (pydantic; saved as `project.yaml` + per-node files)
- `Project`:
  - goal
  - settings: target length, aspect ratio, format, budget, takes for people clips = 3
  - style bible
  - `actors[]`
  - `root: Node`
  - `dependencies[]`
- `Node`:
  - `id` (like `2.1`)
  - `kind` = `goal` | `clip` | `slides` | `user_clip`
  - `goal_text`
  - `children[]`
  - `inherited` + `overrides` (style, location, mood, actors, clothing)
  - `estimate` {min, likely, max seconds; `basis` = goal/script/actual}
  - `cost_estimate`
  - `status`
- `ClipScript` (on leaves):
  - shot type
  - action beats
  - camera
  - `actors_in_shot[]` (each with clothing and behaviour for this clip)
  - dialogue lines {speaker, text, emotion}
  - narration
  - sound/music notes
  - `provider_override`
  - `takes[]`
  - `chosen_take`
  - `versions[]` (v1, v2, …, each with its script, the feedback that produced it, and its takes)
- `Review`:
  - `target` (take or node)
  - `verdict`
  - `scores{}`
  - `issues[]` (time, frame, text, check)
  - `suggestions[]` (text, accepted yes/no)
  - `user_feedback`
  - `reviewer_model`
  - `cost`
- `Actor`:
  - name, role, kind
  - `photos[]`, `description`
  - `clothing_default`
  - `behaviour`
  - `voice_sample` or `voice_description` → `voice_id`
  - props
  - `reference_sheet[]`
  - `consent`
- `ContextItem`:
  - `id`
  - `type` (actor, object, entity, location, style, audio, text, media)
  - `title`
  - `text`
  - `files[]`
  - `role`
  - `scope` = project | node:<id> | clip:<id>
  - `consent` (when real people's faces or voices are included)
  - `analysis` (automatic tags, captions, length)
- On `Node`:
  - `context_add[]`
  - `context_override{}`
  - `context_off[]`
  - The **effective context** is worked out from the root of the tree down to the clip.
- `Dependency`:
  - `from`, `to`
  - `type`
  - `source` = ai/rule/user
  - `payload` (for example the hand-off frame path)
- Each step stores a **hash of its inputs**. Unchanged work is skipped, and work that depends on something changed is marked "out of date".

## GUI (local web app)
- **Backend:** FastAPI. It uses the same service layer as the command line. Progress updates come live over WebSocket.
- **Frontend:** React + TypeScript (built with Vite).
  - React Flow draws the dependency graph.
  - A tree component shows the goal tree.
  - The built frontend is shipped inside the Python package, so the user still runs one command: `vg gui`.

### User experience: enterprise quality, modern, minimal clicks, almost no learning
**Design principles**

1. **Goal first, everything else optional.**
   - The first screen has **one large box**: "What video do you want to make?". Next to it are an optional drop zone for files (slides, clips, photos, voice) and a length picker.
   - Pressing Enter (**1 action**) makes the AI brain produce a complete first draft:
     - the goal tree
     - the scripts
     - the actors, taken from the text and any uploaded photos
     - the links between clips
     - the length, cost and time estimates
   - The user then *edits a draft*. They never fill in an empty form.
2. **Smart defaults everywhere.** These are all decided automatically and shown as small labels the user can change. Example: a label "Model: Kling 3 ▾" that opens a list.
   - which model to use, and the takes, resolution and transitions
   - the voices
   - the link types between clips

   The advanced settings stay hidden under "More options" until needed (*progressive disclosure*: show the simple options first and the advanced ones on request).
3. **One clear main action on each screen.** It changes with the state: Generate draft → Approve plan → Generate video → Download. Secondary actions are smaller.
4. **Edit where you see it.** Click any text to change it in place. This includes goals, script lines, actor details and estimates. There is no separate "edit mode" and no Save button: everything is **saved automatically**.
5. **Undo instead of "Are you sure?"** Every change can be undone (Ctrl+Z, plus a version history). Confirmation boxes appear **only when money is about to be spent** or something is deleted for good.
6. **Natural-language commands everywhere.**
   - An "Ask AI" box on every node, and a project-wide command bar (Ctrl+K).
   - Example commands: "make the hook shorter", "give Priya a blue kurta in all clips", "generate the next two clips".
   - The tool shows what will change before it applies it.
7. **Drag and drop everywhere.**
   - Drop photos on an actor.
   - Drop a voice file on an actor.
   - Drop a clip or slides into the tree.
   - Drag nodes to reorder them.
8. **The tool explains itself in context.**
   - Hover hints on every estimate. Example: "35 s = 80 words at 140 wpm + 1 s pause".
   - Plain-language status messages.
   - Helpful empty states.
   - A 60-second guided tour on first use, which can be skipped.
   - The user never needs a manual.
9. **Always visible:**
   - total length against the target
   - cost against the budget
   - time left
   - items waiting for the user (takes to pick, reviews to approve)

   These sit in one slim status bar.

**Layout (one main workspace, no page-hopping)**
```
┌ Top bar: project name · AI brain ▾ · Budget $41/$60 · ⌘K command · Share/Export ┐
├──────────────┬───────────────────────────────────────────┬──────────────────────┤
│ Story (tree) │  Selected node: goal / script / preview   │  Inspector (tabs):   │
│ 1 Hook  20s  │  ┌ Clip 1.2 "Rahul's strap snaps" ──────┐ │  Actors · Review ·   │
│  1.1 ✓ 6s    │  │ [video player / keyframe / takes]    │ │  Cost · Links ·      │
│  1.2 ⚠ 7s    │  │ Script (inline edit) · Ask AI…       │ │  Versions            │
│ 2 Product…   │  └──────────────────────────────────────┘ │                      │
├──────────────┴───────────────────────────────────────────┴──────────────────────┤
│ Timeline: clips as blocks sized by length, link arrows, status colours ·        │
│ ▶ Generate next   ⏩ Continue to end   ⏸   ·  3:05 / 3:00  ·  $38.40  ·  ~32 min │
└─────────────────────────────────────────────────────────────────────────────────┘
```
- **Story panel:** the goal tree with the length, cost and status of every node.
- **Timeline:** the whole video at a glance. The dependency arrows are drawn here. A full graph view opens with one click.
- **Inspector:** shows everything about the selected item. The review agent's findings appear here as cards, each with **Accept / Edit / Dismiss**.
- **Takes and reviews** open in the centre as side-by-side players, with the issue markers on each timeline.

**Click targets (measured in tests)**

| Task | Target |
|---|---|
| Goal → complete draft plan | 1 action (type + Enter) |
| See cost and time for any clip | 0 clicks (always visible) |
| Generate the entire video | 2 clicks (button + confirm spend) |
| Generate next clip | 2 clicks |
| Pick a take | 1 click |
| Accept AI review suggestions and re-make | 2 clicks (Accept all → Re-make + confirm) |
| Add an actor with photos | 1 drag-drop + type a name |
| Change a model or setting for one clip | 2 clicks |
| Download final video | 1 click |

**Enterprise-quality basics**
- **Design system:**
  - shadcn/ui components (built on Radix, so they are accessible)
  - Tailwind CSS
  - one consistent set of colours, fonts and spacing
  - light and dark themes
  - Lucide icons
- **Data and speed:**
  - TanStack Query for loading and caching data, with optimistic updates (a change shows on screen at once, before the server confirms it)
  - WebSocket live progress, with no page reloads
  - video previews use low-resolution proxy files, so the interface stays fast with large projects
- **Accessibility:** WCAG 2.2 AA, which is the standard accessibility level for websites.
  - full keyboard use
  - screen-reader labels
  - colour is never the only signal; status uses both an icon and a colour
- **Reliability:**
  - autosave and crash-safe state
  - clear error messages, each with a "Try again" or "Use another model" button
  - a full activity log for every action and every amount spent
- **Ready for growth:**
  - all interface text in one place, so other languages can be added later
  - the layout adapts to laptop and large screens; a tablet works for reviewing clips
  - access control and sharing for several users (login, roles, comments) are left out of version 1, but the backend API is designed so they can be added later
- **Before the interface is built:** a clickable prototype of the main workspace is made first, so the user can approve the look and flow.

**Screens (all inside the one workspace)**
1. **Start:** the goal box, the drop zone and recent projects.
2. **Workspace:** the story tree, the centre editor or preview, the inspector, and the timeline (described above).
3. **Actor library:** a card grid.
   - Drop in photos or write a description.
   - Clothing, behaviour, and a voice sample or voice description.
   - A ▶ button to preview the voice.
   - Consent is a single checkbox, with the details in a tooltip.
4. **Graph view:** the full dependency graph (React Flow). Click an arrow to see what is handed over.
5. **Takes and review:** the takes side by side, with the agent's cards and your feedback box.
6. **Settings:** API keys (with a "Test" button), the AI brain, the model catalogue, the budget, and the vendor status from `vg vendors`.

## Command line (same features, for scripting)
- `vg new "<goal>" --length 180`
- `vg tree show|decompose <node>|add|move|remove`
- `vg script <leaf>`
- `vg revise <node> "<text>"`
- `vg actor add priya --photos … --voice … --description … --clothing … --behaviour …`
- `vg deps show|add|remove`
- `vg estimate [node]`
- `vg render [node] [--yes]`
- `vg compare <leaf> --models …`
- `vg plugins`
- `vg catalog [check]`
- `vg vendors`
- `vg cost [node]` (estimate, plus actual cost once the clip is made)
- `vg gui`

## Safety
- Consent is recorded for each real person whose photos or voice are uploaded, including the user's digital twin.
- Realistic videos of public figures are blocked when there is no consent.
- A budget guard stops any render that would cost more than the set limit. The estimate counts the takes.
- API keys are read only from the environment or `.env`.
- Each plugin's licence is shown.

## Files to create (main ones)
- Root: `pyproject.toml`, `README.md`, `catalog.yaml`, `config.example.yaml`, `.env.example`
- `video_generator/`:
  - `models.py`
  - `tree.py` (goal tree, inheritance)
  - `deps.py` (dependency graph, ordering, marking work out of date)
  - `estimate.py` (length, cost, time)
  - `registry.py` (plugins, catalogue routing)
  - `pipeline.py`
  - `services.py`
  - `cli.py`
  - `project.py`
- `video_generator/plugins/…` (as listed above)
- `video_generator/web/` (FastAPI API + WebSocket)
- `frontend/` (React app)
- `docs/writing-a-plugin.md`, `examples/vg-plugin-example/`
- `tests/`

## Build order
1. Data model, goal tree with inheritance, dependency graph, estimator, plugin registry, fake plugins, and the command line. The full pipeline runs offline.
2. ffmpeg ingest, assembly and stitching, plus local voice (Kokoro, Chatterbox). A real free video can be made from slides and clips.
3. Claude: break down goals, write clip scripts, revise, suggest dependencies, estimate lengths. Plus the budget guard.
4. Actors: photo checks, reference sheets from photos or text, voice cloning or voice matching (ElevenLabs, Cartesia), consent.
5. Image and video plugins, shot-type routing, start-frame hand-off, takes, and `vg compare`.
6. Avatar plugins, Sync.so lip-sync, quality scorers, music.
7. Review agent and speech-to-text: reviews of clips and nodes, the feedback merge, version history.
8. GUI:
   1. Build a clickable prototype of the workspace with sample data, and get the user's approval.
   2. Then build the full GUI: the goal box, the workspace (story tree, editor, inspector, timeline), the actor library, the graph view, takes with review, run controls, settings, the command bar and undo.
9. Plugin guide and an example external plugin.

## Verification
- **pytest:**
  - goal tree editing and inheritance
  - dependency loop detection, ordering, and marking later clips "out of date" after a take changes
  - the start-frame hand-off uses the chosen take's last frame
  - length estimate from script and from actual audio, totals for parent nodes, and the target warnings
  - routing (including start-frame-only models for `continues_from`)
  - discovery of plugins through entry points
  - consent blocking
  - an actor defined by text only
  - the same AI-brain test suite passes for both `anthropic` and `openai` (with recorded API responses, so no network is needed)
  - switching `llm.default` changes the vendor with no other change
  - cost for each clip = unit price × units × takes
  - parent nodes add up their children's costs
  - the what-if option recalculates the cost
  - a cost range appears as soon as a node is created
  - context:
    - the effective context combines project, node and clip items
    - an override replaces an inherited item, and "switch off" removes it
    - each role is passed to the right model input
    - a model's input limits produce a warning and the most relevant items are chosen
    - the review agent flags a missing "must appear" item
    - a text-only item works
  - Review agent:
    - with a fake model, a planted problem (a missing script line in the transcript) creates an issue and a suggestion
    - re-make combines the accepted suggestions with the user's feedback, and the user's feedback wins when they conflict
    - nothing is made again without user approval, including in "Continue to the end" mode
    - versions are kept, and going back to an old version works
  - the time estimate counts parallel steps once and waiting steps in sequence, and is corrected by the history of real job times
  - run modes:
    - "Generate next" makes one clip, then "Continue" finishes the rest
    - "Generate this clip" asks before making earlier clips it needs
    - Pause and Resume work, including after a restart
    - while waiting for a take pick, independent clips keep running
  - the cost range narrows after the script and becomes exact after the voice
  - a price change recalculates the affected clips
  - `price_lookup()` falls back to the catalogue price
  - the spending log records estimated against actual cost
  - the budget guard stops before a clip that would go over budget
- **Offline end-to-end:**
  - a 3-level tree with 2 actors (one with photos and a voice sample, one text only), one `continues_from` link, slides, and a user clip
  - run with fake image, video and avatar plugins and real Kokoro voice
  - ffprobe checks the final file's streams and its length (within the estimate)
- **GUI check:** use Playwright with the pre-installed Chromium to:
  - break down a node
  - add an actor
  - see the dependency arrow
  - pick a take
  - check that the total length and the total cost both update live when a clip is edited
  - check that cost and time are shown before Generate is pressed
  - "Generate next" twice, then "Continue to the end", finishes the video (using the fake plugins)
  - **click-count tests:** each task in the click-target table is done within its target. The test fails if it takes more clicks
  - **accessibility:** automatic checks with axe-core report no serious problems, and the main flows can be done with the keyboard only
  - **speed:** the workspace opens in under 2 seconds for a project with 50 clips
- **Usability check with the user:**
  - Prototype first. The user approves the clickable prototype before the full interface is built.
  - First-run test: with no instructions, a new user goes from goal to a generated draft video using only the screen.
- **Live smoke tests:** these run only when an API key is set. One short clip per provider, plus a run of `vg compare`.
- **Pluggability:** install the example plugin, add it to the catalogue, and confirm that the router picks it.
- Commit and push to `claude/stoic-pasteur-76elrs`.


## v3.9 additions (what they do and why)

- **Cause of a placeholder** (`Service.preview_info`): every clip that only gets a free placeholder carries a cause: `pinned` (you chose a free model for the clip), `no_key`, `free_mode`, `not_covered`. Only `no_key` produces an "add a key" hint. `Service.unpin` clears pins and marks clips that were made as placeholders out of date.
- **Auto length** (`Settings.length_mode`): `auto` = no length asked for; the draft prompt says "as short as the story allows" and the plan's own total becomes the target. Asking for a length sets `fixed`. Projects made before this setting stay `fixed`.
- **Language** (`Settings.language`, `languages.py`, `data/languages.yaml`): a short code. `auto` lives only until the first draft, when the planner's `language` replaces it. Voice and speech-to-text services never receive `auto`.
- **Cost by part** (`Service.parts_table`) and a **price ballpark** before any plan exists (`estimate.ballpark`, assumptions in `policy.ballpark_*`).
- **Every model listed** (`Service.model_rows`, `models_list.py`): price in words, abilities, and the exact reason a model cannot be used. Brain models are chosen per kind of work (`llm.per_task_model`, kinds: default, review, simple). `Registry.llm_entry` finds the catalogue row by plugin AND model, so each AI call is priced by the model that answered. A vendor's own model list is read with the data in `vendors.yaml → models_list`.
- **Music made once** (`musictrack.py`): the track is saved with what it was made from; `Engine._ensure_music` reuses it while the mood and reference are unchanged and the video is not longer than the track by more than `policy.music_reuse_tolerance`. The estimate shows "Music (saved track, reused) $0".
- **Download any part** (`Engine.export_node`): a clip is its finished file; a part is `Engine._join_node` (the same join the final video uses), a slice of the saved music (`media.music_slice`), and subtitles counted from the start of the part. Nothing is spent without asking: with no saved track and a paid music model the answer is `needs_music_choice` with the cost.


## v3.10 additions (what they do and why)

- **Right numbers** (`estimate._words`, `speech_need`, `clip_floor`): words are pieces between spaces that hold a letter, mark or number (so one Hindi word is one word); scripts written without spaces count `policy.unspaced_chars_per_word` characters as a word. A clip's floor is the largest of its speech and pauses, its action steps times `min_action_seconds`, the shortest length the chosen model can make, and `min_clip_s`. The planner may set each speaker's `speaking_wpm`.
- **Length edits cascade** (`scaling.py`): `scale_node` rescales the clips under a node in proportion, never below their floors, leaving protected clips alone (`scaling.protected`: made, locked, or not an AI clip). It returns what moved and why it stopped. `DialogueLine.fixed` and `ClipScript.narration_fixed` mark text that is never shortened, reworded or dropped; `brain.preserve_fixed` puts such lines back after any rewrite. `Service.rewrite_offer` prices (never starts) the rewrite of the scripts under a part after its goal was edited.
- **Quality per part** (`Node.quality_mode`, `estimate.mode_for`): own choice, else the nearest part above, else the project. `plan_clip`, the picture fall-backs and natural sound use it. Voice, narrator, music and the character reference sheet use the **whole video's** quality (`estimate.voice_entry`, `sheet_image`), and a speaker who is already cast keeps the voice service that cast them. `Service.mode_costs` prices each quality on a copy.
- **Joins** (`models.Continuity`, `brain.PlannedContinuity`): decided at outline time (draft, break-down, split) as `continues | same_scene | cut` with a reason, then stored on the later clip. `Service._apply_joins` turns them into links, `_sync_states` copies end state to start state for a continuing clip (and marks made clips out of date), `_repair_joins` turns a join that lost its previous clip into a cut, `set_join` is what the marker in the story tree calls. A join left blank (a project from before) is never invented: the links between clips still say it.
- **The hand-over rule** (`estimate._video_that_starts_from_picture`, `placeholder_before`): a clip that continues another **needs** a video model that can start from a picture. The part's quality still ranks the models that can; a note says when that changed the model the quality would have picked. With none connected, or with a pinned model that cannot, `ClipPlan.blocked` (and `Node.blocked`) say so, `Engine.start` refuses the run, and `_make_clip` refuses the clip. A talking-picture clip, whose speaker picture is the last picture of the clip before, is held the same way when the clip before is only a placeholder.
- **Measured joins** (`media.frame_difference`, `Engine._check_joins`, `estimate.join_miss`): both pictures are shrunk to 32x32 grey and compared pixel by pixel; the result is stored in `Continuity.difference` and judged live against `policy.join_max_difference`, so changing the limit changes the flag at once. It runs when either clip finishes. Placeholders are never compared.
- **Characters in sync** (`ActorDetails.language`, `voice_accent_label`, `casting.accent_mismatch`): the draft prompt requires an accent for every speaker, decided from who the character is. `policy.voice_accent_weight` makes it count strongly in `ElevenLabsVoice.candidates`. `routes.describe` tells the planner, from the catalogue's `sing` capability, that no connected voice can sing.
- **Continuity check** (`continuity.py`): plain rules, listed in the summary (`summary.continuity`), the next-step guide and the Continuity bar; `Service.fix_continuity` runs the mechanical fixes (`copy_start`, `set_join`, `joins_as_cuts`). `continuity.reuses` lists what a set of clips takes from the rest of the video (shown in the confirm dialog). Writing systems per language are data in `data/language_scripts.yaml`.
- **Not testable here:** how a real video model honours a start picture, real accents and Hindi voice quality, and real prices. Tests use pretend vendors; check these on your machine and tune `join_max_difference` with `vg policy`.
