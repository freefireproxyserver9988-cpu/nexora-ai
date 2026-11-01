import json, re, shutil, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import analysis, config as C, render
from db import q

def auth(r: Request):
    if C.TOKEN and (r.headers.get("x-token") or r.query_params.get("token")) != C.TOKEN: raise HTTPException(401, "Invalid token")
app = FastAPI(title="NEXORA AI API", dependencies=[Depends(auth)])
if C.ORIGINS: app.add_middleware(CORSMiddleware, allow_origins=C.ORIGINS, allow_methods=["*"], allow_headers=["*"])
EXT = {"video": {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"}, "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp"}, "audio": {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}}
ana, pool = ThreadPoolExecutor(2), ThreadPoolExecutor(C.WORKERS)
q("update jobs set status='error',error='Server restarted' where status in ('queued','running')")
q("update projects set status='error',error='Server restarted' where status='analyzing'")

def proj(pid):
    p = q("select * from projects where id=?", (pid,), True)
    if not p: raise HTTPException(404, "Project not found")
    return p
def pdir(pid): d = C.DATA / "projects" / pid; d.mkdir(parents=True, exist_ok=True); return d
def save(u: UploadFile, kinds, d: Path):
    ext = Path(u.filename or "").suffix.lower()
    if not any(ext in EXT[k] for k in kinds): raise HTTPException(415, f"Unsupported file type {ext or '(none)'}")
    dest = d / (uuid.uuid4().hex + ext); n = 0
    with dest.open("wb") as f:
        while c := u.file.read(1 << 20):
            n += len(c)
            if n > C.MAX_MB << 20: f.close(); dest.unlink(missing_ok=True); raise HTTPException(413, "File too large")
            f.write(c)
    return dest
def readable(dest):
    try: return analysis.probe(dest)
    except Exception: dest.unlink(missing_ok=True); raise HTTPException(422, "Could not read this file (unsupported codec/format?)")

class NewP(BaseModel): name: str = "Untitled"
class Scene(BaseModel):
    dur: float = Field(ge=.3, le=30); fx: str = Field("auto", pattern="^(auto|zin|zout|none)$"); sp: float = Field(1, ge=.25, le=4); media: str
class RenderReq(BaseModel):
    mode: str = "smart"; res: int = 1080; aspect: str = "9:16"; fps: int = 30; text: str = ""; music: bool = False; scenes: List[Scene]

@app.get("/api/health")
def health():
    import subprocess; return {"ok": True, "ffmpeg": subprocess.run([C.FFMPEG, "-version"], capture_output=True, text=True).stdout.split("\n")[0]}
@app.post("/api/projects")
def new(b: NewP):
    pid = uuid.uuid4().hex[:12]; q("insert into projects values(?,?,?,?,?,?,?,?,?)", (pid, b.name[:60], time.time(), "created", 0, "", None, None, None)); pdir(pid); return {"id": pid}
@app.get("/api/projects")
def lst(): return q("select id,name,created,status,(select id from jobs j where j.pid=p.id and j.status='done' order by created desc limit 1) as job from projects p order by created desc")
@app.get("/api/projects/{pid}")
def get(pid: str):
    p = proj(pid); p["blueprint"] = json.loads(p["blueprint"]) if p["blueprint"] else None; p.pop("ref")
    p["media"] = q("select id,name,kind,w,h,dur,dup,faces from media where pid=? and kind!='audio'", (pid,)); return p
@app.delete("/api/projects/{pid}")
def rm(pid: str):
    proj(pid); shutil.rmtree(C.DATA / "projects" / pid, ignore_errors=True)
    for t in ("media", "jobs"): q(f"delete from {t} where pid=?", (pid,))
    q("delete from projects where id=?", (pid,)); return {"ok": True}

@app.post("/api/projects/{pid}/reference")
def ref(pid: str, file: UploadFile = File(...)):
    proj(pid); dest = save(file, ["video"], pdir(pid)); readable(dest)
    q("update projects set status='analyzing',progress=1,stage='Queued',error=null,ref=? where id=?", (str(dest), pid))
    def job():
        cb = lambda p, s: q("update projects set progress=?,stage=? where id=?", (p, s, pid))
        try:
            bp = analysis.analyze_ref(dest, cb)
            q("update projects set status='analyzed',progress=100,stage='Analysis complete',blueprint=? where id=?", (json.dumps(bp), pid))
        except Exception as e: q("update projects set status='error',error=?,stage='Failed' where id=?", (str(e)[:300], pid))
    ana.submit(job); return {"ok": True}

@app.post("/api/projects/{pid}/media")
def media(pid: str, file: UploadFile = File(...)):
    proj(pid); dest = save(file, ["video", "image"], pdir(pid)); m = readable(dest)
    if m["kind"] == "audio": dest.unlink(missing_ok=True); raise HTTPException(422, "Not a photo or video")
    h = analysis.phash(dest, m["kind"]); dup = int(bool(h) and any(o["hash"] and sum(a != b for a, b in zip(h, o["hash"])) <= 4 for o in q("select hash from media where pid=? and kind!='audio'", (pid,))))
    fc = analysis.faces(dest, m["kind"]); mid = uuid.uuid4().hex[:12]
    q("insert into media values(?,?,?,?,?,?,?,?,?,?,?)", (mid, pid, (file.filename or "")[:80], str(dest), m["kind"], m["w"], m["h"], m["dur"], h, dup, fc))
    return {"id": mid, "kind": m["kind"], "w": m["w"], "h": m["h"], "duration": m["dur"], "dup": bool(dup), "faces": fc, "orientation": "portrait" if m["w"] < m["h"] * .95 else "landscape" if m["w"] > m["h"] * 1.05 else "square"}

@app.post("/api/projects/{pid}/music")
def music(pid: str, file: UploadFile = File(...)):
    proj(pid); dest = save(file, ["audio", "video"], pdir(pid)); m = readable(dest)
    if not m["audio"]: dest.unlink(missing_ok=True); raise HTTPException(422, "No audio track found")
    b = analysis.beats(dest); q("delete from media where pid=? and kind='audio'", (pid,))
    q("insert into media values(?,?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex[:12], pid, (file.filename or "")[:80], str(dest), "audio", 0, 0, m["dur"], json.dumps(b), 0, None))
    return {"beats": b, "bpm": analysis.bpm(b), "duration": m["dur"]}

def run_job(jid):
    j = q("select * from jobs where id=?", (jid,), True); P = json.loads(j["params"]); pid = j["pid"]; t0 = time.time()
    def upd(p, s):
        if q("select cancel from jobs where id=?", (jid,), True)["cancel"]: raise render.Cancelled()
        q("update jobs set progress=?,stage=?,eta=? where id=?", (round(p, 1), s, int((time.time() - t0) * (100 - p) / p) if p > 3 else None, jid))
    try:
        q("update jobs set status='running' where id=?", (jid,)); upd(0, "Preparing")
        M = {m["id"]: m for m in q("select * from media where pid=?", (pid,))}; bp = json.loads(proj(pid)["blueprint"] or "{}")
        items = [M[s["media"]] for s in P["scenes"]]; sc = bp.get("scenes", []); rgbs = [sc[i]["rgb"] if i < len(sc) else [128] * 3 for i in range(len(items))]
        mus = next((m for m in M.values() if m["kind"] == "audio"), None) if P["music"] else None
        beats = json.loads(mus["hash"]) if mus else bp.get("beats", [])
        work = pdir(pid) / ("w" + jid); work.mkdir(); out = pdir(pid) / f"{jid}.mp4"
        try: render.render(P, items, rgbs, mus["path"] if mus else None, beats, work, out, upd)
        finally: shutil.rmtree(work, ignore_errors=True)
        q("update jobs set status='done',progress=100,stage='Done',eta=0,out=? where id=?", (str(out), jid))
    except render.Cancelled: q("update jobs set status='cancelled',stage='Cancelled' where id=?", (jid,))
    except Exception as e: q("update jobs set status='error',error=?,stage='Failed' where id=?", (str(e)[-400:], jid))

@app.post("/api/projects/{pid}/render")
def rend(pid: str, b: RenderReq):
    proj(pid)
    if b.mode not in ("exact", "cine", "smart", "manual") or b.res not in (720, 1080, 1440, 2160) or b.res > C.MAX_RES or b.aspect not in ("9:16", "16:9", "1:1") or b.fps not in (30, 60): raise HTTPException(422, "Invalid export settings")
    if not 1 <= len(b.scenes) <= 60: raise HTTPException(422, "1–60 scenes required")
    ids = {m["id"] for m in q("select id from media where pid=? and kind!='audio'", (pid,))}
    if any(s.media not in ids for s in b.scenes): raise HTTPException(422, "A scene references media that was not uploaded")
    jid = uuid.uuid4().hex[:12]; q("insert into jobs values(?,?,?,?,?,?,?,?,?,?,?)", (jid, pid, time.time(), "queued", 0, "Queued", None, None, None, b.model_dump_json(), 0))
    pool.submit(run_job, jid); return {"id": jid}

@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = q("select id,pid,status,progress,stage,eta,error from jobs where id=?", (jid,), True)
    if not j: raise HTTPException(404, "Job not found")
    return j
@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str): q("update jobs set cancel=1 where id=? and status in ('queued','running')", (jid,)); return {"ok": True}
@app.get("/api/jobs/{jid}/video")
def video(jid: str, download: int = 0):
    j = q("select * from jobs where id=?", (jid,), True)
    if not j or j["status"] != "done" or not Path(j["out"]).exists(): raise HTTPException(404, "Video not ready")
    nm = re.sub(r"\W+", "-", proj(j["pid"])["name"]).strip("-") or "nexora"
    return FileResponse(j["out"], media_type="video/mp4", filename=f"NEXORA-{nm}.mp4" if download else None)

FRONT = Path(__file__).resolve().parent / "static"
if FRONT.exists(): app.mount("/", StaticFiles(directory=FRONT, html=True), name="web")
