Create a complete first plan for this video.

GOAL: {{goal}}
{{length_block}}
ASPECT RATIO: {{aspect}}
{{language_block}}

CONTEXT GIVEN BY THE USER (shared by all clips):
{{context}}

Return:
- title: short project title
- language: the main language of the SPOKEN words, as a short code (for example en or hi), following the LANGUAGE line above. The title, goals, descriptions, notes and every other word you write are English.
- style: look, colour, mood that fit the goal
- actors: every recurring person/animal/product character (reuse names from the context if present). For each: kind, appearance description, default clothing, behaviour (mannerisms, how they move and speak), voice description.
  For EVERY character that speaks (people of any age, animals, mascots, robots) and for a narrator (add an actor named "Narrator" when there is voice-over), also decide the voice profile: voice_gender (male | female | neutral), voice_age (child | teen | young | adult | older), voice_pitch (low | medium | high), voice_pace (slow | normal | fast), voice_accent, and `language` (the language this character speaks, a short code; the video's main spoken language unless the story says otherwise or the LANGUAGE line names other languages for other characters). voice_accent is REQUIRED for every speaker and is never empty: decide it from who the character is (where they are from and where they live), so the same person always sounds like that person in every part of the video. (Example only: a character from India speaking English has an Indian English accent; a character from Britain has a British accent.) Choose what fits the story: (examples only) a gruff, slow, low male voice for an old sea captain; a bright young female voice for a student; a calm elderly voice for a teacher. Speakers in the same video must sound clearly different from each other. Also give `speaking_wpm`: the words per minute this speaker really speaks (normal speech is about 150; slow, drawn-out or chanted delivery is far fewer, for example 40 to 90). Leave it empty for normal speech. It is how the length of the speech is worked out.
- music_advice: one line deciding the music for the whole video: "none", "subtle" or "full", then mood and genre and where it should come in and go out (for example "subtle: warm acoustic guitar, in at the start, out under the final line"). Choose none when speech or natural sound carries the scene.
- parts: 2–6 story parts that together meet the goal, each with title, goal (one sentence), seconds; and inside each part 1–5 clips (title, goal, seconds and the continuity fields below). Clip seconds should be 3–12 and add up to the part; parts add up to the video's length.

CONTINUITY: decide it now, for every clip, before any script is written. Give each clip these fields:
- join: how this clip joins the clip BEFORE it in story order, also across parts. "continues" = it begins on the very last picture of the clip before (the same place, people, pose, light and framing: one unbroken shot goes on). "same_scene" = the same place and people, but a new angle or a later moment. "cut" = a new place or a jump in time. Leave it empty only for the very first clip of the video. Choose "continues" only when the story really is one unbroken shot. join_reason: one short line saying why.
- place: where and when the clip happens (place, time of day, light, weather).
- present: the names of the characters who are in it.
- start_state and end_state: one sentence each: where the subject is and what they are doing, the framing, the light. For a clip whose join is "continues", start_state MUST be exactly the end_state of the clip before it.
- carry_over: what must stay exactly as it was in the clip before (clothing, props, sound)

{{routes}}

Length rules: {{length_rules}} Keep dialogue short enough for its clip (about 2.5 spoken words per second; slow or drawn-out delivery needs fewer words per second). A very short goal needs only 1–3 clips.
