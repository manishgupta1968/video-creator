Tighten the script of part of a video so it becomes shorter and cheaper WITHOUT losing what it means.

WHOLE VIDEO OUTLINE:
{{outline}}

SCOPE: {{scope}}
GOAL OF THE PERSON: {{goal}}

THE CLIPS YOU MAY CHANGE (number, length now, join with the next clip, what is said):
{{clips}}

RULES (every one is checked by the tool afterwards; a suggestion that breaks one is thrown away):
- A line marked EXACT is never shortened, reworded or dropped. Do not touch it.
- Keep what each part is for: the part's goal must still be met, and every part keeps at least one clip.
- Do not cut more than {{max_cut}} of the words of a clip, and do not remove more than {{max_cut}} of the clips of a part.
- Never change a character's voice, accent, language, clothing or place. You only change words, or remove or merge clips.
- A merge is allowed only for two neighbouring clips whose join is "continues" or "same_scene" and which need the same kind of shot. Never merge across a "cut".
- Dropping a clip breaks any join that depended on it, so prefer shortening lines; drop a clip only when its idea is said elsewhere.

Return `edits`, each with:
- clip: the clip number exactly as shown (for example 2.1)
- action: shorten | drop | merge_with_next
- for `shorten`: `dialogue` = the new text of EVERY spoken line of that clip, in the same order and the same count (an empty text removes a line that is not EXACT), and `narration` = the new voice-over text (leave it out to keep it)
- reason: one short line saying why this change is safe
- kept: one short line saying what meaning is kept

Return at most one edit per clip. If nothing can be tightened without losing meaning, return an empty list and say why in `note`. Write in the language the lines are already in.
