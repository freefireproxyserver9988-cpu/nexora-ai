import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
DATA = Path(os.getenv("NEXORA_DATA", "./data")).resolve(); DATA.mkdir(parents=True, exist_ok=True)
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg"); FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "500")); MAX_REF_SEC = int(os.getenv("MAX_REF_SECONDS", "180"))
MAX_RES = int(os.getenv("MAX_EXPORT_RES", "2160")); WORKERS = int(os.getenv("RENDER_WORKERS", "1"))
PRESET = os.getenv("X264_PRESET", "veryfast"); SCENE_TH = float(os.getenv("SCENE_THRESHOLD", "0.3"))
TOKEN = os.getenv("NEXORA_TOKEN", ""); ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "").split(",") if o]
FONT = os.getenv("FONT_FILE", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
