Split ONE clip of a video into consecutive clips, so that every clip needs only what ONE route can do.

WHOLE VIDEO OUTLINE:
{{outline}}

CLIP {{number}}: {{title}}
GOAL: {{goal}}
LENGTH: {{seconds}} seconds in total (keep the total, unless a clip is exactly as long as its speech)

CURRENT SCRIPT OF THIS CLIP:
{{script}}

ACTORS:
{{actors}}

{{routes}}

Return 2 to 4 parts in story order. For every part:
- title, goal, seconds
- shot_type: one of {{shot_types}}
- motion: face | body | scene (what must move in THIS part)
- visual, action_beats, dialogue (speaker_name, text, and for each line keep its `language` and `translation` as they are), narration, sound_notes
- start_state and end_state (pose, place, time of day, framing, light). The end state of a part MUST equal the start state of the next part; the first part starts as the original clip starts and the last part ends as the original clip ends.
Keep every spoken line, exactly as written, in the part where it belongs, and keep its `fixed` mark. A part with speech to camera and only face and head movement should be about as long as the speech plus one second.


{{english_line}}
