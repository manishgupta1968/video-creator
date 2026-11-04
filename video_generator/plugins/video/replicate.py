"""Video through Replicate (aggregator). Catalogue `model` = "owner/name"."""
from __future__ import annotations

import os

import httpx

from ..base import PluginError, Usage, VideoGenerator, VideoRequest, data_uri, download, poll, raise_for

API = "https://api.replicate.com/v1"


class ReplicateVideo(VideoGenerator):
    name = "replicate"
    env_keys = ["REPLICATE_API_TOKEN"]
    description = "Video models on Replicate"

    async def generate(self, req: VideoRequest):
        headers = {"Authorization": f"Bearer {os.environ.get('REPLICATE_API_TOKEN', '')}", "Prefer": "wait=60"}
        inp = {"prompt": req.prompt, "num_frames": int(max(req.seconds, 1) * 16), "aspect_ratio": req.aspect}
        if req.start_frame:
            inp["image"] = data_uri(req.start_frame)
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{API}/models/{req.model}/predictions", headers=headers, json={"input": inp})
            raise_for(r, "Replicate")
            pred = r.json()

            async def fetch():
                g = await client.get(pred["urls"]["get"], headers=headers)
                raise_for(g, "Replicate status")
                return g.json()

            def done(d):
                return {"succeeded": True, "failed": False, "canceled": False}.get(d.get("status"))

            if pred.get("status") != "succeeded":
                pred = await poll(fetch, done, interval=4)
        out = pred.get("output")
        url = out[0] if isinstance(out, list) else out
        if not url:
            raise PluginError("Replicate returned no video")
        await download(url, req.out)
        return req.out, Usage(seconds=req.seconds)
