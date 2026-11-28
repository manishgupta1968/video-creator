A video is planned as the clips below. In the tool, every character, place and object the clips need should be
defined once (with a description and a picture), so that it looks the same in every clip. Find what is still missing.

THE VIDEO: {{goal}}

THE PLAN (the whole video and every part, with their prompts):
{{outline}}

THE CLIPS (script, actors, and their 3D scene: the set's name and what is in it):
{{clips}}

PICTURES: {{pictures}}

WHAT THE USER ASKED FOR SO FAR:
{{history}}

ALREADY DEFINED:
{{have}}

Return items: one for each character (type actor), place (type location) or object (type object) that the clips need
but that is NOT already defined (a different name for something already defined is not missing), and one for each
defined item marked NO DESCRIPTION YET (same type and title, with a full description).
- A place: where the clips happen (for example "village courtyard under a banyan tree, mud houses"). There must be a
  defined place for every distinct place or 3D set in the clips: if none is defined, ALWAYS return one, built from the
  prompts, the scripts, the set names and the pictures.
- An object: only things that matter to the story or that someone uses (a mat, a seat, a staff) — not every pebble.
- A character: anyone who is seen. kind is ai_person for a person, animal for an animal, product for a product.
- title: a short name. description: how it looks, in one or two concrete sentences that fit the story and the other
  items (age, clothes, colours, materials, size; for a place: buildings, plants, ground, light, time of day).
- clips: the clip numbers it appears in. why: one short sentence.
- note: one plain sentence (for example "The place and the takht were missing.").
Return an empty list when nothing is missing.

{{english_line}}
