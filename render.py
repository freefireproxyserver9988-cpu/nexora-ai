"""Real FFmpeg renderer: per-scene zoom/speed/grade -> xfade transitions -> text + audio mux, with live progress."""
import re, subprocess
from pathlib import Path
from config import FFMPEG, FONT, PRESET
import analysis

class Cancelled(Exception): pass
TR = ["fade", "slideleft", "circleopen", "dissolve", "wipeleft", "zoomin"]

def size(res, ar):
    a, b = map(int, ar.split(":"))
    w, h = (res, round(res * b / a)) if a < b else (round(res * a / b), res)
    return w // 2 * 2, h // 2 * 2

def snap(d, beats):
    out, acc, prev = [], 0, 0
    for i, v in enumerate(d):
        acc += v; t = acc
        if i < len(d) - 1:
            nb = min(beats, key=lambda b: abs(b - t))
            if abs(nb - t) < .35: t = nb
        o = max(.5, t - prev); prev += o; out.append(o)
    return out

def grade(rgb):  # match the reference scene's color cast and brightness (approximation)
    m = sum(rgb) / 3; t = [max(-.25, min(.25, (c - m) / 255 * 1.2)) for c in rgb]; br = max(-.1, min(.1, (m - 128) / 255 * .25))
    return f"colorbalance=rm={t[0]:.3f}:gm={t[1]:.3f}:bm={t[2]:.3f},eq=brightness={br:.3f}:saturation=1.1"

def seg_cmd(it, out, W, H, fps, dur, fx, sp, rgb, gr, bars):
    z0, z1 = (1, 1.15) if fx == "zin" else (1.15, 1) if fx == "zout" else (1, 1); n = max(2, round(dur * fps))
    if it["kind"] == "photo":
        vf = f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},zoompan=z='{z0}+({z1}-{z0})*on/{n}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={n}:s={W}x{H}:fps={fps}"
    else:
        z = f"({z0}+({z1}-{z0})*t/{dur:.3f})"
        vf = f"setpts=PTS/{sp},tpad=stop_mode=clone:stop_duration=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},scale=w='iw*{z}':h='ih*{z}':eval=frame,crop={W}:{H},fps={fps}"
    if gr: vf += "," + grade(rgb)
    if bars: vf += f",drawbox=x=0:y=0:w=iw:h=ih*0.09:color=black:t=fill,drawbox=x=0:y=ih*0.91:w=iw:h=ih*0.09:color=black:t=fill"
    vf += ",setsar=1,format=yuv420p"
    return [FFMPEG, "-y", "-v", "error", "-progress", "pipe:1", "-nostats", "-i", it["path"], "-vf", vf, "-t", f"{dur:.3f}", "-r", str(fps), "-an", "-c:v", "libx264", "-preset", PRESET, "-crf", "20", str(out)]

def run(cmd, total, on):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in p.stdout:
            if line.startswith("out_time_us="):
                try: on(min(1.0, max(0, int(line.split("=")[1])) / 1e6 / total))
                except ValueError: pass
        p.wait()
    except BaseException: p.kill(); raise
    if p.returncode: raise RuntimeError("ffmpeg failed: " + p.stderr.read()[-300:])

def render(P, items, rgbs, music, beats, work, out, upd):
    mode, fps = P["mode"], P["fps"]; W, H = size(P["res"], P["aspect"]); d = [s["dur"] for s in P["scenes"]]
    if mode == "smart" and beats: d = snap(d, beats)
    n = len(d); xf = 0 if mode == "exact" or n < 2 else min(.3, min(d) / 2); T = sum(d)
    L = [d[i] + (xf if i < n - 1 else 0) for i in range(n)]; tot = sum(L); done = 0; segs = []
    for i, s in enumerate(P["scenes"]):
        fx = s["fx"]
        if fx == "auto": fx = ("zin" if i % 2 == 0 else "zout") if mode in ("cine", "smart") else "none"
        seg = Path(work) / f"s{i}.mp4"
        run(seg_cmd(items[i], seg, W, H, fps, L[i], fx, s["sp"], rgbs[i], mode != "manual", mode == "cine"), L[i],
            lambda f, i=i, b=done: upd((b + f * L[i]) / tot * 80, f"Rendering scene {i+1}/{n}"))
        done += L[i]; segs.append(seg)
    upd(80, "Assembling timeline")
    ins = [x for sg in segs for x in ("-i", str(sg))]
    ins += ["-stream_loop", "-1", "-i", music] if music else ["-f", "lavfi", "-t", f"{T:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    if xf:
        f, prev, acc = "", "[0:v]", 0
        for k in range(1, n):
            acc += d[k - 1]; tr = ("fade" if k % 2 else "dissolve") if mode in ("cine", "manual") else TR[(k - 1) % len(TR)]
            f += f"{prev}[{k}:v]xfade=transition={tr}:duration={xf:.3f}:offset={acc:.3f}[x{k}];"; prev = f"[x{k}]"
    else:
        f = "".join(f"[{k}:v]" for k in range(n)) + f"concat=n={n}:v=1:a=0[xc];"; prev = "[xc]"
    t = re.sub(r"[^A-Za-z0-9 .,!?\-]", "", P.get("text", ""))[:40].strip()
    if t and Path(FONT).exists():
        fs = int(min(H * .07, W * .9 / (len(t) * .62)))
        f += f"{prev}drawtext=fontfile={FONT}:text='{t}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=h*0.78:alpha='min(1,3.8-t)':enable='between(t,0.3,3.8)'[v];"
    else: f += f"{prev}null[v];"
    f += f"[{n}:a]atrim=0:{T:.3f},afade=t=in:d=0.4,afade=t=out:st={max(0, T-.8):.3f}:d=0.8[a]"
    run([FFMPEG, "-y", "-v", "error", "-progress", "pipe:1", "-nostats", *ins, "-filter_complex", f, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", PRESET, "-crf", "20",
         "-r", str(fps), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{T:.3f}", str(out)], T, lambda fr: upd(80 + fr * 19, "Encoding final video"))
    upd(99, "Verifying output")
    if analysis.probe(out)["dur"] < T - 1: raise RuntimeError("Output file is shorter than expected")
