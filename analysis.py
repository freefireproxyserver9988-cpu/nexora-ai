"""Real media analysis: ffprobe + FFmpeg scene detection + numpy signal processing. No external AI API."""
import json, re, subprocess
import numpy as np
from config import FFMPEG, FFPROBE, SCENE_TH, MAX_REF_SEC

def probe(p):
    o = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(p)], capture_output=True, text=True, timeout=60)
    if o.returncode: raise ValueError("Unreadable media file")
    j = json.loads(o.stdout); v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    audio = any(s["codec_type"] == "audio" for s in j["streams"]); fmt = j["format"].get("format_name", "")
    d = float(j["format"].get("duration") or 0); w = h = 0
    if v:
        w, h = int(v["width"]), int(v["height"]); rot = int((v.get("tags") or {}).get("rotate", 0) or 0)
        for sd in v.get("side_data_list", []): rot = int(sd.get("rotation", rot))
        if abs(rot) % 180 == 90: w, h = h, w
    kind = "audio" if not v else "photo" if ("image2" in fmt or "_pipe" in fmt or d == 0) else "video"
    return dict(w=w, h=h, dur=d if kind != "photo" else 0, audio=audio, kind=kind, video=bool(v))

def beats(p):
    try:
        r = subprocess.run([FFMPEG, "-v", "error", "-i", str(p), "-t", "300", "-vn", "-ac", "1", "-ar", "22050", "-f", "s16le", "-"], capture_output=True, timeout=300)
        x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768; sr = 22050
        if x.size < sr: return []
        h = 512; n = x.size // h; E = (x[:n * h].reshape(n, h) ** 2).mean(1); out = []; last = -1
        for i in range(1, n):
            m = E[max(0, i - 43):i].mean(); t = i * h / sr
            if E[i] > 1.6 * m and E[i] > E[i - 1] and E[i] > 1e-6 and t - last > .25: out.append(round(t, 3)); last = t
        return out
    except Exception: return []

def bpm(b): return int(round(60 / float(np.median(np.diff(b))))) if len(b) >= 4 else 0

def _frame(p, kind, extra):
    ss = ["-ss", "0.1"] if kind == "video" else []
    return subprocess.run([FFMPEG, "-v", "error", *ss, "-i", str(p), "-frames:v", "1", *extra], capture_output=True, timeout=60).stdout

def phash(p, kind):
    b = np.frombuffer(_frame(p, kind, ["-vf", "scale=8:8,format=gray", "-f", "rawvideo", "-"]), np.uint8)
    return "".join("1" if v > b.mean() else "0" for v in b) if b.size == 64 else ""

def faces(p, kind):  # optional: needs opencv-python-headless; returns None if unavailable
    try:
        import cv2
        im = cv2.imdecode(np.frombuffer(_frame(p, kind, ["-vf", "scale=480:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]), np.uint8), cv2.IMREAD_GRAYSCALE)
        return int(len(cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml").detectMultiScale(im, 1.1, 5)))
    except Exception: return None

def analyze_ref(p, cb):
    m = probe(p)
    if not m["video"] or m["kind"] == "photo": raise ValueError("The reference must be a video")
    d, W, H = m["dur"], m["w"], m["h"]
    if d > MAX_REF_SEC: raise ValueError(f"Reference is longer than {MAX_REF_SEC}s")
    cb(10, "Detecting scene cuts")
    r = subprocess.run([FFMPEG, "-i", str(p), "-vf", f"select='gt(scene,{SCENE_TH})',showinfo", "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    cl = [0.0]
    for c in sorted(set(float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stderr))):
        if c - cl[-1] > .4 and d - c > .3: cl.append(c)
    cb(40, "Sampling color and motion")
    r = subprocess.run([FFMPEG, "-v", "error", "-i", str(p), "-vf", "fps=4,scale=32:18", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=900)
    fr = np.frombuffer(r.stdout, np.uint8); n = fr.size // (576 * 3); fr = fr[:n * 576 * 3].reshape(n, 576, 3).astype(np.float32)
    avg = fr.mean(1); diff = np.r_[0, np.abs(np.diff(fr, axis=0)).mean((1, 2))] if n > 1 else np.zeros(n)
    scenes = []
    for i, s in enumerate(cl):
        e = cl[i + 1] if i + 1 < len(cl) else d; a = int(s * 4); b = max(a + 1, int(e * 4))
        rgb = avg[a:b].mean(0) if avg[a:b].size else avg.mean(0); mo = diff[a:b][1:]
        scenes.append(dict(s=round(s, 3), e=round(e, 3), dur=round(e - s, 3), rgb=[int(v) for v in rgb], mo=round(float(mo.mean()) if mo.size else 0, 2), fx="auto", sp=1, need="video" if e - s >= 2.5 else "photo"))
    cb(80, "Analyzing audio beats"); bt = beats(p) if m["audio"] else []
    ratio = W / H; ar = "9:16" if ratio < .7 else "16:9" if ratio > 1.5 else "1:1" if abs(ratio - 1) < .12 else "9:16"
    lab = {"9:16": "9:16 vertical", "16:9": "16:9 landscape", "1:1": "1:1 square"}[ar] if ratio < .7 or ratio > 1.5 or abs(ratio - 1) < .12 else f"{W}x{H}"
    return dict(info=dict(d=round(d, 2), w=W, h=H, lab=lab, ar=ar, thr=SCENE_TH, step=.25), beats=bt, bpm=bpm(bt), scenes=scenes)
