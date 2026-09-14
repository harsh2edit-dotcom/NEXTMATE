"""
XYVEN ADS BOT — FastAPI server.
Webhook + verification website + admin dashboard.
"""
import os
import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import bot as b

ADMIN_USER = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "xyven-admin-2024")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "xyven-session-secret-change-me")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "xyven-hook-secret-change-me")
VERIFY_TTL = int(os.environ.get("VERIFY_SESSION_TTL_MINUTES", "30"))

verify_ser = URLSafeTimedSerializer(b.VERIFY_SECRET, salt="xyven-verify")
admin_ser  = URLSafeTimedSerializer(SESSION_SECRET,    salt="xyven-admin")

BOT_REF: dict = {"bot": None, "dp": None, "scheduler": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await b.init_db()
    bot = b.build_bot()
    dp = b.build_dispatcher()
    BOT_REF["bot"], BOT_REF["dp"] = bot, dp
    await b.set_bot_commands(bot)

    base = b.WEBHOOK_BASE_URL
    if base:
        await bot.set_webhook(
            f"{base}/webhook/{WEBHOOK_SECRET}",
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "my_chat_member"],
        )
        b.log.info("Webhook set")
    else:
        b.log.warning("WEBHOOK_BASE_URL not set — webhook disabled")

    BOT_REF["scheduler"] = b.start_scheduler(bot)

    try:
        yield
    finally:
        if BOT_REF["scheduler"]: BOT_REF["scheduler"].shutdown(wait=False)
        try: await bot.delete_webhook(drop_pending_updates=False)
        except Exception: pass
        await bot.session.close()


app = FastAPI(title="XYVEN ADS BOT", lifespan=lifespan)


from aiogram.types import Update

@app.post("/webhook/{secret}")
async def webhook(secret: str, request: Request):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")
    data = await request.json()
    update = Update.model_validate(data, context={"bot": BOT_REF["bot"]})
    await BOT_REF["dp"].feed_update(BOT_REF["bot"], update)
    return {"ok": True}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


# ════════════════════════════════════════════════════════════════════
# VERIFICATION WEBSITE
# ════════════════════════════════════════════════════════════════════
VERIFY_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XYVEN • Device Verification</title>
<style>
:root{--bg:#0b1220;--card:#131b2c;--line:#22304a;--txt:#e6edf7;--mut:#8ca0bd;--acc:#2f81f7;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444}
*{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
body{background:radial-gradient(1200px 600px at 50% -10%,#1a2942 0%,var(--bg) 60%);color:var(--txt);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;max-width:520px;width:100%;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#2f81f7,#7c3aed);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:18px}
h1{font-size:20px;font-weight:700}
.sub{color:var(--mut);font-size:13px;margin-bottom:20px}
.box{background:#0e1626;border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px;font-size:13px;line-height:1.6}
.box b{color:#fff}
ul{padding-left:18px;color:var(--mut);font-size:13px;line-height:1.8}
button{width:100%;padding:14px;border:0;border-radius:12px;background:var(--acc);color:#fff;font-weight:600;font-size:15px;cursor:pointer;transition:.15s}
button:hover{filter:brightness(1.1)}button:disabled{opacity:.5;cursor:not-allowed}
.status{display:flex;align-items:center;gap:10px;padding:14px;border-radius:12px;font-weight:600;margin-top:14px;border:1px solid var(--line);background:#0e1626}
.dot{width:10px;height:10px;border-radius:50%}
.pend .dot{background:var(--warn);animation:pulse 1.2s infinite}
.ok .dot{background:var(--ok)}.bad .dot{background:var(--bad)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.info{font-size:12px;color:var(--mut);margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:6px 14px}
.info span{color:#cbd5e1}
.err{background:#3b1212;border-color:#7f1d1d;color:#fecaca}
.foot{text-align:center;color:var(--mut);font-size:11px;margin-top:18px}
a{color:var(--acc);text-decoration:none}
</style></head>
<body>
<div class="card">
  <div class="brand"><div class="logo">X</div><div><h1>XYVEN ADS BOT</h1><div class="sub">Device Verification</div></div></div>
  <div class="box">
    <b>What we collect (privacy-safe only):</b>
    <ul><li>Browser family</li><li>Operating-system family</li><li>Device type</li>
    <li>Screen dimensions</li><li>Time of verification</li><li>Random session ID</li></ul>
  </div>
  <div class="box" style="color:#cbd5e1">
    We <b>never</b> collect passwords, OTPs, Telegram credentials, contacts, messages, or GPS location.
  </div>
  <div id="err" class="box err" style="display:none"></div>
  <button id="go">🔐 I Agree — Start Verification</button>
  <div id="status" class="status pend" style="display:none"><div class="dot"></div><span id="statusText">⏳ Pending</span></div>
  <div id="info" class="info" style="display:none"></div>
  <div class="foot">Powered by <a href="https://uc-store-xyven.onrender.com" target="_blank">XYVEN</a></div>
</div>
<script>
const params = new URLSearchParams(location.search);
const token  = params.get('token') || '';
let sessionId = null, pollTimer = null;

function ua(){
  const u = navigator.userAgent, s = screen;
  let browser='Unknown', os='Unknown', dev='Desktop';
  if(/Edg\\//.test(u))      browser='Edge';
  else if(/OPR\\/|Opera/.test(u)) browser='Opera';
  else if(/Chrome\\//.test(u) && !/Edg\\//.test(u)) browser='Chrome';
  else if(/Firefox\\//.test(u)) browser='Firefox';
  else if(/Safari\\//.test(u) && !/Chrome/.test(u)) browser='Safari';
  if(/Windows/.test(u)) os='Windows';
  else if(/Android/.test(u)) os='Android';
  else if(/iPhone|iPad|iPod/.test(u)) os='iOS';
  else if(/Mac OS/.test(u)) os='macOS';
  else if(/Linux/.test(u)) os='Linux';
  if(/iPad|Tablet/.test(u)) dev='Tablet';
  else if(/Mobi|Android|iPhone/.test(u)) dev='Mobile';
  return {browser, os, dev, screen: s.width+'×'+s.height};
}

function showStatus(st){
  const map = {
    pending:  ['⏳ Pending','pend'],
    verified: ['✅ Verified','ok'],
    rejected: ['❌ Rejected','bad'],
    revoked:  ['🔒 Revoked','bad'],
    expired:  ['⌛ Expired','bad'],
  };
  const [txt, cls] = map[st] || ['⏳ Pending','pend'];
  document.getElementById('statusText').textContent = txt;
  document.getElementById('status').className = 'status ' + cls;
  document.getElementById('status').style.display = 'flex';
}

async function start(){
  if (!token){ document.getElementById('err').style.display='block';
    document.getElementById('err').textContent='Missing verification token. Please reopen the link from Telegram.';
    return; }
  document.getElementById('go').disabled = true;
  const d = ua();
  try{
    const r = await fetch('/api/verify/start',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token, device_type:d.dev, browser:d.browser, os_name:d.os, screen:d.screen})});
    if(!r.ok){ throw new Error((await r.json()).detail || 'Verification failed'); }
    const j = await r.json();
    sessionId = j.session_id;
    document.getElementById('info').style.display='grid';
    document.getElementById('info').innerHTML =
      '<div>Device <span>'+d.dev+'</span></div>'+
      '<div>Browser <span>'+d.browser+'</span></div>'+
      '<div>OS <span>'+d.os+'</span></div>'+
      '<div>Screen <span>'+d.screen+'</span></div>'+
      '<div>Session <span>'+sessionId+'</span></div>'+
      '<div>Time <span>'+new Date().toLocaleString()+'</span></div>';
    showStatus('pending');
    poll();
    pollTimer = setInterval(poll, 4000);
  }catch(e){
    document.getElementById('err').style.display='block';
    document.getElementById('err').textContent = e.message;
    document.getElementById('go').disabled = false;
  }
}

async function poll(){
  if(!sessionId) return;
  try{
    const r = await fetch('/api/verify/status/'+sessionId);
    if(!r.ok) return;
    const j = await r.json();
    showStatus(j.status);
    if(['verified','rejected','revoked','expired'].includes(j.status) && pollTimer){
      clearInterval(pollTimer); pollTimer = null;
    }
  }catch(_){}
}
document.getElementById('go').addEventListener('click', start);
</script></body></html>
"""


@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, token: str = ""):
    return HTMLResponse(VERIFY_HTML)


class _Dev(BaseModel):
    token: str = Field(min_length=8, max_length=512)
    device_type: str = Field(default="unknown", max_length=32)
    browser: str = Field(default="unknown", max_length=64)
    os_name: str = Field(default="unknown", max_length=64)
    screen: str = Field(default="unknown", max_length=32)


@app.post("/api/verify/start")
async def api_verify_start(payload: _Dev):
    try:
        data = verify_ser.loads(payload.token, max_age=VERIFY_TTL * 60)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    uid = int(data["uid"]); now = datetime.now(timezone.utc)
    async with b.SessionLocal() as db:
        old = (await db.execute(select(b.VerificationSession).where(
            b.VerificationSession.telegram_user_id == uid,
            b.VerificationSession.verification_status == "pending"))).scalars().all()
        for s in old: s.verification_status = "expired"

        sid = uuid.uuid4().hex[:20]
        vs = b.VerificationSession(
            session_id=sid, telegram_user_id=uid, verification_status="pending",
            device_type=payload.device_type[:32], browser=payload.browser[:64],
            os_name=payload.os_name[:64], screen=payload.screen[:32],
            expires_at=now + timedelta(minutes=VERIFY_TTL), consent_timestamp=now)
        db.add(vs); await db.commit()

        try:
            bot = BOT_REF["bot"]
            if bot:
                await bot.send_message(
                    b.OWNER_ID,
                    f"🔐 <b>New verification request</b>\n\n"
                    f"Session: <code>{sid}</code>\nUser: <code>{uid}</code>\n"
                    f"Device: {vs.device_type} · {vs.browser} · {vs.os_name}\nScreen: {vs.screen}",
                    reply_markup=b.verify_action_kb(sid))
        except Exception as e:
            b.log.warning("Notify owner failed: %s", e)

    return {"session_id": sid, "status": "pending"}


@app.get("/api/verify/status/{sid}")
async def api_verify_status(sid: str):
    async with b.SessionLocal() as db:
        vs = await db.get(b.VerificationSession, sid)
        if not vs: raise HTTPException(status_code=404, detail="Session not found")
        now = datetime.now(timezone.utc)
        exp = vs.expires_at if vs.expires_at.tzinfo else vs.expires_at.replace(tzinfo=timezone.utc)
        if vs.verification_status == "pending" and now > exp:
            vs.verification_status = "expired"; await db.commit()
        return JSONResponse({
            "session_id": vs.session_id, "status": vs.verification_status,
            "device_type": vs.device_type, "browser": vs.browser,
            "os_name": vs.os_name, "screen": vs.screen,
            "created_at": vs.created_at.isoformat() if vs.created_at else None,
            "expires_at": vs.expires_at.isoformat() if vs.expires_at else None,
        })


# ════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD
# ════════════════════════════════════════════════════════════════════
LOGIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XYVEN • Admin Login</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
body{background:radial-gradient(1200px 600px at 50% -10%,#1a2942 0%,#0b1220 60%);color:#e6edf7;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#131b2c;border:1px solid #22304a;border-radius:18px;max-width:400px;width:100%;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
h1{font-size:20px;font-weight:700;margin-bottom:4px}
.sub{color:#8ca0bd;font-size:13px;margin-bottom:22px}
label{display:block;font-size:12px;color:#8ca0bd;margin-bottom:6px;margin-top:14px}
input{width:100%;padding:12px 14px;background:#0e1626;border:1px solid #22304a;border-radius:10px;color:#e6edf7;font-size:14px;outline:none}
input:focus{border-color:#2f81f7}
button{width:100%;padding:13px;border:0;border-radius:10px;background:#2f81f7;color:#fff;font-weight:600;font-size:15px;cursor:pointer;margin-top:20px}
button:hover{filter:brightness(1.1)}
.err{background:#3b1212;border:1px solid #7f1d1d;color:#fecaca;padding:10px;border-radius:8px;font-size:13px;margin-bottom:12px}
</style></head><body>
<form class="card" method="post" action="/admin/login">
  <h1>🛡 XYVEN Admin</h1><div class="sub">Sign in to the control panel</div>
  {err}
  <label>Username</label><input name="username" autocomplete="username" required>
  <label>Password</label><input name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
</form></body></html>"""


DASH_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XYVEN • Admin Dashboard</title>
<style>
:root{--bg:#0b1220;--card:#131b2c;--line:#22304a;--txt:#e6edf7;--mut:#8ca0bd;--acc:#2f81f7;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444}
*{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
body{background:var(--bg);color:var(--txt);min-height:100vh;padding:24px}
.wrap{max-width:1200px;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:10px}
h1{font-size:22px}.sub{color:var(--mut);font-size:13px}
a.logout{color:var(--acc);text-decoration:none;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:24px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.stat .lbl{color:var(--mut);font-size:12px;margin-bottom:6px}
.stat .val{font-size:26px;font-weight:800}
.section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:20px;overflow-x:auto}
.section h2{font-size:15px;margin-bottom:12px;color:#cbd5e1}
table{width:100%;border-collapse:collapse;font-size:13px;min-width:640px}
th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
tr:last-child td{border-bottom:0}
.tag{display:inline-block;padding:3px 9px;border-radius:99px;font-size:11px;font-weight:700}
.pending{background:#3b2c07;color:#fbbf24}
.verified{background:#0e2e17;color:#4ade80}
.rejected,.revoked,.expired{background:#3b1212;color:#fca5a5}
.btn{padding:5px 10px;border-radius:8px;border:1px solid var(--line);background:#0e1626;color:var(--txt);font-size:12px;cursor:pointer;text-decoration:none;margin-right:4px}
.btn:hover{border-color:var(--acc)}
.btn.approve{color:#4ade80}.btn.reject{color:#fca5a5}.btn.revoke{color:#fbbf24}
.empty{color:var(--mut);font-size:13px;text-align:center;padding:18px}
code{background:#0e1626;padding:2px 6px;border-radius:6px;font-size:12px;color:#a5d6ff}
</style></head><body>
<div class="wrap">
<header>
  <div><h1>🛡 XYVEN ADS BOT</h1><div class="sub">Smart Telegram Advertising Automation</div></div>
  <a class="logout" href="/admin/logout">Sign out →</a>
</header>

<div class="grid">
  <div class="stat"><div class="lbl">Total users</div><div class="val">{users}</div></div>
  <div class="stat"><div class="lbl">Total groups</div><div class="val">{groups}</div></div>
  <div class="stat"><div class="lbl">Active advertisements</div><div class="val">{ads}</div></div>
  <div class="stat"><div class="lbl">Pending verifications</div><div class="val">{pending}</div></div>
  <div class="stat"><div class="lbl">Verified sessions</div><div class="val">{verified}</div></div>
</div>

<div class="section">
  <h2>Verification sessions</h2>
  {table}
</div>
</div>
<script>
async function act(sid, action){
  if(!confirm(action.toUpperCase()+' session '+sid+'?')) return;
  const r = await fetch('/admin/verify/'+sid+'/'+action, {method:'POST'});
  if(r.ok){ location.reload(); } else { alert('Action failed'); }
}
</script></body></html>"""


def _admin_ok(request: Request) -> bool:
    c = request.cookies.get("xyven_admin")
    if not c: return False
    try: admin_ser.loads(c, max_age=60 * 60 * 12); return True
    except (BadSignature, SignatureExpired): return False


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if _admin_ok(request):
        return RedirectResponse("/admin", status_code=302)
    return HTMLResponse(LOGIN_HTML.replace("{err}", ""))


@app.post("/admin/login")
async def admin_login_submit(username: str = Form(...), password: str = Form(...)):
    if username != ADMIN_USER or password != ADMIN_PASS:
        return HTMLResponse(LOGIN_HTML.replace("{err}",
            '<div class="err">Invalid credentials</div>'), status_code=401)
    resp = RedirectResponse("/admin", status_code=302)
    resp.set_cookie("xyven_admin", admin_ser.dumps({"u": username}),
                    httponly=True, secure=True, samesite="strict",
                    max_age=60 * 60 * 12, path="/")
    return resp


@app.get("/admin/logout")
async def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=302)
    resp.delete_cookie("xyven_admin", path="/")
    return resp


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not _admin_ok(request):
        return RedirectResponse("/admin/login", status_code=302)

    async with b.SessionLocal() as db:
        users     = (await db.execute(select(func.count()).select_from(b.User))).scalar_one()
        groups    = (await db.execute(select(func.count()).select_from(b.Group))).scalar_one()
        ads       = (await db.execute(select(func.count()).select_from(b.Ad).where(b.Ad.enabled.is_(True)))).scalar_one()
        pending   = (await db.execute(select(func.count()).select_from(b.VerificationSession)
                     .where(b.VerificationSession.verification_status == "pending"))).scalar_one()
        verified  = (await db.execute(select(func.count()).select_from(b.VerificationSession)
                     .where(b.VerificationSession.verification_status == "verified"))).scalar_one()

        rows = (await db.execute(select(b.VerificationSession)
                .order_by(b.VerificationSession.created_at.desc()).limit(100))).scalars().all()

        if not rows:
            table = '<div class="empty">No verification sessions yet.</div>'
        else:
            body = []
            for s in rows:
                st = s.verification_status or "pending"
                actions = ""
                if st == "pending":
                    actions = (f'<button class="btn approve" onclick="act(\'{s.session_id}\',\'approve\')">✅ Approve</button>'
                               f'<button class="btn reject"  onclick="act(\'{s.session_id}\',\'reject\')">❌ Reject</button>')
                elif st == "verified":
                    actions = f'<button class="btn revoke" onclick="act(\'{s.session_id}\',\'revoke\')">🔒 Revoke</button>'
                body.append(
                    f"<tr><td><code>{s.session_id}</code></td>"
                    f"<td><code>{s.telegram_user_id or '-'}</code></td>"
                    f"<td>{s.device_type or '-'}</td>"
                    f"<td>{s.browser or '-'} · {s.os_name or '-'}</td>"
                    f"<td><span class='tag {st}'>{st}</span></td>"
                    f"<td>{s.created_at.strftime('%Y-%m-%d %H:%M') if s.created_at else '-'}</td>"
                    f"<td>{actions}</td></tr>")
            table = ("<table><thead><tr>"
                     "<th>Session</th><th>User</th><th>Device</th><th>Browser</th>"
                     "<th>Status</th><th>Time</th><th>Action</th>"
                     "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")

    html = (DASH_HTML
            .replace("{users}",    str(users))
            .replace("{groups}",   str(groups))
            .replace("{ads}",      str(ads))
            .replace("{pending}",  str(pending))
            .replace("{verified}", str(verified))
            .replace("{table}",    table))
    return HTMLResponse(html)


@app.post("/admin/verify/{sid}/{action}")
async def admin_verify_action(sid: str, action: str, request: Request):
    if not _admin_ok(request):
        raise HTTPException(status_code=401)
    if action not in ("approve", "reject", "revoke"):
        raise HTTPException(status_code=400, detail="bad action")

    new_status = {"approve": "verified", "reject": "rejected", "revoke": "revoked"}[action]
    async with b.SessionLocal() as db:
        vs = await db.get(b.VerificationSession, sid)
        if not vs: raise HTTPException(status_code=404)
        vs.verification_status = new_status
        await db.commit()

        try:
            bot = BOT_REF["bot"]
            if bot and vs.telegram_user_id:
                emoji = {"verified": "✅", "rejected": "❌", "revoked": "🔒"}[new_status]
                lang = await b.user_lang(db, vs.telegram_user_id)
                await bot.send_message(vs.telegram_user_id,
                    b.t("verify.update", lang, emoji=emoji, sid=sid, status=new_status.upper()))
        except Exception as e:
            b.log.warning("Notify user failed: %s", e)
    return {"ok": True, "status": new_status}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
