// All help text lives here, in one place, so it stays consistent and easy to improve.
// Every entry answers two questions: what does this do, and what do I get?

export interface HelpEntry {
  title: string;
  does: string;       // what happens when you use it
  gets: string;       // what you achieve
  note?: string;      // good to know: cost, needs, limits
}

export const HELP: Record<string, HelpEntry> = {
  // ------------------------------------------------------------------ start page
  "goal-box": { title: "Describe your video", does: "Type what you want in your own words. Example: “A 30-second advert for our travel bag”.", gets: "A complete first draft: parts, clips, scripts, actors, and the length, cost and time of each.", note: "Nothing is paid for at this step." },
  "attach-files": { title: "Add your own material", does: "Attach photos, slides, video clips or a voice recording.", gets: "Slides and clips go into the video as they are. Photos define how actors look. A voice recording is used to copy that voice." },
  "length-picker": { title: "Length of the video", does: "Sets how long the finished video should be.", gets: "The plan is sized to this length. You can change it later.", note: "Writing “30-second” in your goal sets it for you." },
  "shape-picker": { title: "Shape of the video", does: "Chooses wide (16:9), vertical (9:16) or square (1:1).", gets: "Wide suits YouTube, vertical suits Reels and Shorts, square suits feeds." },
  "quality-picker": { title: "Quality and cost", does: "Chooses how the tool picks AI models.", gets: "Best = highest quality. Balanced = quality for the money. Budget = the cheapest real model that is good enough for the shot. Free preview = free local tools only.", note: "Free preview makes text cards, not real footage." },
  "create-draft": { title: "Create the draft", does: "Plans your whole video with the AI brain.", gets: "A draft you can edit before anything is paid for.", note: "Costs a few cents of AI-brain use, or nothing with the offline brain." },

  // ------------------------------------------------------------------ top bar
  "back-home": { title: "All projects", does: "Goes back to the start page.", gets: "Your work is saved automatically; you can come back any time." },
  "project-name": { title: "Project name", does: "Click to rename this project.", gets: "A clear name in your project list." },
  "ai-badge": { title: "The AI brain", does: "Shows which AI plans, writes and reviews your video.", gets: "Offline = free but simple. Anthropic, OpenAI or Gemini = proper creative writing and visual review.", note: "Change it in Settings → AI brain." },
  "budget-chip": { title: "Budget", does: "Shows money spent so far against the limit you set. Click for the full breakdown.", gets: "You see exactly where every rupee or dollar went, and what is still to spend.", note: "It is a safety limit: runs pause before a clip that would cross it." },
  "ask-ai": { title: "Ask AI", does: "Type a change in plain words, or ask a question about your project.", gets: "Changes are shown to you before they happen. Questions are answered from your project's own numbers.", note: "Shortcut: Ctrl or ⌘ + K." },
  "undo": { title: "Undo", does: "Takes back your last change.", gets: "Freedom to try things. Money already spent and files already made are not undone.", note: "Shortcut: Ctrl or ⌘ + Z." },
  "redo": { title: "Redo", does: "Puts back a change you undid.", gets: "Your change returns.", note: "Shortcut: Ctrl or ⌘ + Shift + Z." },
  "graph": { title: "Links between clips", does: "Shows which clips depend on which, as arrows.", gets: "You can add, change or remove links. A clip that “continues from” another starts on that clip's last frame." },
  "library": { title: "Context library", does: "Lists every actor, photo, sound, logo and note in one place.", gets: "Find and edit anything that guides the video, shared or for one clip." },
  "theme": { title: "Light or dark", does: "Switches the colour theme.", gets: "Whatever is easier on your eyes." },
  "settings": { title: "Settings", does: "Opens your keys, AI brain, budget and model prices.", gets: "Connect the services that make real footage, voices and music." },
  "help": { title: "Help", does: "Opens step-by-step guides and a place to ask questions.", gets: "Clear steps for any task, with a “Show me” button that points at the real control.", note: "Shortcut: press ?" },
  "download": { title: "Download the video", does: "Saves your finished video to this computer.", gets: "The final .mp4 or .mov file." },

  // ------------------------------------------------------------------ the basics strip
  "summary-length": { title: "Length of the video", does: "Shows how long the finished video will be, worked out from every clip's script (words ÷ speaking speed, plus action time and pauses).", gets: "No surprise at the end. Click it to open the whole video and change the length.", note: "“Auto” means you did not ask for a length: the plan is as short as the story allows. Once you type a length, it becomes your target." },
  "summary-cost": { title: "Cost of the whole video", does: "Shows the estimated price of every clip together, and how much of it is still to spend. Click it to see the cost of each part.", gets: "The size of the bill before you spend anything.", note: "It is an estimate: price × amount × takes, from your model catalogue. Your vendor's own dashboard is the final truth." },
  "summary-time": { title: "Time to make", does: "Shows about how long it will take to make the clips that are not made yet. Clips that do not depend on each other are made at the same time.", gets: "You know whether to wait or come back later.", note: "It uses each service's usual speed, corrected by your own earlier runs." },
  "summary-quality": { title: "Quality for the whole video", does: "Chooses how models are picked. Best = highest quality. Balanced = quality for the money. Budget = the cheapest real model that is good enough. Free preview = free placeholders only.", gets: "Change it and the cost, length and models update at once. Nothing is spent by changing it.", note: "Clips that are already made are not changed. Make them again to use the new quality." },
  "summary-budget": { title: "Budget", does: "Shows money already spent against the limit you set. Click for the full breakdown.", gets: "The run pauses before a clip that would cross the limit.", note: "It is a safety limit, not a bill." },
  "cost-by-part": { title: "Cost by part", does: "Lists every part and clip with its length, cost, making time, quality and model.", gets: "You see which part is the most expensive, so you know where to save.", note: "The part totals add up to the cost of the whole video." },

  // ------------------------------------------------------------------ placeholders and models
  "part-quality": { title: "Quality for this part", does: "Chooses Best, Balanced, Budget or Free preview for this part only. “Same as above” follows the part above, or the whole video. The price of each choice is shown beside it.", gets: "Spend more on the part that matters and less on the rest. Nothing is spent by choosing.", note: "Only the video, picture and natural-sound models change. Voices, the narrator and the music are chosen once for the whole video, so every character sounds the same in every part. Clips already made are not changed." },
  "join-marker": { title: "How this clip joins the clip before it", does: "Continues = it starts on the very last picture of the clip before. Same scene = same place and people, new angle. Cut = a new place or time. The plan decides this before any script is written.", gets: "A continuing shot looks unbroken, and clips in one scene keep the same look.", note: "A continuing clip needs a video model that can start from a picture, and the cut between the two is always a hard cut." },
  "continuity-bar": { title: "Continuity", does: "Plain rules (no AI, no cost) that check the plan: every join decided, a continuing clip starts where the one before ended, the same person speaks the same way, lines are in the speaker's own script, and no clip was made with an old voice.", gets: "You find what would look or sound wrong before you spend anything.", note: "Each problem has a fix button where the fix is mechanical." },
  "say-exactly": { title: "Say exactly this", does: "Marks a spoken line as fixed. It is never shortened, reworded or dropped, whatever the AI rewrites or the length change does.", gets: "A verse, a slogan or a quote is always heard as written.", note: "The plan marks text you gave in your goal automatically. You can switch it on or off for any line." },
  "keep-clip": { title: "Keep as it is", does: "Stops length changes and script rewrites from touching this clip.", gets: "A clip you like stays exactly as it is while you change the rest.", note: "Clips already made are kept automatically unless you make them again." },
  "unpin": { title: "Use the best model", does: "Clears the model you chose on these clips, so the tool picks the best one that is connected again.", gets: "Clips pinned to the free preview model get real footage. Clips that were already made as placeholders are marked out of date, ready to be made again.", note: "Making them again costs money; you see the cost first." },
  "model-picker": { title: "Choose a model", does: "Lists every model of this kind, not only the connected ones. Each shows its price and what it can do.", gets: "You can compare and choose. Models that are not connected are marked with what is missing; choosing one opens Settings.", note: "“Auto” lets the tool pick the best one for the shot." },
  "refresh-models": { title: "Refresh from vendor", does: "Asks each connected AI vendor which models your key can use. This is free and only reads a list.", gets: "New models that are not in the catalogue yet appear, so you can choose them.", note: "Type the price from the vendor's page when you add one. It is how AI costs are counted." },

  // ------------------------------------------------------------------ start page choices
  "length-auto": { title: "Auto length", does: "You do not give a length. The plan is as short as the story allows without losing meaning or quality.", gets: "No filler. Every spoken line is heard in full.", note: "You can set a length later, or press a length here to ask for one." },
  "language-picker": { title: "Language of the video", does: "The language people speak in your video.", gets: "Lines are written in it, and voices are chosen for it.", note: "“Decided from your goal” lets the planner choose, and shows you what it chose." },
  "budget-input": { title: "Budget for this video", does: "The most you want to spend on this video.", gets: "A safety limit. The run pauses before a clip that would cross it.", note: "The default comes from Settings → Budget & quality." },
  "ballpark": { title: "Rough price", does: "A quick guess of the price from your catalogue prices, before any plan exists.", gets: "You know the size of the bill before you start.", note: "The exact numbers come after the draft. Hover to see what it is made of." },

  // ------------------------------------------------------------------ download
  "download-part": { title: "Download this part", does: "Joins the clips of this part, with their transitions, into one video file. It uses the same background music as the final video, and gives you a subtitle file too.", gets: "A finished video of just this part.", note: "It works when every clip in the part is made. If the music has not been made yet, you are asked first and shown the cost." },
  "download-clip": { title: "Download this clip", does: "Saves this finished clip to your computer.", gets: "The clip as a video file." },
  "join-music": { title: "Background music", does: "The music is made once for the whole video and saved. Joining again, and every part you download, reuse it.", gets: "You do not pay for the same music twice.", note: "New music is made only if you change the music mood or example, or the video becomes much longer than the saved track." },

  // ------------------------------------------------------------------ story tree
  "story-tree": { title: "Your story", does: "Shows the video as parts that hold clips. Click one to edit it. Drag to reorder.", gets: "A clear map of the whole video." },
  "add-part": { title: "Add a part", does: "Adds a new part (a chapter) to the story.", gets: "Room for a new idea. Break it into clips with AI, or add clips by hand." },
  "row-menu": { title: "More for this item", does: "Break it down with AI, add a clip or sub-part, or delete it.", gets: "Quick ways to reshape the story." },
  "drop-media": { title: "Add slides or your own video", does: "Drop slides (PDF, PowerPoint) or a video file here.", gets: "They become clips in the story and play exactly as supplied." },

  // ------------------------------------------------------------------ editor
  "target-seconds": { title: "Target length", does: "How long this part or clip should run.", gets: "The estimates and the AI plan follow this number." },
  "ask-ai-box": { title: "Ask AI to change this", does: "Describe a change in plain words. Example: “make it shorter and punchier”.", gets: "The AI rewrites this item. You can undo it at once." },
  "break-down": { title: "Break down with AI", does: "The AI splits this part into smaller sub-goals and writes a script for each clip.", gets: "A detailed plan for this part.", note: "Costs a few cents of AI-brain use." },
  "write-scripts": { title: "Write the missing scripts", does: "Writes a detailed script for every clip that has none yet.", gets: "Each clip gets: what we see, camera, actors, dialogue and sound." },
  "generate-part": { title: "Generate this part", does: "Makes all clips inside this part. You see the cost and time first.", gets: "The clips for this part, ready to watch and pick.", note: "You confirm before any money is spent." },
  "clip-generate": { title: "Make this clip", does: "Makes this clip (with any earlier clip it depends on). You see the cost and time first.", gets: "Several takes to choose from for shots with people; one for other shots." },
  "model-select": { title: "Which AI model", does: "Chooses the video or animation model for this clip.", gets: "“Auto” picks the best fit for the shot. Choose another to change quality or price.", note: "The cost updates at once." },
  "shot-type": { title: "Type of shot", does: "Tells the tool what kind of shot this is.", gets: "The right kind of model is chosen: talking presenter, people moving, wildlife, product and so on." },
  "on-camera-speech": { title: "Someone speaks on camera", does: "Marks that a visible person or animal speaks.", gets: "The mouth is animated to the voice (lip-sync)." },
  "pick-take": { title: "Pick this take", does: "Chooses this version of the clip for the final video.", gets: "The clip is done and clips that follow it can start.", note: "You can change your pick later; clips that depend on it are marked out of date." },
  "compare-models": { title: "Compare models", does: "Makes the same clip with several models.", gets: "You judge the models on your own content.", note: "Costs the price of each model's clip." },
  "remake-feedback": { title: "Re-make with feedback", does: "Combines the Review Agent's ticked suggestions with your own words into a new script, and shows you the change first.", gets: "A better version of the clip. The old version is kept.", note: "You see the new cost before you confirm. Your feedback wins over the agent's." },
  "feedback-box": { title: "Your feedback", does: "Say what to change. Example: “make the strap break in slow motion”.", gets: "It is added to the clip's instructions for the next version. It always wins over the AI's suggestions." },
  "apply-with-ai": { title: "Apply with Ask AI", does: "Puts this suggestion into the Ask AI box.", gets: "You see exactly what would change before anything is edited." },
  "final-card": { title: "Final video", does: "Plays the finished video and says whether it is up to date.", gets: "A last check before you download." },

  // ------------------------------------------------------------------ context & actors
  "ctx-drop": { title: "Add context", does: "Drop photos, sounds, logos or notes that apply only here.", gets: "The AI and the video models use them for this part or clip only." },
  "inherit-toggle": { title: "Use this inherited item", does: "Switches an item that comes from the whole video or a parent part on or off for this clip.", gets: "Example: hide the logo in one clip, keep it everywhere else." },
  "add-actor": { title: "Add an actor", does: "Creates a person, animal or character.", gets: "Describe them in words, add photos, set clothing, behaviour and a voice.", note: "Photos and voice of real people need your consent confirmation." },
  "add-location": { title: "Add a location", does: "Describes a place the video should look like.", gets: "Shots in that place keep a consistent look." },
  "add-object": { title: "Add an object", does: "Describes something that must appear. Example: a coffee cup.", gets: "The tool keeps it consistent, and can find a real photo of it." },
  "my-voice": { title: "My voice", does: "Creates an actor called “Me” and opens the voice recorder.", gets: "A copy of your voice that can speak any line of the script.", note: "Needs ElevenLabs or Cartesia to make the copy." },
  "find-photo": { title: "Find a photo", does: "Searches real photos with their licences.", gets: "A real photo to start from, with credits saved for you.", note: "Only for animals, objects and places. Photos of people must be your own." },
  "voice-profile": { title: "Voice profile", does: "Says who is speaking: gender, age, how deep or high, how fast, and accent. The plan fills it in from your story.", gets: "A voice that fits the character. Example: a heavy, slow, low male voice for a big old lion.", note: "Change a value and the voice is chosen again on the next run. Every speaker gets a different voice." },
  "voice-next": { title: "Choose another voice", does: "Switches this speaker to the next best voice the voice service has for the profile.", gets: "Press Preview voice to listen. The voice you pick stays, even if you edit the description later." },
  "natural-sound": { title: "Natural sound", does: "Makes wind, birds, room tone or footsteps for clips that would otherwise have no sound. The plan decides what each clip needs.", gets: "A clip with a true feel instead of silence. It costs a fraction of a cent per second, and never covers speech.", note: "A clip whose sound plan says silence stays silent." },
  "fill-mode": { title: "Empty space around pictures", does: "Chooses what fills the gap when a picture is not the shape of your video (for example a wide photo in a vertical video).", gets: "Blur: the picture sits on a blurred copy of itself (default). Black: plain bars. Crop: fills the frame and cuts the edges." },
  "next-step": { title: "Your next step", does: "Looks at your project right now and tells you the one thing to do next, with a button that does it. It updates after every click.", gets: "You never have to guess what comes next. Press the button, or press Show me where to see the control it means.", note: "All steps shows the whole path to a finished video. Hide it any time; it comes back when you press Show next-step guide." },
  "split-clip": { title: "Split this clip", does: "Replaces this clip with consecutive clips so that each needs only one kind of movement (for example one that only talks, and one that moves).", gets: "Each part can be made well by one route. The parts are linked, so each starts exactly where the last one ends. You can edit every part before spending.", note: "Costs a few cents of AI time. The clips made before and after keep their links." },
  "record-voice": { title: "Record my voice", does: "Records a voice sample in your browser.", gets: "A sample used only to copy your voice. It is not placed in the video." },
  "start-recording": { title: "Start recording", does: "Starts your microphone. Read the shown text aloud.", gets: "30 seconds to 2 minutes of clear speech gives the best copy." },
  "use-recording": { title: "Use this recording", does: "Saves the recording as this actor's voice sample.", gets: "Every spoken line is made in a copy of this voice.", note: "You must confirm the voice is yours, or that you have permission." },
  "consent-self": { title: "This is me", does: "Records that the face or voice belongs to you.", gets: "The tool may use it. The confirmation is stored with the project." },
  "consent-permission": { title: "I have permission", does: "Records that the person agreed to this use.", gets: "The tool may use it. The confirmation is stored with the project." },
  "preview-voice": { title: "Preview the voice", does: "Speaks a short sentence in this actor's voice.", gets: "You hear it before spending on a whole clip." },
  "auto-photo": { title: "Find a photo for me", does: "Searches real photos by itself, picks the best match and shows it here.", gets: "A real starting picture, with credits saved. It never replaces a photo you supplied.", note: "Free. Only for animals, objects and places; never for people." },
  "choose-another-photo": { title: "Choose another photo", does: "Opens the photo search, already filled with what the tool searched for.", gets: "You pick the exact photo you want." },
  "remove-auto-photo": { title: "Remove this photo", does: "Removes the photo the tool found and stops searching for this item.", gets: "The tool will make a picture with an AI image model instead (or a preview card if none is connected)." },
  "use-photo": { title: "Use this photo", does: "Downloads the photo into this item.", gets: "The tool starts from this exact picture. The credit is saved to a file next to your video." },

  // ------------------------------------------------------------------ cost & links
  "what-if": { title: "What if…", does: "Change the model, number of takes or transition for this clip.", gets: "The cost and time update at once, so you can compare before you spend." },
  "find-links": { title: "Find links with AI", does: "The AI looks for clips that must connect.", gets: "Links added for you. Example: “starts where the last clip ended”." },
  "add-link": { title: "Add a link", does: "Makes this clip depend on another.", gets: "The tool uses the earlier clip's result and waits for it automatically." },
  "revert-version": { title: "Go back to this version", does: "Restores an older script of this clip.", gets: "Your earlier work comes back; nothing is lost." },

  // ------------------------------------------------------------------ run bar
  "estimates": { title: "Length, cost and time", does: "Shows the estimated length, what is still to spend, and how long making the rest will take.", gets: "No surprises. Hover each number to see how it was worked out; click the Cost tile at the top for the cost of each part and the full list." },
  "generate-all": { title: "Generate entire video", does: "Makes every clip in the right order, several at the same time, then joins them. You see the cost and time first.", gets: "The finished video, with music and subtitles.", note: "You confirm before any money is spent. Pause or stop at any time." },
  "generate-next": { title: "Generate next", does: "Makes just the next clip in the story.", gets: "A safe way to check quality one clip at a time before spending more." },
  "continue-end": { title: "Continue to end", does: "Makes all remaining clips and joins the video.", gets: "Finish the job after you are happy with the first clips." },
  "pause": { title: "Pause", does: "Stops new clips from starting. Clips already running finish.", gets: "Time to think; nothing is lost." },
  "resume": { title: "Resume", does: "Carries on from where it paused.", gets: "The run continues." },
  "stop": { title: "Stop", does: "Cancels clips that are waiting.", gets: "Finished clips are kept." },
  "play-final": { title: "Play final video", does: "Plays the finished video.", gets: "A last look before you download." },
  "download-final": { title: "Download", does: "Saves the video to this computer.", gets: "The .mp4 or .mov file." },
  "join-final": { title: "Join clips into final video", does: "Joins all finished clips into one video: same size and speed, transitions, music and subtitles.", gets: "The final video. It happens by itself after “Generate entire video”; use this after making clips one by one, or after changes." },
  "timeline-block": { title: "A clip on the timeline", does: "Click to open this clip. The width shows its length.", gets: "Green = done, orange = waiting for your pick, red = failed, striped = being made." },
  "activity-bar": { title: "What is happening now", does: "Shows what the tool is doing, for how long, and how many clips are done.", gets: "You can always tell whether it is working. Pause or stop from here." },

  // ------------------------------------------------------------------ dialogs
  "confirm-spend": { title: "Confirm and spend", does: "Starts making the clips shown.", gets: "The clips, at about the cost shown.", note: "The estimate is shown first so there are no surprises." },
  "auto-pick": { title: "Auto-pick the best take", does: "The tool chooses the best take using the Review Agent's scores.", gets: "A run that finishes without waiting for you. You can change any pick afterwards." },
  "save-key": { title: "Save the key", does: "Stores the key on this computer only.", gets: "The tool can use that service from now on." },
  "test-connection": { title: "Test connection", does: "Checks that the key works.", gets: "You know it is ready before a real project." },
};

// ---------------------------------------------------------------------- guides
export interface GuideStep { text: string; show?: string }
export interface Guide { id: string; title: string; achieve: string; steps: GuideStep[] }

export const GUIDES: Guide[] = [
  { id: "first", title: "Make my first video", achieve: "A finished video file from one sentence.", steps: [
    { text: "Type your goal in the big box and press Enter. Example: “A 30-second advert for our travel bag”.", show: "goal-box" },
    { text: "Read the draft. Parts and clips are on the left. Click any text to change it; it saves by itself.", show: "story-tree" },
    { text: "Check the length, cost and time at the bottom. They are estimates, shown before anything is paid for.", show: "estimates" },
    { text: "Press Generate next to make one clip and look at it. Happy? Press Continue to end. Or press Generate entire video.", show: "generate-next" },
    { text: "When the bar says a take is waiting, open the clip and press Pick this take.", show: "pick-take" },
    { text: "Press Play final video to watch it, then Download.", show: "play-final" },
  ] },
  { id: "real", title: "Get real footage instead of previews", achieve: "Real pictures, video and voices, not text cards.", steps: [
    { text: "Open Settings. Each service has a Sign up link and a Prices link.", show: "settings" },
    { text: "Add one AI brain (Anthropic or OpenAI). It plans, writes and reviews." },
    { text: "Add fal.ai for pictures and video, and ElevenLabs for voices. These three are a good start." },
    { text: "Press Test connection for each, so you know they work.", show: "test-connection" },
    { text: "Make or re-make your clips. The orange Preview marks disappear." },
  ] },
  { id: "voice", title: "Use my own voice", achieve: "Every line of your script spoken in a copy of your voice.", steps: [
    { text: "In the Context tab press My voice. The recorder opens.", show: "my-voice" },
    { text: "Press Start recording and read the shown text for 30 seconds to 2 minutes, in a quiet room.", show: "start-recording" },
    { text: "Listen back. Tick that it is your own voice, then press Use this recording.", show: "use-recording" },
    { text: "Remember: the recording is only used to copy your voice. It is not played in the video. Copying needs an ElevenLabs or Cartesia key." },
  ] },
  { id: "actors", title: "Add an actor from a photo or words", achieve: "A person, animal or character that looks and sounds the same in every clip.", steps: [
    { text: "In the Context tab press Actor.", show: "add-actor" },
    { text: "Click the new card. Describe the appearance, clothing and behaviour in words. Photos are optional." },
    { text: "Add a voice sample, or describe the voice. Example: “deep, warm, slow”." },
    { text: "For a real person, confirm consent: “This is me” or “I have permission”.", show: "consent-self" },
  ] },
  { id: "photos", title: "Use a real photo of an animal or object", achieve: "The video starts from a real photo, with credits.", steps: [
    { text: "If you add nothing, the tool searches for a photo by itself and shows it on the card." },
    { text: "Not right? Open the card and press Find a photo to choose another.", show: "find-photo" },
    { text: "Rather use your own? Drop your photo on the card. Yours is always used first." },
    { text: "Photos of people are never searched: upload your own, or use one you have permission for." },
  ] },
  { id: "cost", title: "Understand length, cost, time and budget", achieve: "You know what every number means and where it comes from.", steps: [
    { text: "Click the Cost tile at the top to see the cost of each part, what has been spent, and on which calls.", show: "summary-cost" },
    { text: "Hover any length, cost or time to see how it was worked out.", show: "estimates" },
    { text: "Open a clip, then the Cost & time tab, to try What if… changes before you spend.", show: "what-if" },
    { text: "Ask in plain words. Example: “Why does this clip cost so much?”", show: "ask-ai" },
  ] },
  { id: "quality", title: "Check quality and re-make a clip", achieve: "A better version of a clip, with you in control.", steps: [
    { text: "Open a clip that has takes. The Review Agent scores each take and lists problems with times.", show: "pick-take" },
    { text: "Tick the suggestions you agree with." },
    { text: "Type your own feedback. It wins over the agent's.", show: "feedback-box" },
    { text: "Press Re-make with feedback. You see the change and the cost first.", show: "remake-feedback" },
    { text: "Not better? Open the Versions tab and go back." },
  ] },
  { id: "links", title: "Make a clip continue from the previous one", achieve: "A smooth cut where clip B starts exactly where clip A ended.", steps: [
    { text: "Open clip B and go to the Links tab, or press the graph button at the top.", show: "graph" },
    { text: "Add a link: “continues from” clip A.", show: "add-link" },
    { text: "The tool waits for clip A, takes its last frame and starts clip B from it." },
  ] },
  { id: "final", title: "Get the final video", achieve: "One video file with transitions, music and subtitles.", steps: [
    { text: "Use Generate entire video or Continue to end. The clips are joined automatically at the end." },
    { text: "Made clips one by one? Press Join clips into final video.", show: "join-final" },
    { text: "Changed something later? The button says Update final video." },
    { text: "Press Play final video, then Download.", show: "download-final" },
  ] },
];

export const SHORTCUTS = [
  ["Ctrl / ⌘ + K", "Ask AI: change something or ask a question"],
  ["Ctrl / ⌘ + Z", "Undo"], ["Ctrl / ⌘ + Shift + Z", "Redo"], ["?", "Open Help"],
];
