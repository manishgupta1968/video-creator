Write the detailed production script for ONE clip.

WHOLE VIDEO OUTLINE:
{{outline}}

CLIP {{number}}: {{title}}
CLIP GOAL: {{goal}}
PARENT GOALS: {{parents}}
LENGTH: this clip is exactly {{seconds}} seconds. Use at most {{max_beats}} action steps (about one per 2.5 seconds) and keep any dialogue short enough to say in that time (about 2.5 spoken words per second).
STYLE: {{style}}
PREVIOUS CLIP: {{previous}}

CONTEXT THAT APPLIES TO THIS CLIP:
{{context}}

ACTORS AVAILABLE:
{{actors}}

CURRENT SCRIPT (revise it if present):
{{current}}

FEEDBACK TO APPLY (user feedback wins over AI suggestions):
{{feedback}}

Fields:
- shot_type: one of {{shot_types}} (talking_head = a person presenting to camera)
- visual: one rich paragraph describing exactly what we see (subject, setting, lighting, lens/feel). Restate actor appearance and clothing.
- action_beats: 1 to {{max_beats}} short actions in order (never more than {{max_beats}})
- camera: framing and movement
- actors_in_shot: actor_name plus clothing/behaviour for this clip
- dialogue: lines spoken (speaker_name = actor name or "narrator"); keep to the target length
- narration: voice-over text if any
- on_camera_speech: true only if a visible person speaks on camera
- sound_notes: ambience / sound effects
- negative: things to avoid (e.g. "extra fingers, warped face, text artifacts")
- continues_from_previous: true if this clip must start exactly where the previous clip ended
- same_location_as_previous: true if it is the same place as the previous clip
- change_summary: one line on what you changed (if revising)
