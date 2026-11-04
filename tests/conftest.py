import os
import shutil
from pathlib import Path

import pytest

KEYS = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "FAL_KEY", "ELEVENLABS_API_KEY",
        "HEYGEN_API_KEY", "RUNWAYML_API_SECRET", "LUMAAI_API_KEY", "KLING_ACCESS_KEY", "KLING_SECRET_KEY",
        "CARTESIA_API_KEY", "REPLICATE_API_TOKEN"]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own ~/.video-generator and no real API keys."""
    monkeypatch.setenv("VG_HOME", str(tmp_path / "vg"))
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def svc():
    from video_generator.services import Service
    return Service()


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    import fitz
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=960, height=540)
        page.insert_text((80, 200), f"Feature {i + 1}: weighs only 400 g", fontsize=36)
    out = tmp_path / "features_slides.pdf"
    doc.save(out)
    return out


@pytest.fixture
def sample_clip(tmp_path) -> Path:
    from video_generator import media
    out = tmp_path / "review.mp4"
    media.ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24", "-f", "lavfi", "-i", "sine=frequency=440",
             "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out))
    return out


@pytest.fixture
def sample_photo(tmp_path) -> Path:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (900, 900), (200, 170, 150))
    d = ImageDraw.Draw(img)
    for i in range(0, 900, 30):
        d.line([(i, 0), (900 - i, 900)], fill=(40, 30, 20), width=3)
    out = tmp_path / "priya_face.jpg"
    img.save(out)
    return out


@pytest.fixture
def sample_voice(tmp_path) -> Path:
    from video_generator import media
    out = tmp_path / "priya_voice.wav"
    media.ff("-f", "lavfi", "-i", "sine=frequency=220", "-t", "12", str(out))
    return out


requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
