The current plan of this video is NOT enough for what the person wants: it is too long and/or too expensive. Re-plan it. First change the Goal as little as possible so that it supports the saving, then plan the parts and clips again so that they follow the Goal.

SCOPE: {{scope}}

CURRENT MAIN GOAL:
{{goal}}
{{part_goal}}

WHAT THE PERSON WANTS: {{wish}}
WHERE THE CURRENT PLAN STANDS: {{situation}}

THE CURRENT PLAN, numbered, with seconds, estimated cost and how each clip joins the clip before it. Marks: MADE = a video already exists; KEPT = the person keeps this clip exactly as it is; EXACT = it holds a line that must be said exactly.
{{outline}}

WHAT THE PERSON SAID ABOUT CUTTING (their answers always win):
{{answers}}

{{routes}}

HOW TO RE-PLAN
- The Goal: return the WHOLE main Goal with the SMALLEST change that supports the saving: a few words or one short clause (for example the number of scenes, or a detail to drop). Do NOT make it longer than needed, do NOT repeat the plan inside it, and keep every piece of quoted text exactly as it is. Return "" if no change is needed.
- Parts and clips: plan them again so that they meet the wish. Every clip needs title, goal, seconds (3 to 12) and the continuity fields (join, join_reason, place, present, start_state, end_state, carry_over); a clip that continues the one before it starts exactly where that one ends.
- Keep what exists: when a clip stays exactly as it is, set `reuse` to its number and copy its title, goal, seconds and continuity. When a part stays (its goal may be reworded a little), set `keep` to its number. A MADE or KEPT clip stays unless the person said it may be cut; if you must drop one, say why in `note`. A clip that is EXACT is never dropped.
- Cut ideas, not quality: drop or merge ideas the story can do without, shorten the rest; never change a character's voice, accent, language, clothing or place.
- The seconds of all clips must add up to the length the person wants (if they gave one).
- If you cannot decide what to cut, return `questions` (each with 2 to 4 short options and an id) and NO parts; the person answers and you are asked again.
- For a single part, return that part only (one entry in `parts`, with `keep` set), and `part_goal` with the smallest change to that part's Goal; `goal` is then the main Goal with at most one short clause added about this part.
