/* NEXORA AI — backend integration. Loaded after the UI script; replaces the browser-only engine with server APIs. */
const API=(window.NEXORA_API||"").replace(/\/$/,""),TK=window.NEXORA_TOKEN?"token="+encodeURIComponent(window.NEXORA_TOKEN):"";
const sleep=ms=>new Promise(r=>setTimeout(r,ms)),esc=s=>String(s).replace(/[&<>"']/g,c=>"&#"+c.charCodeAt(0)+";"),withTk=u=>u+(TK?(u.includes("?")?"&":"?")+TK:"");
async function J(u,o={}){const r=await fetch(API+u,{...o,headers:{...(window.NEXORA_TOKEN?{"X-Token":window.NEXORA_TOKEN}:{}),...(o.headers||{})}});let b={};try{b=await r.json()}catch(e){}
if(!r.ok)throw new Error(Array.isArray(b.detail)?b.detail.map(x=>x.msg).join("; "):b.detail||r.statusText);return b}
const post=(u,b)=>J(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
const up=(u,f)=>{const fd=new FormData();fd.append("file",f);return J(u,{method:"POST",body:fd})};
async function ensure(){if(!S.pid)S.pid=(await post("/api/projects",{name:($("#txt").value||"Untitled").slice(0,60)})).id;return S.pid}
async function analyze(file){go(2);say("Uploading to the NEXORA server…");if(S.refURL)URL.revokeObjectURL(S.refURL);S.refURL=URL.createObjectURL(file);
try{const pid=await ensure();$("#at").textContent="Uploading…";await up(`/api/projects/${pid}/reference`,file);
for(;;){const p=await J(`/api/projects/${pid}`);$("#ap").style.width=p.progress+"%";$("#at").textContent=p.stage;
if(p.status=="error")throw new Error(p.error);if(p.status=="analyzed"){const b=p.blueprint;S.bp=b.scenes;S.info=b.info;S.beats=b.beats;break}await sleep(800)}
$("#ar").value=S.info.ar;autoAssign();stats();say(`Blueprint ready: ${S.bp.length} scenes. Now add ${S.bp.length} photos or clips.`)}catch(e){$("#at").textContent="Failed: "+e.message;say("Analysis failed: "+e.message)}}
const _add=addMedia;
addMedia=async function(files){const n0=S.media.length;await _add(files);const fresh=S.media.slice(n0);
try{const pid=await ensure();for(const m of fresh){say("Uploading "+m.name+"…");const f=files.find(x=>x.name==m.name),r=await up(`/api/projects/${pid}/media`,f);m.sid=r.id;m.dup=r.dup;m.faces=r.faces}say(`${S.media.length} file(s) uploaded.`)}
catch(e){say("Upload failed: "+e.message);fresh.forEach(m=>{if(!m.sid)S.media.splice(S.media.indexOf(m),1)})}autoAssign();chk();paintLib();if(!$$(".pg")[4].hidden)paint()};
$("#dM").ondrop=e=>{e.preventDefault();$("#dM").classList.remove("ov");addMedia([...e.dataTransfer.files])};
$("#fMu").onchange=async e=>{const f=e.target.files[0];if(!f)return;$("#mu").textContent="Uploading…";
try{const r=await up(`/api/projects/${await ensure()}/music`,f);S.music={server:1};S.mbeats=r.beats;$("#mu").textContent=r.beats.length?`${r.beats.length} beats · ~${r.bpm} BPM`:"loaded";paint()}catch(er){$("#mu").textContent=er.message}};
async function render(){
if(!S.pid||!S.bp.length)return say("Add a reference video first.");
const sc=S.bp.map((s,i)=>({dur:s.dur,fx:s.fx,sp:s.sp,media:(S.media.find(m=>m.id==S.asg[i])||{}).sid}));
if(sc.some(s=>!s.media))return say("Some scenes still need uploaded media — see the checklist.");
$("#rb").disabled=true;$("#cb").hidden=false;$("#res2").hidden=true;rp(0,"Queued…");let job;
try{job=await post(`/api/projects/${S.pid}/render`,{mode:$("#mode").value,res:+$("#res").value,aspect:$("#ar").value,fps:+$("#fps").value,text:$("#txt").value.trim(),scenes:sc,music:!!S.music})}
catch(e){$("#rb").disabled=false;$("#cb").hidden=true;rp(0,"Failed: "+e.message);return}
$("#cb").onclick=()=>J(`/api/jobs/${job.id}/cancel`,{method:"POST"});
try{for(;;){const j=await J(`/api/jobs/${job.id}`);rp(j.progress,`${Math.floor(j.progress)}% · ${j.eta!=null?"~"+j.eta+"s left · ":""}${j.stage}`);
if(j.status=="done"){const u=withTk(`${API}/api/jobs/${job.id}/video`),dl=withTk(`${API}/api/jobs/${job.id}/video?download=1`);S.out={url:u};say("Your video is ready.");
const r=$("#res2");r.hidden=false;r.innerHTML=`<video id=ov src="${u}" controls playsinline style="width:100%;max-height:70vh"></video><div class=row style="border:0"><a class=btn style="text-decoration:none" href="${dl}">⇩ Download MP4</a><button class="btn s" onclick="share()">Share</button><button class="btn s" onclick="ba(this)">Before / After</button><button class="btn s" onclick="render()">Generate again</button></div><small>Saved to Recent Projects.</small>`;break}
if(j.status=="error"){rp(0,"Failed: "+j.error);break}if(j.status=="cancelled"){rp(0,"Rendering cancelled.");break}await sleep(1000)}}catch(e){rp(0,"Lost connection: "+e.message)}
$("#rb").disabled=false;$("#cb").hidden=true}
$("#rb").onclick=render;
async function share(){try{const b=await(await fetch(S.out.url)).blob(),f=new File([b],"nexora.mp4",{type:"video/mp4"});if(navigator.canShare&&navigator.canShare({files:[f]}))await navigator.share({files:[f],title:"NEXORA video"});else say("Sharing isn’t supported here — use Download.")}catch(e){}}
async function recent(){let l=[];try{l=await J("/api/projects")}catch(e){$("#rec").innerHTML=`<span class=bad>Can’t reach the server: ${esc(e.message)}</span>`;return}
$("#rec").innerHTML=l.length?l.map(p=>`<div class=row><b>${esc(p.name)}</b><span class=mut>${new Date(p.created*1000).toLocaleString()} · ${esc(p.status)}</span>${p.job?`<a class=btn style="padding:6px 12px;text-decoration:none" href="${withTk(`${API}/api/jobs/${p.job}/video?download=1`)}">Download</a>`:""}<a href="#" onclick="delProj('${esc(p.id)}');return false">Delete</a></div>`).join(""):'<span class=mut>No saved projects yet.</span>'}
async function delProj(id){await J("/api/projects/"+id,{method:"DELETE"});if(S.pid==id)S.pid=null;recent()}
