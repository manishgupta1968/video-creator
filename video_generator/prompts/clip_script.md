Write the detailed production script for ONE clip.

WHOLE VIDEO OUTLINE:
{{outline}}

CLIP {{number}}: {{title}}
CLIP GOAL: {{goal}}
PARENT GOALS: {{parents}}
LENGTH: this clip is exactly {{seconds}} seconds. Use at most {{max_beats}} action steps (about one per 2.5 seconds) and keep any dialogue short enough to say in that time (about 2.5 spoken words per second).
STYLE: {{style}}
LANGUAGE: {{language_line}}
PREVIOUS CLIP: {{previous}}

STORY SO FAR (what the earlier clips established; stay consistent with it):
{{so_far}}

PLANNED CONTINUITY (decided by the plan before any script was written; keep it exactly):
{{contract}}

CONTEXT THAT APPLIES TO THIS CLIP:
{{context}}

ACTORS AVAILABLE:
{{actors}}

CURRENT SCRIPT (revise it if present):
{{current}}

FEEDBACK TO APPLY (user feedback wins over AI suggestions):
{{feedback}}

{{routes}}

Fields:
- shot_type: one of {{shot_types}} (talking_head = a person presenting to camera)
- visual: one rich paragraph describing exactly what we see (subject, setting, lighting, lens/feel). Restate actor appearance and clothing.
- action_beats: 1 to {{max_beats}} short actions in order (never more than {{max_beats}})
- camera: framing and movement
- actors_in_shot: actor_name plus clothing/behaviour for this clip
- dialogue: lines spoken (speaker_name = actor name or "narrator"); keep to the target length. Set `fixed` to true on a line that must be spoken exactly as written: text the user gave in the goal or context (a quote, a slogan, a name), or a line already marked fixed in the CURRENT SCRIPT. A fixed line is never shortened, reworded or dropped. `language` (a short code) only when this line is in a different language from the speaker's, as the LANGUAGE line allows. `translation` = the meaning in plain English, for every line that is not in English.
- narration: voice-over text if any, in the language the LANGUAGE line gives. Set `narration_fixed` to true under the same rule. `narration_language` only when it differs from the video's main spoken language; `narration_translation` = its meaning in plain English when it is not English.
- on_camera_speech: true only if a visible person speaks on camera
- sound_notes: the sound design for this clip, always filled: the ambience of the place (for example wind and birds outdoors, room tone indoors, street or crowd), effects tied to the action (footsteps, a door, pouring water), or the single word "silence" when silence is the right choice. Do not describe music here.
- motion: face | body | scene: what must move in this clip (see HOW TO PLAN above). If the clip would need more than one route can do, keep only the part that one route can do and say in change_summary what should become its own clip.
- start_state: how the clip begins, in one sentence: where the subject is and what they are doing (pose), the place, time of day, framing, clothing, light. If PLANNED CONTINUITY gives a start state, use it word for word.
- end_state: how the clip ends, in one sentence, in the same terms. The next clip that continues from this one starts exactly here, so plan the end deliberately. If PLANNED CONTINUITY gives an end state, use it word for word (example only: "the subject has stopped moving, faces the camera, arms relaxed").
- negative: things to avoid (e.g. "extra fingers, warped face, text artifacts")
- continues_from_previous: true if the JOIN in PLANNED CONTINUITY is continues (the plan decided it; do not guess)
- same_location_as_previous: true if the JOIN in PLANNED CONTINUITY is same_scene
- change_summary: one line on what you changed (if revising)
