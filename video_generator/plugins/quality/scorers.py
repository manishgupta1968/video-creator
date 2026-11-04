"""Automatic quality measurements used next to each take and by the Review Agent."""
from __future__ import annotations

from pathlib import Path

from ..base import QualityScorer
from ... import media


class FlickerScorer(QualityScorer):
    name = "flicker"
    env_keys: list[str] = []
    description = "Share of frames with sudden brightness jumps (lower is better)"

    def score(self, video: Path, references: list[Path]) -> dict[str, float]:
        return {"flicker": media.frame_diff_score(video)}


class FaceSimilarityScorer(QualityScorer):
    name = "face_similarity"
    env_keys: list[str] = []
    description = "How closely faces match the actor's photos (0–1; needs the [face] extra)"
    _app = None

    def is_configured(self):
        try:
            import insightface  # noqa: F401
            return True, "ok"
        except Exception:
            return False, "pip install 'video-generator[face]'"

    def _embed(self, img_path: Path):
        import numpy as np
        from PIL import Image
        if FaceSimilarityScorer._app is None:
            from insightface.app import FaceAnalysis
            app = FaceAnalysis(providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=-1, det_size=(640, 640))
            FaceSimilarityScorer._app = app
        img = np.array(Image.open(img_path).convert("RGB"))[:, :, ::-1]
        faces = FaceSimilarityScorer._app.get(img)
        if not faces:
            return None
        f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
        return f.normed_embedding

    def score(self, video: Path, references: list[Path]) -> dict[str, float]:
        import numpy as np
        refs = [e for e in (self._embed(p) for p in references[:4]) if e is not None]
        if not refs:
            return {}
        frames = media.sample_frames(video, video.parent / f"{video.stem}_faces", every=2, max_frames=5)
        sims = []
        for _, fp in frames:
            e = self._embed(fp)
            if e is not None:
                sims.append(max(float(np.dot(e, r)) for r in refs))
        return {"face_similarity": round(sum(sims) / len(sims), 3)} if sims else {}
