Plan a ROUGH 3D version of ONE clip of a video. It is built in Blender from plain coloured shapes and rendered as a
reference video. The video model copies only its CAMERA PATH, FRAMING, TIMING and WHERE EACH FIGURE MOVES; the looks
come from the character and location pictures. So the shapes stay simple, but sizes, positions and the camera must be right.

WHOLE VIDEO OUTLINE:
{{outline}}

CLIP {{number}}: {{title}}
GOAL: {{goal}}
LENGTH: exactly {{seconds}} seconds
FRAME SHAPE: {{aspect}}

SCRIPT OF THIS CLIP:
{{script}}

CHARACTERS AND THINGS (use these ids in actor_id):
{{actors}}

THE PLACE AND THE OBJECTS THE USER DEFINED (build the place's big features — trees, huts, walls, a river — as props
placed around and behind the action, at real size, leaving the action room; put each object that must be seen as a
prop where the script uses it; their looks come from their pictures later, so plain shapes are enough):
{{places}}

THE SET THIS CLIP SHARES WITH OTHER CLIPS (reuse its set_id and size when this clip happens in the same place):
{{shared_set}}

WHAT THE USER WANTS IN THIS 3D SCENE (their own words; follow them wherever they do not contradict the rules below):
{{wishes}}

3D MODELS OF THE CHARACTERS (their real size, and every pose each one knows, with its height in that pose):
{{models}}

HOW THE CLIP BEFORE ENDED (for a clip that continues it, start the camera and every shared figure exactly there):
{{previous}}

Rules:
- Units are metres and seconds. Z is up, the floor is Z = 0, the set is centred on X = 0, Y = 0.
  Example: a set 20 m long (X) and 12 m wide (Y) runs from X = -10 to 10 and from Y = -6 to 6.
- Real sizes: an adult is about 1.7-1.8 m tall and 0.5 m wide. If the story makes someone tiny or giant, scale the
  OTHER things, not the person (a lizard that dwarfs two people might be 8 m long and 4 m high).
- Make the set big enough for the action (a chase needs room to run), and empty: only the large things that the
  action needs (a rock to hide behind). Small details (plants, clutter) are added later by the video model.
- things: every character in the shot is a `figure` (shape person | creature | box | sphere | cylinder), each with
  its own colour from: red, blue, green, yellow, purple, orange, cyan, pink (as #rrggbb). Scenery is a `prop`.
  label = who or what it stands for, in a few words. keys = where its base is over time: {t, at:[x,y,z]}.
  Movement between keys is straight and even. Add more keys for a curve or a stop.
- Poses: a character with a 3D model takes the poses the script asks for, in order, by naming them in its keys:
  {t, at:[x,y,z], pose:"walk"}, then {t, at, pose:"kneel"}, then {t, at, pose:"touch_ground"}. Use only the poses listed
  for that character. Give each pose time (about 0.5-1 s to change pose). A pose stays until the next key names another.
- YOU DECIDE THE CAMERA, as a film director would: where it stands, how high, what it looks at, which lens, and how it
  moves, for every moment of the shot. Frame the action at each moment using the real heights above (a person who
  kneels is lower: bring the camera down and closer, look at their head and hands, not at empty air above them).
  Follow the script's camera words when it has them; when it does not, choose the camera that tells the story best.
- camera: lens_mm (24-35 wide, 50-85 close), keys = {t, at:[x,y,z], look_at:[x,y,z]}. The FIRST key is at t = 0 and
  the LAST at t = {{seconds}}. Follow the script's camera words exactly (comes down from above, pans right, tilts up,
  follows them, pushes in...). `move` = the camera move in one plain sentence.
- Every figure that matters must be in the frame at the start, middle and end, unless the script says it enters or leaves.
- The camera must never be inside a shape.
- lights: usually one sun; put it where the light comes from in the location picture (for example top left).
- set_id: a short name for the place (for example "terrarium"); the same place in another clip = the same set_id.

{{english_line}}
