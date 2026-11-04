"""Runway API (image-to-video). Docs: https://docs.dev.runwayml.com"""
from __future__ import annotations

import os

import httpx

from ..base import PluginError, Usage, VideoGenerator, VideoRequest, data_uri, download, poll, raise_for

API = "https://api.dev.runwayml.com/v1"
RATIOS = {"16:9": "1280:720", "9:16": "720:1280", "1:1": "960:960", "4:3": "1104:832", "3:4": "832:1104", "21:9": "1584:672"}


class RunwayVideo(VideoGenerator):
    name = "runway"
    env_keys = ["RUNWAYML_API_SECRET"]
    description = "Runway Gen-4.x (camera control, product shots)"

    async def generate(self, req: VideoRequest):
        if not req.start_frame:
            raise PluginError("Runway needs a start image (the keyframe)")
        headers = {"Authorization": f"Bearer {os.environ.get('RUNWAYML_API_SECRET', '')}",
                   "X-Runway-Version": "2024-11-06"}
        body = {"model": req.model or "gen4.5", "promptImage": data_uri(req.start_frame),
                "promptText": (req.prompt + (f" Camera: {req.camera}." if req.camera else ""))[:1000],
                "ratio": RATIOS.get(req.aspect, "1280:720"), "duration": 10 if req.seconds > 7 else 5}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{API}/image_to_video", headers=headers, json=body)
            raise_for(r, "Runway")
            task_id = r.json()["id"]

            async def fetch():
                g = await client.get(f"{API}/tasks/{task_id}", headers=headers)
                raise_for(g, "Runway status")
                return g.json()

            def done(d):
                return {"SUCCEEDED": True, "FAILED": False, "CANCELLED": False}.get(d.get("status"))

            res = await poll(fetch, done, interval=5)
        url = (res.get("output") or [None])[0]
        if not url:
            raise PluginError("Runway returned no video")
        await download(url, req.out)
        return req.out, Usage(seconds=body["duration"])
