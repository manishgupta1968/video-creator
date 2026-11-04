"""Kling official API (JWT from access key + secret key).
Docs: https://app.klingai.com/global/dev/document-api"""
from __future__ import annotations

import os
import time

import httpx

from ..base import PluginError, Usage, VideoGenerator, VideoRequest, b64, download, poll, raise_for

API = os.environ.get("KLING_API_BASE", "https://api-singapore.klingai.com")


def _token() -> str:
    import jwt
    now = int(time.time())
    return jwt.encode({"iss": os.environ["KLING_ACCESS_KEY"], "exp": now + 1800, "nbf": now - 5},
                      os.environ["KLING_SECRET_KEY"], algorithm="HS256", headers={"alg": "HS256", "typ": "JWT"})


class KlingVideo(VideoGenerator):
    name = "kling"
    env_keys = ["KLING_ACCESS_KEY", "KLING_SECRET_KEY"]
    description = "Kling official API"

    async def generate(self, req: VideoRequest):
        headers = {"Authorization": f"Bearer {_token()}"}
        body: dict = {"model_name": req.model or "kling-v3", "prompt": req.prompt[:2500],
                      "negative_prompt": req.negative[:2500], "duration": "10" if req.seconds > 7 else "5",
                      "mode": "pro"}
        path = "/v1/videos/text2video"
        if req.start_frame:
            body["image"] = b64(req.start_frame)
            path = "/v1/videos/image2video"
            if req.end_frame:
                body["image_tail"] = b64(req.end_frame)
        else:
            body["aspect_ratio"] = req.aspect
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(API + path, headers=headers, json=body)
            raise_for(r, "Kling")
            task_id = r.json()["data"]["task_id"]

            async def fetch():
                g = await client.get(f"{API}{path}/{task_id}", headers={"Authorization": f"Bearer {_token()}"})
                raise_for(g, "Kling status")
                return g.json()["data"]

            def done(d):
                return {"succeed": True, "failed": False}.get(d.get("task_status"))

            res = await poll(fetch, done, interval=6)
        try:
            url = res["task_result"]["videos"][0]["url"]
        except (KeyError, IndexError):
            raise PluginError("Kling returned no video")
        await download(url, req.out)
        return req.out, Usage(seconds=float(body["duration"]))
