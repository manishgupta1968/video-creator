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
| 8 | Automatic check-and-fix rounds (up to `max_fix_rounds`) with Claude Code / Codex | agent | phase 4 |
| 9 | You approve the 3D preview, or auto-approve does it | You / setting | done (`vg scene3d approve`) |
| 10 | Turn the first frame into a realistic start picture with the character and location pictures | image model | phase 3 |
| 11 | Make the video from the reference, the pictures and the prompt | video model (reference-to-video) | phase 3 |
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
3. **Use the reference when a clip is made.** In `runner._make_takes`: when a clip has an approved, up-to-date
   reference, make the realistic start picture from its first frame, then call a reference-to-video model with the
   reference, the pictures (labelled, with the colour legend) and the prompt. Otherwise nothing changes.
4. **The agent (Claude Code / Codex / pair).** A `scene_agent` plugin kind, run through the command-line tools
   (`claude -p …`, `codex exec …`) in a locked folder, allowed only to edit the plan and run Blender. Used when a check
   fails, or when a shape needs more than the fixed builder makes.
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
`vg scene3d on --auto-approve` approves a passing preview by itself. `--agent codex` or `--agent pair` changes the
agent. `--renderer sketch` never uses Blender.
