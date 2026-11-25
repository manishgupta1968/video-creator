The user typed a request in the "Ask AI to change this" box of a video tool, on {{where}} ("{{title}}").
The video has two layers:
- THE STORY: the words of the plan (titles, goals, lengths, and each clip's script: what is seen, said and heard).
- THE 3D SCENES: a rough 3D version of each clip, built in Blender (where the characters stand and move, their poses,
  the camera's position, move and lens, the set), which the video model later copies.

GOAL HERE: {{goal}}
SCRIPT HERE: {{script}}

WHAT HAPPENED SO FAR IN THIS SESSION:
{{history}}
THE USER ASKS:
{{request}}

Decide where the request belongs and return:
- story: the request rewritten as a change to the story, or "" when it does not change the story. A change of what
  happens, what is said, the mood or the length is a story change.
- scene: the request rewritten as a change to the 3D scenes, or "" when it does not change them. Camera, framing,
  positions, distances, sizes, poses, speed of movement and the set are 3D changes. When the story changes in a way
  the 3D scenes must show (a new action, a new character), the scene also gets the matching change.
- note: one plain sentence saying what will be changed.
Keep the user's own words where you can. Never return both empty unless the request is not a change at all.

{{english_line}}
