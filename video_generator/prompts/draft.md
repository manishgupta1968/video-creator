Create a complete first plan for this video.

GOAL: {{goal}}
{{length_block}}
ASPECT RATIO: {{aspect}}
{{language_block}}

CONTEXT GIVEN BY THE USER (shared by all clips):
{{context}}

Return:
- title: short project title
- language: the language the people in this video speak, as a short code (for example en or hi), following the LANGUAGE line above
- style: look, colour, mood that fit the goal
- actors: every recurring person/animal/product character (reuse names from the context if present). For each: kind, appearance description, default clothing, behaviour (mannerisms, how they move and speak), voice description.
  For EVERY character that speaks (people of any age, animals, mascots, robots) and for a narrator (add an actor named "Narrator" when there is voice-over), also decide the voice profile: voice_gender (male | female | neutral), voice_age (child | teen | young | adult | older), voice_pitch (low | medium | high), voice_pace (slow | normal | fast), voice_accent (for example "Indian English"; leave empty to use the video's language). Choose what fits the story: (examples only) a gruff, slow, low male voice for an old sea captain; a bright young female voice for a student; a calm elderly voice for a teacher. Speakers in the same video must sound clearly different from each other. Also give `speaking_wpm`: the words per minute this speaker really speaks (normal speech is about 150; slow, drawn-out or chanted delivery is far fewer, for example 40 to 90). Leave it empty for normal speech. It is how the length of the speech is worked out.
- music_advice: one line deciding the music for the whole video: "none", "subtle" or "full", then mood and genre and where it should come in and go out (for example "subtle: warm acoustic guitar, in at the start, out under the final line"). Choose none when speech or natural sound carries the scene.
- parts: 2–6 story parts that together meet the goal, each with title, goal (one sentence), seconds; and inside each part 1–5 clips (title, goal, seconds). Clip seconds should be 3–12 and add up to the part; parts add up to the video's length.

{{routes}}

Length rules: {{length_rules}} Keep dialogue short enough for its clip (about 2.5 spoken words per second; slow or drawn-out delivery needs fewer words per second). A very short goal needs only 1–3 clips.
