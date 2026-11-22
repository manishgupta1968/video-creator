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
| 12 | Review: "Did it follow the camera?" | Review Agent | phase 5 |
| 13 | Pick takes, join with music | as today | exists |

## Phases
1. **Reference video support (done).**
   - `VideoRequest` has `reference_video` and `reference_labels`.
   - The fal plugin sends reference pictures and videos as lists, and starts the prompt with a guide to what each
     reference is: "[Video1] is the camera and movement reference … Do not copy its look. [Image1] is Dan."
   - Catalogue rows `seedance_2_reference` and `seedance_2_fast_reference`. They carry
     `requires: [reference_video]`, so they are never chosen for an ordinary clip.
   - **To verify:** the field names and limits came from fal's listing as shown in search results (the page could not
     be opened from the build machine). Check https://fal.ai/models/bytedance/seedance-2.0/reference-to-video/api
     before a big project.
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
5. **Screens and numbers.** A switch per video and per part, the 3D preview panel with the check pictures, the
   cost and time of the 3D step in the estimates, and the new review check.

## Render engines
- **Workbench** is fast. On Linux it needs the `libegl1` and `libgl1-mesa-dri` packages, and then works even with
  no graphics card. Measured on the build machine: a 4-second 640×360 clip took 35 s.
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
