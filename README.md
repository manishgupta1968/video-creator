# video-generator

Turn a goal into a finished video (`.mp4` or `.mov`).

You describe what you want. The tool:
1. makes a complete draft plan, with parts, clips, scripts, actors, and the length, cost and time of each;
2. lets you edit everything (or ask the AI to change it in plain words);
3. calls the best AI tools you have connected to make the clips, voices and music;
4. lets you watch the takes, read the Review Agent's suggestions and pick the best take;
5. joins everything into one video.

Example goals:
- "A 2-minute video that shows a lion being chased by a deer with long horns"
- "A 30-second advert for our travel bag, presented by me"

You stay in control at every step. **Nothing is paid for until you see the cost and press Generate.**

---

## 1. Install on your laptop

You need three things:

| What | Why | How to get it |
|---|---|---|
| Python 3.10 or newer | runs the tool | https://www.python.org/downloads/ |
| ffmpeg | cuts, joins and mixes video | macOS: `brew install ffmpeg` · Windows: `winget install ffmpeg` · Linux: `sudo apt install ffmpeg` |
| This folder | the tool itself | `git clone` this repository |

Optional:
- LibreOffice, only if you want to use PowerPoint/Keynote files directly. (A PDF of your slides works without it.)
- Node.js, only if you want to change the GUI code.

Then, inside this folder:

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

On Windows, use this instead of `source`:

```bash
.venv\Scripts\activate
```

```bash
pip install -e .
```

## 2. Start it

```bash
vg gui
```

Your browser opens at http://127.0.0.1:8765.

**It works straight away, for free, with no accounts.** Without any keys, it uses:
- a simple offline "brain";
- storyboard-card previews with gentle motion;
- your computer's own voice.

This is useful for trying the whole flow: goal → plan → clips → final video.

## 3. Connect the AI services you want (pay-as-you-go)

Open **Settings → Vendors & keys** in the app. Each vendor has a *Sign up / billing* link and a *Prices* link. Paste the key and press **Save**. Keys are stored only on your computer, in `~/.video-generator/.env`.

**Recommended starter set (3–4 accounts):**

| Vendor | What it does here | Sign up |
|---|---|---|
| Anthropic **or** OpenAI | the AI brain: plans, scripts, reviews | https://console.anthropic.com · https://platform.openai.com |
| fal.ai | one key for many video models (Kling, Seedance, Wan), images (Flux), avatars (VEED Fabric, Kling Avatar), lip-sync, music | https://fal.ai/dashboard |
| ElevenLabs | voices, cloning your voice, music | https://elevenlabs.io/app |
| Google Gemini API (optional) | Veo 3.1 (people speaking in scenes), Nano Banana images | https://aistudio.google.com |

Add these only if you need them:
- HeyGen, for a digital twin of yourself;
- Runway, Luma, Kling (direct), Cartesia, Replicate.

`vg vendors` prints the full list with links.

> Prices and model names change often. The tool keeps them in an editable **model catalogue** (Settings → Model catalogue). Each price has the date it was last checked. Check a vendor's pricing page before a big project.

## 4. How you use it (GUI)

1. **Type your goal** on the start page and press Enter. You may drop photos, slides, clips or a voice recording on the box.
   - If the goal says "30-second" or "2 minute", the length is set for you.
   - **Length is "Auto" until you choose one.** Auto means: as short as the story allows, every spoken line heard in full, no filler. Press 15 s, 30 s, 1 min … to ask for a length instead.
   - Under the box you also choose the **spoken language** (or let the plan decide from your goal), any **also spoken** languages for a mixed-language video, what the **subtitles show**, and the **budget**. A line below shows a **rough price** from your catalogue prices, before any plan exists.
2. **Edit the draft.** The workspace has five areas:
   - **Left – Story:** the goal tree. Parts contain sub-parts, which contain clips. Drag to reorder. Use ••• → *Break down with AI*.
   - **Middle – Editor:** click any text to change it; it saves by itself. Or type in *Ask AI*, e.g. "make Rahul look more frustrated".
   - **Right – Context:** photos, voices, logos, sounds and notes. They can be **shared by all clips**, belong to **one part and everything below it**, or belong to **this clip only**. Inherited items can be switched off for one clip.
   - **Right – Cost & time:** the full breakdown, plus *What if…* options (change the model, takes or resolution and see the new cost at once).
   - **Bottom:** the timeline and run buttons.
3. **Actors** can be:
   - only a text description (age, look, clothing, behaviour, voice description); or
   - face photos and/or a voice recording.

   For real people, you confirm consent once: "This is me" or "I have permission".
4. **Links between clips.** The tool finds them and handles them for you.
   - Example: "clip 2.2 *continues from* 2.1" means 2.2 starts on 2.1's last frame.
   - See them under *Links*, or in the graph (branch icon at the top).
5. **Generate.** Every button first shows **cost, time and budget**.
   - **Generate entire video**: makes all clips, then stitches the video.
   - **Generate next**: makes one clip at a time.
   - **Continue to end**: after some one-by-one clips, finishes the rest.
   - **Pause / Resume / Stop** at any time. Finished clips are kept.
6. **Pick takes and use the Review Agent.**
   - Shots with people get 2–3 takes. You pick one (or switch on *Auto-pick*).
   - The Review Agent scores each take: goal, script, actors, realism, timing, lip-sync. It suggests fixes, but **only suggests**.
   - Tick the suggestions you like, add your own feedback (yours wins), and press **Re-make with feedback**. You see the before/after script and the new cost before anything runs.
   - Older versions are kept under *Versions*.
7. **Download** the final video (top right). Subtitles (`final.srt`) are made too.
   - **Any clip or part can be downloaded** once its clips are made: the *Download part* button in the part, *Download clip* in the clip, or ••• → *Download* in the story. A part is its clips joined with their transitions, with the same music as the final video, and a subtitle file.

**The numbers you look at first** are always at the top: **Length**, **Cost of the whole video**, **Time to make**, **Quality** and **Budget**. After each edit a small chip shows what changed ("Cost +$1.02"). Click the cost to see the **cost of every part and clip**, with its length, time, quality and model.

Keyboard shortcuts:
- **Ctrl/⌘ K**: ask AI for any change
- **Ctrl/⌘ Z**: undo
- **Ctrl/⌘ Shift Z**: redo

### Things worth knowing

**Quality choices.** *Best* = highest quality. *Balanced* = quality for the money. *Budget* = the cheapest **real** model that is good enough for the shot. *Free preview* = free local tools only (text cards). Free tools are never chosen in the other modes unless nothing real is connected.

**Why a clip is only a placeholder.** The banner says the real reason: a clip **you pinned to the free model** (its Model box), a **missing key**, **Free preview** quality, or no connected model that fits the clip. A pinned clip is never blamed on a missing key. *Use the best model* clears the pins in one click; clips that were already made as placeholders are then marked out of date so you can make them for real.

**Every model is listed.** In Settings → *AI brain* each kind of work (planning and scripts, the Review Agent, simple jobs) has a dropdown of every brain model with its price per 1 million tokens and about what one plan draft costs. In a clip's *Model* box every video model is listed, with what is missing for the ones that are not connected. *Refresh from vendor* asks each connected AI vendor which models your key can use (free); a model that is not in your catalogue yet can be added with the price you read on the vendor's page. Every AI call is priced by the model that really answered.

**Background music is made once.** The first time it is needed, one track is made for the whole video and saved (`output/music.mp3` and `music.json`). Joining again, and every part you download, reuse it for free. New music is made only if the music mood or example changed, or the video became much longer than the track (`music_reuse_tolerance` in `vg policy`). Before it spends, the *Join* button and *Download part* tell you what the music would cost.

**Make it shorter and cheaper (Optimize).** Press *Optimize the video…* under the numbers strip, or *Optimize this part…* in a part's header. It works in three steps and changes nothing until the last one. (1) *Goal*: "as short and cheap as possible, without losing quality", or a number for the length and/or for what is still to spend. (2) *Proposal*: Before and After for length, cost and making time; a ladder of levels, each with its own tick boxes, what it saves and what you would lose; and "Joins kept: 5 of 5". It stops at the first level that gets you to your number and says so; if the number cannot be reached it says why and what would be needed. (3) *Apply* the ticked changes as ONE change: one Undo (Ctrl/⌘ Z) takes it all back, and the lengths at the top follow what you chose.
- **Level 1, no visible change:** each clip is cut to what its words and action need (no empty time). Every word and action step stays.
- **Level 2, small change:** one step cheaper quality for the scope (never a model that is weak for that kind of shot), one take fewer for people clips, action at the fastest honest pace.
- **Level 3, noticeable:** natural sound off, the Review Agent off, and (whole video only) music off. Music is one track for the whole video, so a single part cannot switch it off; every second removed also lowers the music cost, and a track already made is reused at no cost.
- **Level 4, script change (AI):** shorter lines, or clips dropped or merged. You press *Ask AI to tighten the script*; the cost is shown on the button first (it uses the cheaper AI for simple jobs, see Settings → AI brain). The tool checks every suggestion before you see it: a line marked *exact* is never changed, no more than `max_cut_ratio` of a clip's words or of a part's clips may go, every part keeps a clip, and a merge is allowed only inside one scene. Each suggestion shows the reason and what meaning is kept; you tick what you want.
- **Level 5, re-plan from a leaner Goal (AI):** when the gentle levels cannot reach your goal (or you tick *Also be ready to rewrite the Goal and re-plan* in step 1), the AI can reword the main Goal **as little as it can** (a few words, never a longer text, your quoted words kept exactly) and plan the parts again. It is shown the **current breakdown** (marked MADE, KEPT, EXACT, with seconds and cost), the numbers (now 72 s and $38; wanted 40 s and $15; what the gentle levels reach) and what you said may be cut, so it knows the current plan is not enough. For the whole video every part is re-planned; for one part, that part's own Goal gets the smallest change and the main Goal one short matching clause. You then see the **old and new Goal** (word by word, in a box you can edit), the **new plan beside the current one** with Before and After, and your videos (below). The new clips have no script yet, so their numbers are a range; their scripts are written afterwards with the usual *Write the scripts* step, cost shown first. Apply is one change, refused while clips are being made or when the project changed since the proposal. The saved background music is re-linked to the new wording, so a small Goal change never makes you buy the music again.
- **What may be cut?** When the goal cannot be reached, the dialog shows every part and clip with what dropping it would save, and for each: *Must stay*, *May shorten* (the usual) or *May cut*. Your answers go to the rules, to the AI tightening and to the re-plan. A clip that holds an exact line, a clip you keep, and your own slides or footage always stay; a part keeps at least one clip; a made clip may be cut (its video stays on disk, Undo brings it back). The planner can also ask you a question when it truly cannot choose; the cost is shown before it is asked again.
- **Your videos in a re-plan:** a clip the planner keeps exactly as it is comes back with its takes and its video (untick to make a new one). A made clip that is not in the new plan is left out, its video stays on disk, and you can tick it to keep it in its part. Nothing is deleted; Undo brings everything back.
- **Never touched:** clips already made, clips marked *Keep as it is*, clips you protect in step 1, and lines marked *exact*.
- **Joins:** resizing never changes a join. Dropping a clip turns the join after it into a cut; merging two clips keeps the first start and the last end and the join to the next clip. Every proposal shows which joins survive.
- In the terminal: `vg optimize --length 50` (or `--cost 10`, or `--lowest`; add `--scope 2` for one part, `--ai` to ask the AI after seeing its cost, `--apply` to apply). Without `--apply` it only shows the proposal.

**The Review Agent also judges the stitch.** For every take of a clip that has a clip before it, the Review Agent is shown the last picture of the clip before and the first picture of the take, what the plan says about the join (*continues*, *same scene* or *cut*), the planned transition, and a number the tool measures for free (how different the two pictures are, 0 = the same, 1 = opposite). It scores the stitch ("join", 1 to 5) by the kind of join: a continuing shot must start where the clip before ended; a same-scene join must keep the place, people, light and props; a cut is only flagged when it looks like an accident (a jump cut, an abrupt light or size change). A continuing shot above `join_max_difference` is capped at 2 by a rule the AI cannot overrule, and a join score of 2 or less means the clip does not meet the goal. The take with the better stitch wins the automatic pick. Not judged (and the card says why): the first clip, a clip before it that is not made yet, or only a placeholder. The review card shows both pictures side by side. A weak stitch also appears under *Continuity* with *Re-make* and *Change this join to a cut*. The part and whole-video review now looks at every seam, cuts included, in the stitched video, so a crossfade over a continuing shot is seen too.

**Quality for one part.** Open a part and choose *Quality for this part*: Best, Balanced, Budget or Free preview, or "Same as above". The price of each choice is shown beside it (worked out on a copy; nothing is saved or spent until you choose). A clip uses its own choice, else its part's, else the whole video's. Only the video, picture and natural-sound models change. **Voices, the narrator and the music are chosen once for the whole video**, so a character never gets a different voice in a cheaper part.

**Change a length and everything follows.** Type a new length for a part or the whole video and the clips under it are resized in proportion, never below what each clip needs (its speech, its action steps, the shortest clip the chosen model can make, `min_clip_s`). A message says which clips moved, and why it could not go lower. Clips already made, clips you marked *Keep as it is*, and clips of your own footage are never changed silently. A spoken line marked *exact* (the plan marks text you gave in your goal) is never shortened, reworded or dropped. After you edit a part's goal, the tool offers (never forces) to rewrite the clip scripts under it, and shows the AI cost first.

**How a clip joins the clip before it.** The plan decides this for every clip, before any script is written, and says why: *Continues* (starts on the very last picture of the clip before; the same shot goes on), *Same scene* (same place and people, new angle) or *Cut* (new place or time). A small marker between the clips in the story tree shows it; click it to change it. For a *Continues* join the tool: makes the earlier clip first; starts the later clip from the earlier clip's real last frame; **requires** a video model that can start from a picture (it never quietly starts fresh: if none is connected the clip is blocked, with a plain message and ways out); copies the end state of the earlier clip into the start state of the later one itself; makes the cut between them a hard cut; and waits for a real clip when the earlier one is only a placeholder. After both clips are made it **measures** the join: the first picture of the later clip against the last picture of the earlier one (0 = the same, 1 = opposite). Above `join_max_difference` (`vg policy`) the clip is flagged with *Re-make from the hand-over picture* and *Change this join to a cut*. The default limit comes from clips made with ffmpeg; tune it after you see real clips.

**Everything is English; only the spoken words use your language.** The language you choose is the language of the **spoken words** (dialogue and narration) only. The Goal, part and clip titles, descriptions, notes, reviews and every message stay in English, even when the video is spoken in Hindi or Tamil. Quotes you type are never translated or reworded. For a **mixed-language video** add the other languages under *Also spoken*: a character speaks the language on their card, and any single line or the narration can have its own language (the small language box beside the line in the clip editor). The planner writes the English meaning of every non-English line next to it, so you can check a line you cannot read and use it for subtitles (*Subtitles show*: the spoken words, the English meaning, or both). Voices are asked for each line's own language, and the Review Agent listens in the clip's language (a clip with two languages is transcribed with automatic detection). If you give a quote in English letters (for example Hindi written as "Shri guru charan…"), the planner writes the same words in the language's own script for the voice; the continuity check tells you when a line is in the wrong script. If a subtitle font for the language is missing on your computer, the continuity check says so.

**Characters stay the same in every part.** Every speaker has an accent and a language decided by the plan from who the character is (an Indian character speaks with an Indian accent), and you can change both in the character card. The accent the plan asks for counts strongly when a voice is chosen (`voice_accent_weight`); if your voice library has no closer match the card says so plainly (the voice service sets the accent through the voice itself, so the result depends on your voice library). No connected voice can sing yet, so the planner is told to write lines that are recited or chanted.

**Continuity check.** A line under the numbers strip lists what would make the clips feel like different videos, with one-click fixes where the fix is mechanical: a join not decided, a continuing clip that does not start where the one before ends, the same place and people joined as a cut, clothes that change inside one scene, a speaker with no accent or gender, a line written in another script than its speaker's language, a clip made with a voice that has since changed, and neighbouring parts made with different video models. These are plain rules: no AI, no cost. The *Generate* box also lists what a part **reuses** (voices, looks, the last picture of the clip before) and refuses to start a clip that is blocked.

**Preview mode.** Without keys for a video or image service, the tool cannot make real footage. It makes *text-card previews* instead (each card says "PREVIEW — not real footage"). A banner at the top, a "preview" mark on each clip, and the Generate box all tell you this and what to add.

**A talking animal or object** (for example a lion that says "hello how are you"). The tool does it in three steps:
1. a picture of the lion: made by an image model (GPT Image, Nano Banana, Flux), or a real photo you choose;
2. the voice: spoken by a voice service (ElevenLabs, Cartesia), from your description such as "deep, growly";
3. the animation: a talking-animation model (Kling Avatar through fal.ai) moves the mouth to the voice.

With the fal.ai key (and ElevenLabs for the voice) this works. A presenter who is a person uses the same steps with HeyGen or VEED as an alternative.

**Real photos, found for you.** For an animal, an object or a place, you can add your own photo. If you add none, the tool **searches for a real photo by itself** (Wikimedia Commons needs no key; Pexels is optional) when the plan is drafted, so you see the picture before any money is spent. It uses a free search; if your AI brain can see pictures, it also looks at the best few and picks the one that fits. It never replaces a photo you supplied. It never searches for people or for your own product or brand (those must be supplied). You see what it found, who took it and the licence, with buttons *Choose another photo* and *Remove it*. If you remove it, it will not search again for that item. Credits are saved in `output/credits.txt`. If nothing suitable is found, a picture is made with an AI image model, or a preview card if none is connected.

**Record your voice in the tool.** On an actor press *Record my voice* (or *My voice* in the Context tab). Read the shown text for 30 seconds to 2 minutes. The recording is used **only to copy your voice**. It is not placed in the video: every line of the script is spoken fresh in the copied voice. Copying a voice needs ElevenLabs or Cartesia; without one, the tool warns you and uses a stock voice. If Safari blocks the microphone: Safari → Settings → Websites → Microphone.

**How the Review Agent judges quality.** It judges every take as *video*, to cinema quality, not only against your goal. It scores: goal, script, actors, behaviour, **realism** (skin, eyes, hands, fur, no AI artifacts), **motion** (real, natural movement, not a slideshow or zoom), **consistency** (same face, clothing, light and background across frames), **fidelity** (sharp, no blur or blocks), **audio** (natural, clear voice), continuity, timing and lip-sync. It looks at spread-out frames and at pairs of neighbouring frames, to catch warping and morphing. The tool also measures numbers itself, for free: how much moves, how sharp the clip is compared with its starting picture, loudness and silence. Some rules cannot be overruled by the AI: a free preview card, or a clip where almost nothing moves, can never pass as realistic animation. A score of 0 means "could not be checked" (for example the offline brain cannot see). The Review Agent only suggests; you decide.

**Where did the money go?** Click the *Cost* or *Budget* tile at the top. It shows your budget, what has been spent, what is still to spend, and every paid call grouped by type (AI brain, pictures, video, voices, music), with how each amount was counted. In the terminal: `vg budget`. The Budget is a safety limit; the default comes from Settings.

**Help is everywhere.** Hover any button, or tab to it, to see *what it does* and *what you get*. Press **?** (or the Help button) for step-by-step guides; each step has a **Show me** button that points at the real control. You can also ask questions in plain words (Ctrl/⌘ K, or Help): "Why does this clip cost so much?" The answer comes from your project's own numbers. In the terminal: `vg explain "why is the budget $0.23?"`.

**Is it working?** While anything runs you see a bar under the top menu: what is happening now ("Making clip 2.1 · Making video, take 2 of 3"), the time so far, how many clips are done, and Pause/Stop. The browser tab title shows ⏳ while working, 👆 when it needs your pick and ✅ when finished. The browser can also send a notification (it asks once).

**Quality rules are generic and in one place.** The tool does not know about any particular kind of video. The AI planner writes what each clip needs (for example: only the face moves, the body moves, or the whole scene moves), and each model's row in the catalogue says what it can do. The tool matches the two. If a clip needs more than any single route can do, it is flagged and you get a **Split this clip** button; the planner is also told this rule, in words generated from the catalogue. Every number used to judge a result is a named setting; run `vg policy` to see them all (longest allowed freeze, sound loudness under speech and alone, voice pitch ranges, the sharpness match between clips, whether to make end pictures, …) and change any of them in `~/.video-generator/config.yaml` under `policy:`.
- A clip is never padded with a frozen picture. If a model makes less than planned, the clip is cut to what was made and you are told why.
- Sound always lasts as long as the picture, and every made sound is brought to the same level, so cuts have no jump in loudness.
- Before a voice is paid for, the tool listens to the vendor's free sample clips of the best candidates and picks the one whose pitch fits the character.
- A clip with a planned ending that the next clip continues from gets an end picture, when a model can use it.
- A clip much softer than the clip it continues from gets a mild finishing pass.
- If your key lacks a permission (for example ElevenLabs "music_generation"), the message names it, the next model is tried, and the reason is shown in "Your next step". `vg doctor` checks these permissions up front.

**Your next step.** A strip under the top bar always shows the one thing to do next, with a button that does it, and *Show me where* to highlight the control. It reads the project as it is right now and updates after every click: connect your services, plan, check characters (consent, photos, voices), check the cost against the budget, make the first clip, pick a take, fix a failed clip, make the rest, join, watch and download. *All steps* shows the whole path; things that do not block you (a Review Agent flag, a warning on a clip) are listed as "also worth a look". It uses plain rules, so it is instant and free. Hide it with the ✕ and bring it back with *Show next-step guide*.

**Voices, sound, continuity and frame shape work for any scenario.** You do not have to describe these yourself; the plan decides, and you can change anything.
- **Voices.** Every speaker (a person of any age, an animal, a mascot, the narrator) gets a voice profile from the plan: gender, age, pitch, pace, accent. The tool chooses a voice that fits (gender and age are hard rules), gives every speaker a different voice, and keeps it for the whole video. In the character card you can change the profile, press *Preview voice* and *Choose another voice*. After the voice is made the tool measures its pitch and corrects it a little if it clearly does not fit (for example a high voice for a deep character), and says so. If your ElevenLabs key cannot list voices, `vg doctor` tells you to allow "Voices: Read".
- **Sound.** The plan writes the sound design of each clip (wind and birds outdoors, room tone indoors, footsteps, or "silence") and suggests music for the whole video. A clip that would otherwise be silent (a video model with no sound of its own, or a talking-picture clip) gets natural sound made for it for a fraction of a cent per second; a free local sound is the safety net. Switch it off with *Natural sound* in the Inspector. Music stays your choice.
- **Continuity.** The plan says where each clip begins and ends, and whether the next clip continues the same shot, stays in the same scene, or is a new scene. A clip that continues starts from the previous clip's last frame, also when someone is speaking to the camera. A character keeps the look they had when they first appeared. The Review Agent compares the last frame of one clip with the first frame of the next.
- **No black bars.** Pictures are fitted to your video's shape (16:9, 9:16, 1:1, 4:5…). Gaps are filled with a blurred copy of the picture; you can choose Black or Crop under *Empty space around pictures*.
- **Re-make.** Pressing *Re-make* on a finished clip now makes it again, and clips that continue from it are marked to be made again too.

**Test everything cheaply before a real project.** Run `vg smoke-test`. It shows what it will do and the estimated cost (about $0.8 for a normal setup), asks "Spend up to about $…?", and only then makes a tiny real test of the voice, a picture, a short video and the talking lion with your own keys. It never spends more than `--max-usd` (default $1.00), keeps going if one step fails, and prints one short report to paste when something needs fixing. If one model fails before it did any work (for example a wrong model name), the next usable model takes over and the report marks the step with ! so the name can be corrected.

**Model names and prices** live in `video_generator/data/catalog.yaml` (or your own copy in `~/.video-generator/catalog.yaml`). The `params:` block of a model says how its API is spelled (the start-picture field, the lengths it accepts). A model that only makes 5, 10 or 15 seconds is billed for the next length up, and the cost window says so. `vg doctor` also asks fal.ai whether each model name exists.

**Check your keys (free).** Run `vg doctor` before you generate. It reads the keys you saved in the GUI, uses free calls only, and says in plain words whether OpenAI, ElevenLabs and fal.ai accept your keys, how many ElevenLabs characters are left, and which OpenAI picture model your key can use. If a picture model fails during a run, the tool tries the next picture model by itself and writes which one it used in the Budget breakdown.

**Photo search check.** If a card says no photo was found, run `vg photo-test "male lion"`. It prints each step (search, filters, download) in plain words and saves the first photo it can fetch. The photos come from Wikimedia Commons (no key needed); only photos with a licence that allows commercial use and changes are used, and the credit is saved next to your video.

**Length.** The length you ask for wins. If you ask for 12 seconds in 3 clips, each clip is 4 seconds, and the AI is told how many action steps fit (about one per 2.5 seconds). A clip only becomes longer when its spoken words need more time, because speech cannot be squeezed; the clip then shows an orange note saying so.

**The final video.** When you use *Generate entire video* or *Continue to end*, the clips are joined automatically at the end. If you make clips one by one, use *Join clips into final video* (same size and speed, transitions, music, subtitles). If you change something afterwards, the final video is marked out of date and the button becomes *Update final video*.

## 5. Command line (same features)

Each command below is shown on its own line so you can copy it.

```bash
vg new "A 30-second advert for our travel bag, presented by me" --length 30 --add slides.pdf --add me.wav
```

Leave out the length and add `--auto-length` to let the plan be as short as the story allows. Add `--language hi` (or `--language auto`) to set the spoken language, `--also-language en` (repeat it for more) for a mixed-language video, and `--subtitles english` (or `spoken`, `both`) to choose what the subtitles show.

```bash
vg new "Explain our product simply" --auto-length --language auto
```

```bash
vg show
```

The goal tree with length, cost and status.

```bash
vg export 2 -o part2.mp4
```

Saves the finished video of part 2 (or a clip such as `2.1`). Every clip under it must be made. It uses the saved music; if new music would cost money it asks first (`--yes` agrees, `--music none` leaves it out).

```bash
vg join 1.2 continues
vg continuity
```

```bash
vg optimize --length 50
vg optimize --cost 10 --scope 2 --ai --apply
```

`vg optimize --replan --length 40 --cut 2.3 --keep 1.1 --apply` shows the cost, asks the AI to reword the Goal a little and re-plan (it asks you if the planner has a question), shows the Goal difference and the new plan, and applies only with `--apply` (`--no-reuse` makes new videos instead of reusing the made ones the plan keeps).

`vg optimize` proposes a shorter and cheaper video and changes nothing until you add `--apply`. Give a goal with `--length` (seconds), `--cost` (dollars still to spend) or `--lowest` (as low as possible without losing quality); `--scope 2` limits it to part 2, `--max-level 2` stops before the noticeable changes, `--ai` asks the AI to tighten the script after showing what that costs. Apply is one change: `vg undo` takes it back.

`vg join` says how a clip joins the clip before it: `continues` (starts on its last picture), `same_scene` (same place, new angle) or `cut` (new place or time). `vg continuity` lists what would make the clips feel like different videos, and the fix for each (plain rules, no AI, no cost).

```bash
vg tree decompose 2
```

Break part 2 into clips with AI.

```bash
vg revise 1.2 "make Rahul look more frustrated"
```

```bash
vg actor add Priya --photo priya1.jpg --photo priya2.jpg --voice priya.wav --clothing "blue kurta" --behaviour "calm, warm smile"
```

```bash
vg actor consent <actor-id> permission
```

```bash
vg context add logo.png --role must_appear
```

```bash
vg context add --text "Always mention it weighs 400 g" --scope project
```

```bash
vg deps add 2.1 2.2 --type continues_from
```

```bash
vg estimate 2.2
```

Cost and time before making anything.

```bash
vg render --next
```

```bash
vg render --continue
```

```bash
vg render --all
```

```bash
vg takes 2.2
```

The takes, plus the Review Agent's findings.

```bash
vg pick 2.2 2
```

```bash
vg remake 2.2 --feedback "slow motion when the strap breaks"
```

```bash
vg compare 2.2 --models veo_3_1,kling_3
```

```bash
vg cost
```

Estimated vs actual cost per clip.

```bash
vg config set llm.default openai
```

Switch the AI brain to OpenAI.

```bash
vg plugins
```

```bash
vg catalog --check
```

```bash
vg vendors
```

## 6. Adding a new AI tool later

Every tool is a plug-in. A new tool is:
1. a small Python package with one class;
2. one entry-point line in its `pyproject.toml`;
3. one row in the model catalogue.

No change to the core is needed. See [docs/writing-a-plugin.md](docs/writing-a-plugin.md) and the working example in `examples/vg-plugin-example`.

## 7. Where things are stored

```
~/.video-generator/
  config.yaml      your settings (AI brain, budget, quality)
  .env             your API keys (owner-only permissions)
  catalog.yaml     your edits to the model catalogue
  timings.json     real job times, used to improve time estimates
  projects/<id>/   project.json, history (undo), inputs, clips, output/final.mp4, ledger.jsonl (spending log)
```

## 8. Honest notes

- The free, offline mode makes **previews** (storyboard cards with motion and a robotic voice). Real footage needs a video vendor key.
- The cloud plug-ins follow each vendor's public API documentation. They were not run against live accounts while this was built (no keys were available). If a vendor changes an endpoint or model name, the fix is usually one row in the catalogue or one small plug-in file. Use **Settings → Test connection** after adding a key.
- Better local voices and checks are optional installs:
  - `pip install -e ".[local-voice]"`: Kokoro voices;
  - `pip install -e ".[transcribe]"`: Whisper, so the Review Agent hears the speech;
  - `pip install -e ".[face]"`: face-match scores.

## 9. Development

```bash
pip install -e ".[dev]"
```

```bash
pytest
```

The GUI is React + TypeScript (Vite, Tailwind, Radix, React Flow) in `frontend/`. Its build is committed in `video_generator/web/static`, so users do not need Node.

```bash
npm --prefix frontend install
```

```bash
npm --prefix frontend run dev
```

That runs the GUI with live reload on :5173. It talks to `vg gui` on :8765.

```bash
npm --prefix frontend run build
```

The design and the research behind the tool choices are in [docs/DESIGN.md](docs/DESIGN.md).
