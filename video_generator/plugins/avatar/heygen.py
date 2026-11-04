"""HeyGen API: digital twin / photo avatar speaking your audio.

Flow: upload photo (talking photo) or use an existing avatar_id, upload the
audio asset, create the video, poll, download.
Docs: https://docs.heygen.com
"""
from __future__ import annotations

import mimetypes
import os

import httpx

from ..base import AvatarGenerator, AvatarRequest, PluginError, Usage, download, poll, raise_for
from ... import media

API = "https://api.heygen.com"
UPLOAD = "https://upload.heygen.com/v1"
DIMS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}


class HeyGenAvatar(AvatarGenerator):
    name = "heygen"
    env_keys = ["HEYGEN_API_KEY"]
    description = "HeyGen avatars / digital twins"

    async def _upload(self, client: httpx.AsyncClient, path, kind: str) -> dict:
        mime = mimetypes.guess_type(str(path))[0] or ("image/jpeg" if kind == "talking_photo" else "audio/mpeg")
        url = f"{UPLOAD}/talking_photo" if kind == "talking_photo" else f"{UPLOAD}/asset"
        r = await client.post(url, headers={"X-Api-Key": os.environ["HEYGEN_API_KEY"], "Content-Type": mime},
                              content=path.read_bytes())
        raise_for(r, "HeyGen upload")
        return r.json().get("data", {})

    async def generate(self, req: AvatarRequest):
        headers = {"X-Api-Key": os.environ.get("HEYGEN_API_KEY", "")}
        async with httpx.AsyncClient(timeout=300) as client:
            audio = req.audio
            if audio.suffix.lower() != ".mp3":
                mp3 = audio.with_suffix(".mp3")
                media.ff("-i", str(audio), str(mp3))
                audio = mp3
            asset = await self._upload(client, audio, "asset")
            audio_id = asset.get("id") or asset.get("asset_id")
            if req.avatar_id:
                character = {"type": "avatar", "avatar_id": req.avatar_id, "avatar_style": "normal"}
            elif req.photo:
                tp = await self._upload(client, req.photo, "talking_photo")
                character = {"type": "talking_photo", "talking_photo_id": tp.get("talking_photo_id")}
            else:
                raise PluginError("HeyGen needs an avatar id or a photo")
            w, h = DIMS.get(req.aspect, (1280, 720))
            body = {"video_inputs": [{"character": character, "voice": {"type": "audio", "audio_asset_id": audio_id}}],
                    "dimension": {"width": w, "height": h}}
            r = await client.post(f"{API}/v2/video/generate", headers=headers, json=body)
            raise_for(r, "HeyGen")
            vid = r.json()["data"]["video_id"]

            async def fetch():
                g = await client.get(f"{API}/v1/video_status.get", headers=headers, params={"video_id": vid})
                raise_for(g, "HeyGen status")
                return g.json().get("data", {})

            def done(d):
                return {"completed": True, "failed": False}.get(d.get("status"))

            res = await poll(fetch, done, interval=10, timeout=3600)
        await download(res["video_url"], req.out)
        return req.out, Usage(seconds=media.probe_duration(req.out))
