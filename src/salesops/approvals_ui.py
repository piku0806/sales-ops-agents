"""Human-in-the-loop approval queue (FastAPI).

Reviewers see each queued action with the agent's reasoning, policy flags and the exact
arguments, can edit an email before approving it, and every decision is audited.

    python -m salesops ui    ->  http://127.0.0.1:8000
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from salesops import crm_db, governance
from salesops.config import get_settings

app = FastAPI(title="Sales Ops Agents · Approval Queue")


class Decision(BaseModel):
    reviewer: str
    note: str = ""
    args: dict | None = None


class RunRequest(BaseModel):
    account: str


@app.get("/api/accounts")
def accounts():
    s = get_settings()
    crm_db.init_db(s.crm_db)
    return crm_db.list_accounts(s.crm_db)


@app.get("/api/crm/{account}")
def crm_account(account: str):
    acct = crm_db.get_account(get_settings().crm_db, account)
    if not acct:
        raise HTTPException(404, "unknown account")
    return acct


@app.post("/api/runs")
async def start_run(req: RunRequest):
    from salesops.orchestrator import run_account_workflow

    try:
        return await run_account_workflow(req.account)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/approvals")
def list_approvals(status: str | None = None):
    return governance.ApprovalStore(get_settings().governance_db).list(status=status)


@app.post("/api/approvals/{aid}/approve")
async def approve(aid: str, d: Decision):
    if not d.reviewer.strip():
        raise HTTPException(400, "reviewer name is required")
    try:
        return await governance.approve(aid, d.reviewer, d.note, d.args)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/approvals/{aid}/reject")
def reject(aid: str, d: Decision):
    if not d.reviewer.strip():
        raise HTTPException(400, "reviewer name is required")
    try:
        return governance.reject(aid, d.reviewer, d.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/audit/{run_id}")
def audit(run_id: str):
    return governance.AuditLog(get_settings().audit_log).read(run_id)


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Approval Queue</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--muted:#5b6270;--line:#e3e6eb;--accent:#2f5bea;
--ok:#1a7f4b;--okbg:#e5f5ec;--warn:#9a5b00;--warnbg:#fff3dc;--bad:#b42318;--badbg:#fdecea;--code:#f1f3f6}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--ink:#e8eaee;--muted:#9aa1ad;--line:#2a2f3a;
--accent:#7b9bff;--ok:#4cc38a;--okbg:#12281d;--warn:#f0b35a;--warnbg:#2b2112;--bad:#ff8a80;--badbg:#2c1515;--code:#1f232c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);background:var(--card);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:18px;margin:0;flex:1}main{max-width:980px;margin:0 auto;padding:24px 16px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:28px 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:14px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.muted{color:var(--muted)}.sp{flex:1}
.badge{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);white-space:nowrap}
.b-external,.b-write_high{background:var(--warnbg);color:var(--warn);border-color:transparent}
.b-executed{background:var(--okbg);color:var(--ok);border-color:transparent}
.b-rejected{background:var(--badbg);color:var(--bad);border-color:transparent}
.flag{background:var(--warnbg);color:var(--warn);padding:6px 10px;border-radius:6px;margin-top:8px;font-size:14px}
label{font-size:13px;color:var(--muted);display:block;margin:10px 0 4px}
input,textarea,select{width:100%;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px 10px}
textarea{min-height:240px;font-family:ui-monospace,Menlo,monospace;font-size:13px}
button{font:inherit;border-radius:6px;padding:8px 14px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}button.danger{color:var(--bad)}
button:disabled{opacity:.5;cursor:wait}
pre{background:var(--code);padding:10px;border-radius:6px;overflow:auto;font-size:13px;margin:8px 0 0;white-space:pre-wrap}
.diff{font-family:ui-monospace,Menlo,monospace;font-size:14px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media (max-width:640px){.grid{grid-template-columns:1fr}}
.tl{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;border-left:2px solid var(--line);padding-left:12px}
.tl div{margin:3px 0}.ev{font-weight:600}
</style></head><body>
<header><h1>Sales Ops Agents · Approval Queue</h1>
<select id="acct" style="width:auto"></select><button class="primary" id="runBtn" onclick="runWorkflow()">Run workflow</button></header>
<main>
<div id="runMsg"></div>
<div class="card row"><label style="margin:0">Reviewer</label><input id="reviewer" placeholder="your name" style="max-width:240px"></div>
<h2>Pending approvals</h2><div id="pending"></div>
<h2>Decided</h2><div id="decided"></div>
<h2 id="auditTitle" style="display:none">Audit trail</h2><div id="audit"></div>
</main>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,opts){const r=await fetch(path,opts);const j=await r.json();if(!r.ok)throw new Error(j.detail||r.statusText);return j}
async function loadAccounts(){const a=await api('/api/accounts');$('#acct').innerHTML=a.map(x=>`<option>${esc(x.name)}</option>`).join('')}
async function runWorkflow(){const b=$('#runBtn');b.disabled=true;$('#runMsg').innerHTML='<div class="card muted">Agents running…</div>';
 try{const r=await api('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:$('#acct').value})});
 const flags=r.guardrail_flags.map(f=>`<div class="flag">⚑ ${esc(f.type)}: ${esc((f.matches||[f.reason]).join(', '))}</div>`).join('');
 $('#runMsg').innerHTML=`<div class="card"><div class="row"><b>Run ${esc(r.run_id)}</b><span class="muted">${esc(r.account)} · ${esc(r.model)}</span><span class="sp"></span>
 <button onclick="showAudit('${esc(r.run_id)}')">Audit trail</button></div><p>${esc(r.research_brief.summary||'')}</p>
 <div class="muted">${r.executed_actions.length} action(s) auto-executed · ${r.pending_approvals.length} queued for approval</div>${flags}</div>`;
 await refresh()}catch(e){$('#runMsg').innerHTML=`<div class="card flag">${esc(e.message)}</div>`}finally{b.disabled=false}}
async function card(it){const a=it.args, pending=it.status==='pending';let body='';
 if(it.tool==='send_email'){body=`<label>To</label><input value="${esc(a.to)}" disabled><label>Subject</label>
  <input id="s-${it.id}" value="${esc(a.subject)}" ${pending?'':'disabled'}><label>Body ${pending?'(editable before approval)':''}</label>
  <textarea id="b-${it.id}" ${pending?'':'disabled'}>${esc(a.body)}</textarea>`}
 else{let cur={};try{cur=await api('/api/crm/'+encodeURIComponent(a.account_name))}catch(e){}
  const rows=Object.entries(a).filter(([k])=>k!=='account_name').map(([k,v])=>`<div class="diff">${esc(k)}: <s class="muted">${esc(cur[k])}</s> → <b>${esc(v)}</b></div>`).join('');
  body=`<label>Proposed change</label>${rows}`}
 const flags=(it.flags||[]).map(f=>`<div class="flag">⚑ ${esc(f)}</div>`).join('');
 const actions=pending?`<label>Note to audit log</label><input id="n-${it.id}" placeholder="why you approved / rejected">
  <div class="row" style="margin-top:12px"><button class="primary" onclick="decide('${it.id}','approve')">Approve & execute</button>
  <button class="danger" onclick="decide('${it.id}','reject')">Reject</button><span class="sp"></span>
  <button onclick="showAudit('${esc(it.run_id)}')">Audit trail</button></div>`
  :`<div class="muted" style="margin-top:10px">${esc(it.status)} by ${esc(it.reviewer)} · ${esc(it.decided_at)}${it.rationale?' · “'+esc(it.rationale)+'”':''}</div>`;
 return `<div class="card"><div class="row"><b>${esc(it.tool)}</b><span class="muted">· ${esc(it.context.account_name)} · requested by ${esc(it.agent)}</span>
 <span class="sp"></span><span class="badge b-${esc(it.risk)}">${esc(it.risk)}</span>${pending?'':`<span class="badge b-${esc(it.status)}">${esc(it.status)}</span>`}</div>
 <div class="muted">${esc(it.reason)}</div>${it.context.rationale?`<label>Agent's reasoning</label><div>${esc(it.context.rationale)}</div>`:''}${flags}${body}${actions}</div>`}
async function refresh(){const all=await api('/api/approvals');const p=all.filter(x=>x.status==='pending'),d=all.filter(x=>x.status!=='pending');
 $('#pending').innerHTML=p.length?(await Promise.all(p.map(card))).join(''):'<div class="card muted">Nothing waiting. Run the workflow to generate actions.</div>';
 $('#decided').innerHTML=d.length?(await Promise.all(d.slice(0,10).map(card))).join(''):'<div class="card muted">No decisions yet.</div>'}
async function decide(id,kind){const reviewer=$('#reviewer').value.trim();if(!reviewer){alert('Enter your name as reviewer first');$('#reviewer').focus();return}
 const payload={reviewer,note:$('#n-'+id).value};const s=$('#s-'+id),b=$('#b-'+id);
 if(kind==='approve'&&b){const it=(await api('/api/approvals')).find(x=>x.id===id);
  if(s.value!==it.args.subject||b.value!==it.args.body)payload.args={...it.args,subject:s.value,body:b.value}}
 try{await api(`/api/approvals/${id}/${kind}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});await refresh()}
 catch(e){alert(e.message)}}
async function showAudit(run){const ev=await api('/api/audit/'+encodeURIComponent(run));$('#auditTitle').style.display='';
 $('#audit').innerHTML=`<div class="card"><div class="muted">Run ${esc(run)}</div><div class="tl">${ev.map(e=>{const {ts,run_id,event,...rest}=e;
 return `<div><span class="muted">${esc(ts.slice(11,19))}</span> <span class="ev">${esc(event)}</span> ${esc(JSON.stringify(rest).slice(0,160))}</div>`}).join('')}</div></div>`;
 $('#audit').scrollIntoView({behavior:'smooth'})}
loadAccounts();refresh();
</script></body></html>"""
