"""Luma Dream Machine API. Image inputs must be public URLs, so a start frame
is only used when it is already hosted (PUBLIC_MEDIA_BASE_URL); otherwise
text-to-video is used."""
from __future__ import annotations

import os

import httpx

from ..base import PluginError, Usage, VideoGenerator, VideoRequest, download, poll, raise_for

API = "https://api.lumalabs.ai/dream-machine/v1"


class LumaVideo(VideoGenerator):
    name = "luma"
    env_keys = ["LUMAAI_API_KEY"]
    description = "Luma Ray video"

    async def generate(self, req: VideoRequest):
        headers = {"Authorization": f"Bearer {os.environ.get('LUMAAI_API_KEY', '')}"}
        body: dict = {"prompt": req.prompt, "model": req.model or "ray-2", "aspect_ratio": req.aspect,
                      "duration": "9s" if req.seconds > 6 else "5s", "resolution": req.resolution}
        base = os.environ.get("PUBLIC_MEDIA_BASE_URL")
        if base and req.start_frame:
            body["keyframes"] = {"frame0": {"type": "image", "url": f"{base.rstrip('/')}/{req.start_frame.name}"}}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{API}/generations", headers=headers, json=body)
            raise_for(r, "Luma")
            gid = r.json()["id"]

            async def fetch():
                g = await client.get(f"{API}/generations/{gid}", headers=headers)
                raise_for(g, "Luma status")
                return g.json()

            def done(d):
                return {"completed": True, "failed": False}.get(d.get("state"))

            res = await poll(fetch, done, interval=5)
        url = (res.get("assets") or {}).get("video")
        if not url:
            raise PluginError("Luma returned no video")
        await download(url, req.out)
        return req.out, Usage(seconds=req.seconds)
