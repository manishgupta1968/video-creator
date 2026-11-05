# Writing a plug-in (adding a new AI tool)

video-generator never calls a vendor directly. It calls **jobs**:
- write a script
- make an image
- make a video
- make an avatar
- speak
- lip-sync
- make music
- transcribe
- score quality

Each tool that can do a job is a **plug-in**.

Adding a tool takes three steps. You do not change the core code.

## Step 1 – Write one class

Pick the interface for the job from `video_generator/plugins/base.py`:

| Job | Interface | Method you write |
|---|---|---|
| AI brain | `LLM` | `generate_json(system, user, schema, model, images, video, meta)` |
| Image | `ImageGenerator` | `generate(ImageRequest)` |
| Video | `VideoGenerator` | `generate(VideoRequest)` |
| Presenter / twin | `AvatarGenerator` | `generate(AvatarRequest)` |
| Voice | `VoiceSynth` | `synthesize(text, VoiceSpec, out)`, plus optional `clone()` and `match()` |
| Lip-sync | `LipSync` | `sync(video, audio, out)` |
| Music | `MusicGenerator` | `generate(prompt, seconds, out, reference)` |
| Speech-to-text | `Transcriber` | `transcribe(media)` |
| Quality score | `QualityScorer` | `score(video, references)` |

Example:

```python
from video_generator.plugins.base import VideoGenerator, VideoRequest, Usage, poll, download, raise_for

class MyVideo(VideoGenerator):
    name = "myvendor"                 # used in catalog.yaml
    env_keys = ["MYVENDOR_API_KEY"]   # shown in Settings; is_configured() checks them
    description = "MyVendor video model"

    async def generate(self, req: VideoRequest):
        # 1. submit (use req.prompt, req.start_frame, req.seconds, req.aspect …)
        # 2. poll(...) until done      3. download(url, req.out)
        return req.out, Usage(seconds=req.seconds)
```

There are helpers in `base.py` and `fal_common.py`:
- `poll()`: the submit → wait → done loop
- `download()`
- `data_uri()` and `b64()`: send files to the vendor
- `raise_for()`: turns an HTTP error into a clear message for the user

## Step 2 – Register it

In your package's `pyproject.toml`, add:

```toml
[project.entry-points."video_generator.plugins"]
myvendor = "my_package:MyVideo"
```

Install your package into the same environment:

```bash
pip install my-package
```

```bash
pip install -e path/to/it
```

The second form is for a package you are working on locally.

Check that it was found:

```bash
vg plugins
```

## Step 3 – Add a catalogue row

The catalogue tells the router when to use your model and what it costs. Add the row in **Settings → Model catalogue**, or in `~/.video-generator/catalog.yaml`:

```yaml
video:
  - id: myvendor_v1
    plugin: myvendor
    model: v1                       # passed to your plugin as req.model
    vendor: myvendor
    strengths: {human_motion: 4, wildlife: 3, landscape: 4, product: 4, dialogue_scene: 2, talking_head: 2, other: 3}
    capabilities: {start_frame: true, end_frame: false, reference_images: 2, native_audio: false, max_seconds: 10}
    price: {unit: second, usd: 0.10}
    time: {queue_s: 30, per_output_s: 8}
    licence: commercial
    pricing_url: https://myvendor.example/pricing
    last_checked: "2026-11-04"
```

What the router does with this row:
- It scores the model for each shot type using `strengths` (from 1 to 5).
- For a clip that *continues from* another clip, it only uses models with `start_frame: true`.
- It uses `price` and `time` for the live estimates.
- It moves to the next model if a call fails or the key is missing.

### The capability words (what a model can do)

The router and the planner read these words from the row. Nothing about a model is written in code, so a new model needs only a row.

| Word | Values | Meaning |
|---|---|---|
| `animates` | `face`, `body`, `scene` | What can move. A talking-picture model is `face` (only the face and head). A video model is `scene`. A higher value covers a lower one. |
| `length` | `follows_audio`, `fixed`, `flexible` | How long a clip is. `follows_audio`: exactly as long as the speech. `fixed`: one of a list (`params.durations`). |
| `start_frame`, `end_frame` | true / false | Can start from, or end on, a given picture. A clip whose ending is planned and which the next clip continues from asks for `end_frame`. |
| `native_audio`, `speech` | true / false | Makes its own sound. `speech`: also speaks the planned line itself. |
| `faces` (lip-sync rows) | `human`, `animal`, `object` or a list | Which speakers the step works for. |
| `voice_preview` (voice rows) | true / false | The vendor gives a free sample clip of every voice, so the tool can listen to a voice before choosing it. |
| `max_seconds`, `reference_images`, `non_human` | numbers / true | As before. |

The planner is shown a "What each route can do" text built from these words, so changing a row changes what the planner is told. Every number the tool uses to judge a result (longest allowed freeze, sound loudness, voice pitch ranges, …) is one named setting; see `vg policy`.

To make it the first choice for one kind of shot, set `preferred_models` in `config.yaml`. For example, `preferred_models: {human_motion: myvendor_v1}`.

## Working example

`examples/vg-plugin-example/` is a complete plug-in package. It is a free "sketch" video model. To try it, install it and then copy its catalogue row:

```bash
pip install -e examples/vg-plugin-example
```

```bash
cat examples/vg-plugin-example/catalog_snippet.yaml >> ~/.video-generator/catalog.yaml
```

```bash
vg plugins
```

`sketch_video` is now listed. In Free mode, the router picks it for landscape shots.

## Tips

- Keep all vendor details (URLs, field names, polling) inside your plug-in file. If the vendor changes its API, only that file needs to change.
- Raise `PluginError("clear message")` for problems the user should see.
- If the vendor reports what a call really cost, return it in `Usage(cost_usd=...)`. The spending log then shows the actual cost instead of the estimate.
- If the vendor has a pricing API, implement `price_lookup(model)`. The estimate will then use live prices.
