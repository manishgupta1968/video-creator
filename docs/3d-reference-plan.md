# Plan: the 3D camera reference add-on

## Why
AI video models are poor at following camera moves written in words. The workflow from the "Blender for AI video"
tutorial fixes this:
1. Build a rough 3D version of each shot (plain shapes, the real camera path).
2. Render it as a reference video.
3. Give the video model that reference together with the character and location pictures.
4. The model copies the camera and the movement from the reference, and the looks from the pictures.

**Example:** "The camera comes down from above, pans to Bruiser, then tilts up to the giant lizard." This is hard to get
from a prompt. With a 3D reference, the model follows the path exactly.

The tutorial does this by hand: clicks in Blender, exports, screenshots, uploads, copied prompts. This add-on does
those steps automatically inside the tool.

## Rules
- **It only adds to the tool.** It is off by default. When it is off, the tool works exactly as it did without it.
- **It can be switched on for the whole video, or for one part.** A part's choice wins over the video's, and a clip's
  choice wins over its part's.
- **Your decisions stay with you.** You approve the plan and the cost, give consent for real people, and pick takes.
  The 3D preview waits for your approval, unless you switch on **auto-approve**. Auto-approve approves a preview by
  itself only when the automatic checks find no major problem.
- **Computer use is not used.** Everything runs through programs and APIs.

## Decisions taken
| Question | Decision |
|---|---|
| Who builds and fixes scenes that the fixed builder cannot | Claude Code by default; Codex, or the pair (one builds, the other checks), can be chosen |
| The 3D preview | Waits for you; auto-approve is available |
| Computer use | Out |
| How Blender runs | In the background from a Python script (`blender --background --python …`), never by clicking |

## How it works, step by step
| # | Step | Who does it | Status |
|---|---|---|---|
| 1 | You type the goal and switch on the 3D camera reference | You | done (`vg scene3d on`) |
| 2 | Plan, shots, dialogue, cost | the tool, as today | exists |
| 3 | You approve the plan and the cost | You, as today | exists |
| 4 | Character sheets, voices | the tool, as today | exists |
| 5 | Scene plan for each clip: shapes, colours, sizes in metres, paths, camera path, light | AI brain | done |
| 6 | Measured checks: a figure never in view, the camera inside a shape, shapes outside the set | plain Python, free | done |
| 7 | Render the reference in background Blender; the free sketch when Blender is missing or fails | Blender / sketch | done |
| 8 | Automatic check-and-fix rounds (up to `max_fix_rounds`) with Claude Code / Codex | agent | done |
| 9 | You approve the 3D preview, or auto-approve does it | You / setting | done (`vg scene3d approve`) |
| 10 | Turn the first frame into a realistic start picture with the character and location pictures | image model | done |
| 11 | Make the video from the reference, the pictures and the prompt | video model (reference-to-video) | done |
| 12 | Review: "Did it follow the camera?" | Review Agent + free measurement | done |
| 13 | Pick takes, join with music | as today | exists |

## Phases
1. **Reference video support (done).**
   - `VideoRequest` has `reference_video` and `reference_labels`.
   - The fal plugin sends reference pictures and videos as lists, and starts the prompt with a guide to what each
     reference is: "@Video1 is the camera and movement reference … Do not copy its look. @Image1 is Dan."
   - Catalogue rows `seedance_2_reference` and `seedance_2_fast_reference`. They carry
     `requires: [reference_video]`, so they are never chosen for an ordinary clip.
   - **Checked on 2026-11-23** against fal's own README and example (github.com/fal-ai/seedance-2.0-api): the fields
     `image_urls` and `video_urls`, the prompt tags `@Image1` / `@Video1`, lengths "4" to "15", and the price
     ($0.3024/s, fast $0.2419/s, and 0.6 × that when a video is given).
2. **Scene plan and background Blender (done).**
   - `video_generator/scene3d/spec.py`: the scene plan, the camera maths and the measured checks.
   - `video_generator/scene3d/blender_build.py`: the script Blender runs.
   - `video_generator/scene3d/render.py`: Blender in the background, falling back to a free sketch.
   - `video_generator/scene3d/service.py`: plan, check, build and approve one clip; the result is kept on the clip.
   - A continuing clip starts where the clip before ended (camera and figures), in the same set.
   - `vg doctor` reports Blender and which render engine can run.
3. **Use the reference when a clip is made (done).** A clip uses its reference only when the add-on is on for it, the
   preview is approved, and the reference is up to date (the plan has not changed and the clip is still the same
   length, within 0.25 s). Then:
   - **The first picture** is made from the layout: the layout's first picture goes to the picture model as picture 1,
     followed by the character and place pictures, with the words "Make a realistic, cinematic still with exactly the
     same framing … In picture 1, the red shape is Dan …".
   - **The video** is made by a reference-to-video model. It gets the reference video, the realistic first picture
     ("the first picture of the clip: it starts exactly like this"), the character pictures with labels ("Dan, the red
     shape in the camera reference"), and the colour legend in the prompt.
   - **A clip longer than the model allows** is made in parts, and each part gets its own stretch of the reference.
   - **The cost estimate** uses the reference model's price, so the numbers you approve are the numbers you pay.
   - **When it cannot be used, the clip says why and is made the usual way:**
     - No reference model is connected: the first picture still comes from the layout, so the framing matches.
     - The clip continues the one before: it must start from that clip's last picture, and no model can follow a
       reference video and start from a picture. The hand-over rule wins.
     - The speech needs a model that speaks the line itself.
   - **A clip made before its reference was approved** is marked out of date, so you can make it again.
4. **The agent: Claude Code, Codex or the pair (done).**
   - **When it runs:** only when a measured check finds a major problem, or always in pair mode (the checker looks
     at the pictures). A plan that is already rendered and unchanged is never fixed, or paid for, again.
   - **The locked work folder** (`clips/<clip>/scene3d/agent/round_N/`) holds `plan.json` (the only file the builder
     may change), `clip.json` (what the shot must show, and which colour is which character), `problems.txt`, and
     preview pictures.
   - **The free check command** the agent may run as often as it likes:
     `python -m video_generator.scene3d.check plan.json`. It lists the problems, says where each character is in the
     picture at the start, middle and end, and redraws the preview pictures. No Blender, no AI, no cost.
   - **Claude Code** runs as `claude -p … --output-format json --permission-mode acceptEdits` with only the file tools and
     that one check command allowed, web tools refused, and `--max-budget-usd` set to what is left of the clip's cap.
     It reports what it spent.
   - **Codex** runs as `codex exec --skip-git-repo-check --sandbox workspace-write --cd <folder> --json`. **To verify:**
     Codex is not installed on the build machine, so these flags come from its documentation and were tested only with
     a stand-in program. Codex does not report a price.
   - **Pair:** Claude Code fixes; Codex then looks at the preview pictures against the script and writes
     `verdict.json`. Its problems go back to Claude Code in the next round.
   - **After each round** the tool checks the plan is still valid, puts back what must not change (length, frame
     shape, the characters' ids, labels and colours, and any character the agent dropped), and measures it again.
   - **It stops** when nothing is wrong, after `max_fix_rounds` rounds, when the same problems are left twice, or when
     the money cap (`agent_max_usd`, default $2 per clip) is reached. Every cent an agent reports goes to the spending log.
   - **A missing agent** is replaced by the one that is installed, and the clip says so. With none installed, the
     problems are shown to you and nothing is changed.
   - **The whole chain** for a clip, or for every clip in story order: plan (when there is none, or the length
     changed) → fix → render → approve by itself when auto-approve is on.
5. **Screens and numbers (done).**
   - **Screens.** The whole video has a "3D camera reference" box: the on/off switch, auto-approve, who fixes (Claude
     Code / Codex / the pair), the money cap per clip, the renderer, and "Prepare all 3D references". A part chooses
     On, Off or "Same as above". A clip shows its status ("Waiting for your approval", "Approved", "Out of date: …"),
     whether the reference is used, the colour legend, the problems, the reference video and the start, middle and end
     pictures, and the buttons: Plan, check and render · Plan again · Fix with Claude Code (+ Codex check) · Approve.
     Slow jobs run in the background and the screen updates when they finish.
   - **Numbers.** A clip with the add-on on shows, in its cost breakdown: the 3D plan (AI brain), the reference render
     (free, with the time of the engine that can run on this computer), and the agent's fixes ("at most $2.00", counted
     only in the highest figure). An approved, up-to-date reference adds nothing.
   - **Review.** A clip made from a reference gets a "camera" score. The tool measures, for free, how the whole picture
     moves in the reference and in the clip (left, right, up, down) and compares the two paths: `camera_follow` from 0
     to 1. Below 0.45 is a major issue (the camera score is capped at 2, and the verdict becomes "does not meet goal");
     below 0.65 is minor. The Review Agent also sees the reference's first and last pictures. No reference means no
     camera score.
   - **Known limit of the measurement:** a camera that travels with its subject keeps the subject still in the
     picture, so such a shot reads as nearly still; a correct clip reads the same way, so the comparison stays fair.
     Pure push-ins and zooms slide very little, so for those the Review Agent's look at the pictures matters more.
   - **Reference renders** are 480p with a checker floor of two greys, so camera movement is easy to see.

## Like the video: describe it, change it in plain words, look at it in Blender
The video's way of working is prompt → look → prompt a change → look again. The add-on keeps that loop, and does
the rest by itself.

1. **Describe the scene** (optional). Before a clip has a 3D scene, its box says "Describe the 3D scene". What you
   type (for example "a big empty kitchen, the chef at the far end, the camera starts high and comes down") is
   given to the planner together with the script. Leave it empty to plan from the script alone.
2. **Change it in plain words.** Once a scene exists, the same box says "Change the 3D scene". For example: "make the
   lizard twice as big", "end the camera closer to the chef", "move the rock to the left".
   - Claude Code (or Codex) makes the change in the locked work folder, changing only what you asked, and measures
     its own work with the free check. With no agent installed, or the clip's money cap used up, the AI brain makes it.
   - Then, by itself: the checks run, the fixer repairs any major problem the change caused, and Blender renders the
     new preview. While this runs, the box says "Working on it".
   - Your changes are listed under "Your changes so far". **One Undo (Ctrl/⌘ Z) takes a whole change back**: the
     change, its check and its render are one undo step.
3. **Open in Blender** opens the clip's scene in your own Blender, looking through the camera; press Play to watch
   the shot. It is for looking: the reference is built from the tool's own scene plan, so changes saved in Blender are
   not used (the app says so). Ask for changes in the box instead. A preview drawn as a free sketch has no Blender
   file to open.

Commands: `vg scene3d change 1.1 "make the lizard twice as big"` and `vg scene3d open 1.1`.

## The 3D scene in every clip, and the whole 3D film
**Every clip uses its approved 3D scene in every way its model allows:**

| Way | What it fixes | Which clips |
|---|---|---|
| The reference video | the whole camera path and all movement | clips made by a reference-to-video model (Seedance reference) |
| The first picture, made from the layout | framing and positions at the start | every clip that does not continue the one before |
| The last picture, made from the layout | framing and positions at the end | every clip whose model takes an end picture (when no reference model is used) |
| The camera move in words, measured from the plan | e.g. "starts far above the scene, comes down to knee height, moves in from 14 m to 6 m away" | every clip |
| The speaking picture, made from the layout | the framing of a talking-to-camera clip | talking clips that do not continue the one before |

A clip that continues the one before still starts from that clip's real last picture (the smooth join wins), and now
ends on its own layout's last picture. Each clip's 3D box says how it is used ("Used when this clip is made: …").

**Generate entire video makes missing previews first.** Before anything is paid for, every clip in the run that has
the add-on on but no approved, up-to-date preview gets one (plan, check, fix, render). With auto-approve off the run
then pauses: "2 3D preview(s) wait for your approval (clip 1.1, 1.2)". Approve them (or watch the whole 3D film
first) and press Resume. A preview you were asked about and left is made the usual way on the next run.

**The whole 3D film.** "Make the whole 3D film" in the Whole video box makes every missing preview and joins them all
in story order: clips with a preview show it, your own video clips show your footage, and any other clip shows a card
of the same length saying why (for example "3D camera reference off for this clip"), so the timing is right. Watch it
in the app, or press "Open the whole film in Blender": film.blend has every clip one after another in Blender's video
editor, each with its number and title on top. It goes out of date when a clip or its preview changes.
Command: `vg scene3d film --open`.

## 3D models of the characters and objects (nothing hard-wired)
Like the video, people and things in the 3D scenes are low-poly models made for this story, not fixed shapes.

1. **Brief.** The planner reads every moment a character or object appears in the scripts and writes its brief:
   what it looks like (it fills in what the story does not say, and never contradicts it), its real size, its
   colours, its parts (face with eyes, eyebrows and beard; robe; hands …) and every pose the script needs, each with
   one sentence (walk, kneel, touch_ground, sit_cross_legged, bless …).
2. **Build.** Claude Code (or Codex) writes `model.py`, a Blender script that builds the model low-poly but
   recognisable, with bones and those poses. The only contract: `POSES = {name: {bone: [x, y, z] degrees}}` (an
   optional `"__lift__"` moves the whole body, for kneeling or sitting) and `build(name)`, which returns the root at
   the origin, on the floor, facing +X, at real size. It works in a locked folder with the brief and the character's
   pictures, and runs the free model check (`python -m video_generator.scene3d.model_check model.py`) as often as it
   likes: the check builds the model in Blender, measures it, checks every pose uses real bones, renders it from four
   sides and in every pose, and lists problems.
3. **Check.** The tool runs the same check itself. Problems go back to the agent for another round (up to
   `max_fix_rounds`). A model that passes is kept: `model.py`, `model.blend`, the pictures, its size, its poses and
   **how tall it is in each pose**.
4. **Use.** Every clip's scene builds its characters from their `model.py` and moves them through the poses its plan
   names, in order (walk → kneel → touch_ground). Built once, reused everywhere, so a character looks the same in
   every clip. A rebuilt model makes the previews (and the whole film) that use it out of date.
5. **The planner decides the camera.** It is given every model's size and its height in each pose, and places the
   camera (position, height, look-at, lens, path) to frame each moment, for example lower and closer when someone
   kneels. The "in view" check uses the pose heights too.

Models are built automatically before a clip's 3D scene is planned (switch: "Build a low-poly 3D model of each
character and object"). Each character's card has a **3D model** section: the four-side and pose pictures, Build
again, Change ("give him a longer white beard"), and Open in Blender. Without Blender or an agent, or for a model
that keeps failing, the clip uses plain shapes. Command: `vg scene3d model Guru [--change "…"] [--open]`.

**Choosing the models the tools use.** Settings → AI brain chooses the brain (Claude Code: its usual model, Opus or
Sonnet; Codex), separately for planning, the Review Agent and simple jobs, and "Type an exact model name" takes any
model name for Claude Code or Codex. The Whole video box chooses the model for the 3D work (building models, fixing
and changing scenes): Claude Code's usual model, Opus, Sonnet or Fable, and any Codex model name.

## Render engines
- **Workbench** is fast. On Linux it needs the `libegl1` and `libgl1-mesa-dri` packages, and then works even with
  no graphics card. Measured on the build machine: a 4-second 640×360 clip took 21–35 s.
- **Cycles** on the processor works on any machine, more slowly. The same clip took 82 s.
- The order is set by `blender_engines` in the settings. The next engine is tried when one fails, and the free
  sketch is used when every engine fails.

## Commands
```bash
vg scene3d on --ask-me
```
```bash
vg scene3d build 1.1
```
```bash
vg scene3d approve 1.1
```
```bash
vg scene3d show
```
Fix one clip's plan with the agent:
```bash
vg scene3d fix 1.1
```
Plan, fix and render every clip that has it switched on:
```bash
vg scene3d all
```
`vg scene3d on --auto-approve` approves a passing preview by itself. `--agent codex` or `--agent pair` changes the
agent. `--renderer sketch` never uses Blender.
