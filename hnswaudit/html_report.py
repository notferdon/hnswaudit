"""Self-contained HTML inspector (no network, no external assets). Data embedded as JSON.

Visual design: black, typographic, two-column long page (label rail + evidence column).
Typeface: TeX Gyre Heros Regular/Bold (GUST Font License, text in hnswaudit/fonts/), unmodified, inlined as base64 so the
report is standalone and offline. If the font files are absent the page falls back to the system Helvetica-class sans.
"""
import base64
import json
import os

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>hnswaudit report</title>
<style>
__FONTS__
:root{--bg:#000;--fg:#fff;--mut:#949494;--rule:#3a3a3a;--track:#262626}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 "TeX Gyre Heros","Helvetica Neue",Helvetica,Arimo,"Liberation Sans",Arial,sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased;text-size-adjust:100%}
.page{padding:0 clamp(20px,4vw,64px) 40px;--gap:clamp(32px,3vw,48px)}
[hidden]{display:none!important}
.top,.sec,.foot{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));column-gap:20px;row-gap:12px}
.top,.foot{padding:30px 0 18px;border-bottom:1px solid var(--rule)}
.foot{border-bottom:0;border-top:1px solid var(--rule);margin-top:var(--gap);padding:18px 0 0;color:var(--mut)}
.sec{margin-top:var(--gap);padding-top:22px;border-top:1px solid var(--rule)}
.sec.hero{margin-top:0;border-top:0;padding-top:var(--gap)}
.rail{grid-column:1/4;color:var(--mut);font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.sig{grid-column:1/4;color:var(--fg);font-weight:700;font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.col{grid-column:4/13;min-width:0}
.up,#status,.foot .mid{font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.top .mid,.foot .mid{grid-column:4/13;display:flex;flex-wrap:wrap;gap:4px 20px;justify-content:space-between}
.mut{color:var(--mut)}
h1{margin:0;font-size:clamp(28px,3vw,44px);font-weight:400;letter-spacing:-.03em;line-height:1.05;max-width:16em;text-wrap:balance}
.lede{padding-top:18px;max-width:65ch}
.note{padding-top:12px;max-width:65ch;color:var(--mut)}
.bar{display:grid;grid-template-columns:minmax(200px,22rem) minmax(0,1fr) 56px;align-items:center;gap:0 16px}
.bar .t{min-width:0}
.bar .tr{height:1px;background:var(--track)}
.bar .tr i{display:block;height:1px;background:var(--fg);min-width:2px}
.bar .n{text-align:right}
.bar.hl .t,.bar.hl .n{font-weight:700}
.bar.dim{color:var(--mut)}.bar.dim .tr i{background:var(--mut)}
.find{padding-top:0}
input[type=search]{background:transparent;color:var(--fg);border:0;border-bottom:1px solid var(--rule);border-radius:0;padding:4px 0;width:260px;max-width:100%;font:inherit;outline:0;-webkit-appearance:none}
input[type=search]::placeholder{color:var(--mut)}
input[type=search]:focus{border-bottom-color:var(--fg)}
.scroll{overflow-x:auto;padding-top:14px}
table{border-collapse:collapse;min-width:540px;width:100%}
th{color:var(--mut);font-weight:400;text-align:left;padding:0 16px 7px 6px;white-space:nowrap;border-bottom:1px solid var(--rule)}
td{padding:3px 16px 3px 6px;vertical-align:top;white-space:nowrap}
th.r,td.r{text-align:right}
td.w,th.w{width:100%}
tr.f{cursor:pointer;-webkit-tap-highlight-color:transparent}tr.f.tomb{color:var(--mut)}
tr.f.sel td{color:var(--fg)}tr.f.sel td:first-child{box-shadow:inset 2px 0 var(--fg)}
tr.f:focus{outline:0}tr.f:focus-visible{outline:1px solid var(--fg);outline-offset:1px}
.ev div{padding-top:2px}.ev .h{padding-top:0}
.ev .nb{display:flex;gap:16px;border-top:1px solid var(--rule);margin-top:4px;padding-top:3px}
.ev .nb span:first-child{flex:0 0 70px}.ev .nb span:last-child{flex:1}
details{border-top:1px solid var(--rule)}
details:last-child{border-bottom:1px solid var(--rule)}
summary{cursor:pointer;padding:5px 0;list-style:none;display:flex;justify-content:space-between}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";color:var(--mut)}
details[open] summary::after{content:"\2212"}
summary:focus{outline:0}summary:focus-visible{outline:1px solid var(--fg);outline-offset:2px}
details .in{padding:2px 0 12px;max-width:65ch;color:var(--mut)}
details .in p{margin:0 0 8px}details .in ul{margin:0 0 8px;padding-left:16px}details .in li{padding-bottom:3px}
.hash{word-break:break-all}
code{font:inherit}
@media (max-width:760px){.rail,.sig,.col,.top .mid,.foot .mid{grid-column:1/-1}.top,.foot{padding-top:20px}.sec{padding-top:20px}.sec.hero{padding-top:36px}.bar{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"t n" "tr tr";gap:3px 12px;align-items:baseline;padding-bottom:9px}.bar .t{grid-area:t}.bar .n{grid-area:n}.bar .tr{grid-area:tr;flex:none;width:auto}.ev .nb{max-width:none}}
@media (max-width:760px){.page{--gap:40px}}
</style></head><body><div class="page">
<div class="top"><div class="sig">FERDON / hnswaudit</div><div class="mid"><div class="mut" id="meta"></div><div id="status"></div></div></div>

<div class="sec hero"><div class="rail">Verdict</div><div class="col"><h1 id="head"></h1><div class="lede" id="lede"></div><div class="note" id="vnote"></div></div></div>

<div class="sec"><div class="rail">Settled</div><div class="col" id="settled"></div></div>

<div class="sec"><div class="rail" id="reach-l">Reach</div><div class="col"><div class="bars" id="reach"></div></div></div>

<div class="sec"><div class="rail" id="aff-l">Affected live IDs</div><div class="col">
<div><input type="search" id="q" placeholder="Filter by ID, label or class" aria-label="Filter affected IDs"> <span class="mut" id="cnt"></span> <span class="mut" id="trunc"></span></div>
<div class="scroll"><table><thead><tr><th>Class</th><th class="r">ID</th><th class="r">Label</th><th class="r">Level</th><th class="r">In-edges L0</th><th class="w">Why</th></tr></thead><tbody id="rows"></tbody></table></div>
</div></div>

<div class="sec" id="evsec" hidden><div class="rail">Selected</div><div class="col ev" id="ev"></div></div>

<div class="sec"><div class="rail">Records</div><div class="col" id="records"></div></div>

<div class="foot"><div class="sig">FERDON / hnswaudit</div><div class="mid"><div>Local file, no network</div><div id="foot"></div></div></div>

<script id="data" type="application/json">__DATA__</script>
<script>
const R=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const N=x=>(x===null||x===undefined)?'-':Number(x).toLocaleString('en-US');
const OK=R.status==='OK';
const DESC=!!R.persisted_observations;
const S=DESC?Object.assign({},R.summary,R.persisted_observations):(R.summary||{});
const O=R.operational;

/* header */
$('foot').textContent='hnswaudit '+R.version+' / SOUNDNESS.md';
$('meta').innerHTML='<span class="up">'+esc(R.layout||'?')+' layout</span> / '+esc(R.path||'');
$('status').textContent='status '+R.status;

/* verdict */
const U=S.unreachable_proven,T=S.tombstone_dependent,L=S.live;
let head,lede='',note='';
if(!OK){head='NO CERTIFICATE.';lede=R.status+(R.reason?': '+R.reason:'');
 note=DESC?'The persisted files are behind the store, so no per-ID verdict is issued. The counts below describe the files only and are not an index-health result.':'No per-ID verdict is issued for this input.';}
else if(U>0){head=N(U)+' live ID'+(U===1?' is':'s are')+' structurally unreachable.';
 lede=N(U)+' of '+N(L)+' live ID'+(U===1?' lies':'s lie')+' outside every graph search over these files.'+(T>0?' '+N(T)+' more are reachable only by routing through deleted nodes.':'');}
else if(T>0){head='No live ID is structurally unreachable.';lede=N(T)+' live ID'+(T===1?' depends':'s depend')+' on routing through deleted nodes.';}
else if(S.nodes===0){head='Empty index.';}
else{head='No structurally unreachable live IDs found.';}
$('head').textContent=head;
$('lede').textContent=lede;
if(OK)note='Not recall@k. Not an ef tuner. Not repair. A clean result would not mean a good index. Status OK means the files parsed and the settled gate passed, not that the index is healthy.';
$('vnote').textContent=note;

/* settled */
(function(){let h='';
 if(O&&O.sqlite==='NOT READ'){h='<div>Not read: '+esc(O.reason)+'</div>';}
 else if(O){const same=O.metadata_segment_seq===O.vector_segment_watermark;
  h='<div>'+N(O.pending_operations)+' pending operation'+(O.pending_operations===1?'':'s')+'</div>';
  if(O.pending_operations>0)h+='<div class="mut">'+esc(Object.entries(O.pending_by_op||{}).map(([k,v])=>k+' x'+v).join(', '))+' touching '+N(O.pending_id_count)+' ID(s): a sequence gap. The graph Chroma serves cannot be certified from the persisted files alone.</div>';
  h+='<div>vector seq '+N(O.vector_segment_watermark)+(same?' = ':' / ')+'metadata seq '+N(O.metadata_segment_seq)+(OK?'':' (store is not settled)')+'</div>';}
 else h='<div>'+esc(R.settled||'n/a')+'</div>';
 $('settled').innerHTML=h;})();

/* reach */
(function(){
 if(S.nodes===undefined){$('reach').innerHTML='<div class="mut">Not computed.</div>';return;}
 const lv=Math.max(L,1),nn=Math.max(S.nodes,1);
 const rows=[['All nodes',S.nodes,nn,0],['Live',L,nn,0],['Start envelope',S.envelope_size,nn,0],['Routing-reachable',S.reach0_size,nn,0],
  ['Reachable without tombstone routing',S.reach_live_only_size,nn,0],
  [DESC?'Live IDs unreachable in persisted files':'Live IDs unreachable (proven)',U,lv,OK&&U>0?1:0],['Live IDs reachable only via tombstones',T,lv,0]];
 let h=DESC?'<div class="mut" style="padding-bottom:8px"><span style="color:#fff">Descriptive only.</span> Persisted-file counts, not a verdict; the store is not settled.</div>':'';
 h+=rows.map(r=>'<div class="bar'+(r[3]?' hl':'')+(DESC&&r[0].startsWith('Live IDs')?' dim':'')+'"><div class="t">'+esc(r[0])+'</div><div class="tr">'+(r[1]>0?'<i style="width:'+(100*r[1]/r[2])+'%"></i>':'')+'</div><div class="n">'+N(r[1])+'</div></div>').join('');
 h+='<div class="mut" style="padding-top:8px;max-width:65ch">Bars are drawn to true proportion; a 2 px minimum marks any non-zero count; zero draws no mark. Entry node '+N(S.entry_internal)+(S.entry_deleted?' (tombstoned)':' (live)')+' / max level '+N(S.maxlevel)+' / layer-0 SCCs '+(S.scc_count===null||S.scc_count===undefined?'not computed (scipy not installed)':N(S.scc_count)+' (largest '+N(S.scc_largest)+')')+' / live nodes with zero layer-0 in-edges '+N(S.layer0_zero_in_degree_live)+'</div>';
 $('reach').innerHTML=h;})();

/* findings */
const F=DESC?(R.persisted_only_findings||[]):(R.findings||[]);
$('aff-l').textContent=(DESC?'Persisted observations':'Affected live IDs')+' ('+F.length+')';
let sel=null;
const shortWhy=f=>f.class==='UNREACHABLE_PROVEN'?(f.in_degree_layer0===0?'No incoming edges at layer 0':'Disconnected island'):'Reachable only via tombstones';
const clsName=f=>f.class==='UNREACHABLE_PROVEN'?'UNREACHABLE':'TOMBSTONE_DEP';
function draw(){const q=$('q').value.toLowerCase();
 const Lf=F.filter(f=>!q||(f.id+' '+f.label+' '+f.class+' '+f.class.replace(/_/g,' ')).toLowerCase().includes(q));
 $('cnt').textContent=q?Lf.length+' of '+F.length:'';
 $('rows').innerHTML=Lf.slice(0,500).map(f=>'<tr class="f '+(f.class==='UNREACHABLE_PROVEN'?'':'tomb')+(sel===f.internal?' sel':'')+'" tabindex="0" data-i="'+f.internal+'" aria-selected="'+(sel===f.internal)+'"><td>'+clsName(f)+'</td><td class="r">'+esc(f.id)+'</td><td class="r">'+f.label+'</td><td class="r">'+f.level+'</td><td class="r">'+f.in_degree_layer0+'</td><td class="w">'+esc(shortWhy(f))+'</td></tr>').join('')||'<tr><td colspan="6" class="mut">'+(F.length?'No match.':'None.')+'</td></tr>';
 document.querySelectorAll('tr.f').forEach(tr=>{tr.onclick=()=>pick(+tr.dataset.i);tr.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(+tr.dataset.i,true);}};});
 $('trunc').textContent=Lf.length>500?'First 500 rows shown; full list is in the JSON report.':'';}
function pick(i,kb){sel=i;try{history.replaceState(null,'','#id='+encodeURIComponent(F.find(x=>x.internal===i).id));}catch(e){}draw();show(F.find(x=>x.internal===i));if(kb){const r=document.querySelector('tr.f[data-i="'+i+'"]');if(r)r.focus({preventScroll:true});}}
function show(f){if(!f){$('evsec').hidden=true;return;}
 $('evsec').hidden=false;const nb=f.in_neighbours_layer0||[];
 $('ev').innerHTML='<div class="h">'+esc(f.id)+' / label '+f.label+' / internal #'+f.internal+' / level '+f.level+' / '+esc(f.class.replace(/_/g,' '))+'</div>'
  +'<div>'+esc(f.why.charAt(0).toUpperCase()+f.why.slice(1))+'.</div>'
  +'<div class="mut">'+(nb.length?'Layer-0 in-edges: first '+nb.length+' of '+f.in_degree_layer0+'. ':'')+'Out-degree at layer 0: '+f.out_degree_layer0+'.</div>'
  +(nb.length?nb.map(n=>'<div class="nb"><span>#'+n.internal+'</span><span>label '+n.label+' / '+(n.deleted?'tombstoned':'live')+' / '+(n.reachable?'reachable':'unreachable')+' &rarr; '+esc(f.id)+'</span></div>').join(''):'')
  +'<div class="mut">Whether Chroma get()/query() return this ID was not measured by this audit.</div>';}
$('q').oninput=draw;
const h0=(location.hash.match(/^#id=(.*)$/)||[])[1];
const f0=(h0&&F.find(x=>String(x.id)===decodeURIComponent(h0)))||F[0];
if(f0){sel=f0.internal;}
draw();if(f0)show(f0);

/* records */
const C=R.consistency||{};
const rec=[];
rec.push(['Consistency',Object.keys(C).length?'<ul>'+Object.entries(C).filter(([k,v])=>typeof v!=='object').map(([k,v])=>'<li>'+esc(k)+': <span style="color:#fff">'+esc(v)+'</span></li>').join('')+'</ul>':'<p>n/a</p>']);
rec.push(['Assumptions','<ul>'+(R.engine_assumptions||[]).map(a=>'<li>'+esc(a)+'</li>').join('')+'</ul>'+(R.snapshot_consistency?'<p>Snapshot consistency: '+esc(R.snapshot_consistency.note)+'</p>':'')]);
rec.push(['Not checked','<ul>'+(R.not_checked||[]).map(a=>'<li>'+esc(a)+'</li>').join('')+'</ul>'+(R.api_status?'<p>Chroma API status: '+esc(R.api_status)+'</p>':'')]);
rec.push(['What a pass does not mean','<p>"No unreachable IDs" says only that no live ID was proven to lie outside every graph search over these files. It is not a recall@k result, not a statement about ef, filters or any particular query, not a check of Chroma\'s non-graph query paths, and not a sign the index is a good ANN index. This report does not repair anything and is not a prevalence estimate. Reasoning: SOUNDNESS.md in the hnswaudit repository.</p>']);
if((R.anomalies||[]).length)rec.push(['Parser anomalies','<ul>'+R.anomalies.map(a=>'<li>'+esc(a)+'</li>').join('')+'</ul>']);
rec.push(['Full verdict text','<p>'+esc((S.verdict||'')+(R.reason?'  ['+R.reason+']':''))+'</p><p>hnswaudit '+esc(R.version)+' / audited in '+esc(R.elapsed_s)+' s / status '+esc(R.status)+'</p>']);
rec.push(['Inputs (SHA-256)','<ul>'+(R.inputs||[]).map(i=>'<li>'+esc(i.file)+' / '+N(i.bytes)+' bytes<div class="hash" style="color:#fff">'+esc(i.sha256)+'</div></li>').join('')+'</ul>']);
$('records').innerHTML=rec.map(r=>'<details><summary>'+esc(r[0])+'</summary><div class="in">'+r[1]+'</div></details>').join('');
</script></div></body></html>"""


def _fontface():
    """@font-face rules with the two bundled TeX Gyre Heros faces inlined; empty if the files are missing."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    out = []
    for fn, w in (("texgyreheros-regular.otf", 400), ("texgyreheros-bold.otf", 700)):
        try:
            with open(os.path.join(d, fn), "rb") as f:
                b = base64.b64encode(f.read()).decode()
        except OSError:
            return ""
        out.append('@font-face{font-family:"TeX Gyre Heros";font-weight:%d;font-style:normal;font-display:swap;'
                   'src:url(data:font/otf;base64,%s) format("opentype")}' % (w, b))
    return "\n".join(out)


def render(report):
    """Return the standalone HTML. Absolute input paths are reduced to their final component."""
    rep = dict(report)
    if rep.get("path"):
        rep["path"] = os.path.basename(str(rep["path"]).rstrip("/\\")) or "snapshot"
    data = json.dumps(rep, separators=(",", ":"), default=str).replace("</", "<\\/")
    return TEMPLATE.replace("__FONTS__", _fontface()).replace("__DATA__", data)
