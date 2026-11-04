"""Google Veo through the Gemini API (long-running predict operation).
Docs: https://ai.google.dev/gemini-api/docs/video"""
from __future__ import annotations

import mimetypes
import os

import httpx

from ..base import PluginError, Usage, VideoGenerator, VideoRequest, b64, download, poll, raise_for

API = "https://generativelanguage.googleapis.com/v1beta"


class VeoVideo(VideoGenerator):
    name = "veo"
    env_keys = ["GEMINI_API_KEY"]
    description = "Google Veo 3.x (strong for people speaking in scenes and nature)"

    async def generate(self, req: VideoRequest):
        key = os.environ.get("GEMINI_API_KEY", "")
        headers = {"x-goog-api-key": key}
        instance: dict = {"prompt": req.prompt + (f" Camera: {req.camera}." if req.camera else "")}
        if req.start_frame:
            instance["image"] = {"bytesBase64Encoded": b64(req.start_frame),
                                 "mimeType": mimetypes.guess_type(str(req.start_frame))[0] or "image/png"}
        if req.end_frame:
            instance["lastFrame"] = {"bytesBase64Encoded": b64(req.end_frame),
                                     "mimeType": mimetypes.guess_type(str(req.end_frame))[0] or "image/png"}
        params = {"aspectRatio": req.aspect if req.aspect in ("16:9", "9:16") else "16:9",
                  "durationSeconds": int(min(max(round(req.seconds), 4), 8)),
                  "resolution": "1080p" if req.resolution in ("1080p", "4k") else "720p"}
        if req.negative:
            params["negativePrompt"] = req.negative
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{API}/models/{req.model}:predictLongRunning", headers=headers,
                                  json={"instances": [instance], "parameters": params})
            raise_for(r, "Veo")
            op = r.json()

            async def fetch():
                g = await client.get(f"{API}/{op['name']}", headers=headers)
                raise_for(g, "Veo status")
                return g.json()

            def done(d):
                if d.get("error"):
                    return False
                return True if d.get("done") else None

            res = await poll(fetch, done, interval=8)
        try:
            samples = res["response"]["generateVideoResponse"]["generatedSamples"]
            uri = samples[0]["video"]["uri"]
        except (KeyError, IndexError):
            raise PluginError(f"Veo returned no video: {str(res)[:300]}")
        await download(uri, req.out, headers=headers)
        return req.out, Usage(seconds=params["durationSeconds"])
