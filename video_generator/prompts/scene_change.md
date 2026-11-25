Change the rough 3D plan of ONE shot of a video exactly as the user asks. It is built in Blender from plain coloured
shapes; the video model later copies its camera path, framing, timing and where each figure moves.

CLIP {{number}}: {{title}}
GOAL: {{goal}}
CAMERA IN THE SCRIPT: {{camera}}

THE CURRENT PLAN:
{{plan}}

WHAT HAPPENED SO FAR IN THIS SESSION (keep everything the user asked for before; never undo it):
{{history}}
THE USER ASKS:
{{request}}

Rules:
- Do what the user asks, and change NOTHING else. Return the whole plan, with the change made.
- Units are metres and seconds. Z is up, the floor is Z = 0, the set is centred on X = 0, Y = 0.
- Keep seconds, fps and aspect. Keep every shape's id. Keep labels, colours and actor_id unless the user asks to change them.
- "Bigger" or "smaller" changes the size (and keeps the shape standing on the floor). "Closer" moves the camera towards
  what it looks at. "Slower" or "faster" changes how far things move between keys, not the length of the shot.
- A new character is a `figure` with its own colour from: red, blue, green, yellow, purple, orange, cyan, pink.
  New scenery is a `prop`.
- The camera must never be inside a shape. Every character must stay in the frame unless the user asks otherwise.
- Update camera.move to describe the camera in one plain sentence if the change affects it.

{{english_line}}
