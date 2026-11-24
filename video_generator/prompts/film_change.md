The user wants to change the rough 3D preview of a WHOLE video, which is made of the clips below (each clip has its own
3D scene, built in Blender from plain shapes and low-poly models; a video model later copies its camera and movement).
Decide what this one request means for each clip and each 3D model.

THE CLIPS, in story order:
{{clips}}

THE 3D MODELS of characters and objects:
{{models}}

THE USER ASKS:
{{request}}

Return:
- clips: one entry for EVERY clip the request affects, and none for the others. `number` is the clip's number exactly
  as above. `request` is the change for THAT clip, written as a short instruction for its 3D scene ("move the camera
  lower, at the guru's eye level"). When the request is about the whole film ("the camera lower everywhere"), every
  clip with a 3D scene gets an entry.
- models: one entry for each 3D model whose LOOK or BODY must change ("give the guru a long white beard"). `name` is
  the model's name exactly as above. Leave it empty when no model changes.
- note: one plain sentence saying what will be changed.

{{english_line}}
