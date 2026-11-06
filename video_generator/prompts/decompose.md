Break this node of the video into smaller sub-goals.

WHOLE VIDEO OUTLINE:
{{outline}}

NODE {{number}}: {{title}}
GOAL: {{goal}}
LENGTH TO FILL: about {{seconds}} seconds

CONTEXT THAT APPLIES HERE:
{{context}}

ACTORS:
{{actors}}

{{routes}}

THE CLIP BEFORE THIS NODE ENDS LIKE THIS (the first child joins it): {{prev_end}}

CONTINUITY: decide it now, for every child that is a clip, before any script is written. Give each clip these fields:
- join: how this clip joins the clip BEFORE it in story order, also across parts. "continues" = it begins on the very last picture of the clip before (the same place, people, pose, light and framing: one unbroken shot goes on). "same_scene" = the same place and people, but a new angle or a later moment. "cut" = a new place or a jump in time. Leave it empty only for the very first clip of the video. Choose "continues" only when the story really is one unbroken shot. join_reason: one short line saying why.
- place: where and when the clip happens (place, time of day, light, weather).
- present: the names of the characters who are in it.
- start_state and end_state: one sentence each: where the subject is and what they are doing, the framing, the light. For a clip whose join is "continues", start_state MUST be exactly the end_state of the clip before it.
- carry_over: what must stay exactly as it was in the clip before (clothing, props, sound)

Return 2–6 children in story order. Use kind "clip" for something filmable in one shot (4–12 s), kind "goal" for a larger idea that needs further breakdown. Seconds should add up to the length to fill.
