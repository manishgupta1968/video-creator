The user typed a command for their video project. Turn it into precise edit operations.

OUTLINE (numbers identify nodes):
{{outline}}

ACTORS:
{{actors}}

FOCUS: {{focus}}
COMMAND: {{instruction}}

Operations (target = node number like "1.2", actor name, or "project"):
- set_title / set_goal / set_seconds (value)
- set_script (field = visual|camera|narration|negative|sound_notes, value)
- add_child (target = parent number, value = goal text)
- remove (target = node number)
- set_actor (target = actor name, field = description|clothing|behaviour|voice_description, value)
- set_style (field = look|colour|mood, value)
- regenerate_scripts (target = node number) — rewrite scripts under that node
- generate (target = node number or "next" or "all") — make clips
Return a short summary of what will change and the ops.


{{english_line}}
