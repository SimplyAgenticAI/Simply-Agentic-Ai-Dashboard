import os
import json
import smtplib
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, request, render_template_string, jsonify
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

APP_TITLE = "Simply Agentic AI Hands"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

MODEL = os.getenv("MODEL", "gpt-4o-mini")

if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY in your .env file")

client = OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)

# ----------------------------
# Files
# ----------------------------
BASE_DIR = Path(__file__).parent
PROSPECTS_LIST_FILE = BASE_DIR / "prospects_list.txt"
TEMPLATES_FILE = BASE_DIR / "templates.json"
SENT_LOG_FILE = BASE_DIR / "sent_history.jsonl"

# ----------------------------
# Prospect List storage
# ----------------------------
def load_prospect_list_raw() -> str:
    if not PROSPECTS_LIST_FILE.exists():
        return ""
    return PROSPECTS_LIST_FILE.read_text(encoding="utf-8")

def save_prospect_list_raw(text: str):
    PROSPECTS_LIST_FILE.write_text(text or "", encoding="utf-8")

def parse_prospect_lines(text: str):
    out = []
    seen = set()

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue

        name = ""
        email = ""

        if "<" in line and ">" in line:
            left = line.split("<", 1)[0].strip()
            mid = line.split("<", 1)[1].split(">", 1)[0].strip()
            name = left
            email = mid
        elif "," in line:
            parts = [p.strip() for p in line.split(",", 1)]
            if len(parts) == 2:
                name, email = parts[0], parts[1]
        else:
            email = line

        email = (email or "").strip()
        name = (name or "").strip()

        if "@" not in email or "." not in email:
            continue

        key = email.lower()
        if key in seen:
            continue
        seen.add(key)

        out.append({"name": name, "email": email})

    return out

# ----------------------------
# Templates storage
# ----------------------------
def load_templates() -> list:
    if not TEMPLATES_FILE.exists():
        return []
    try:
        data = json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []

def save_templates(items: list):
    TEMPLATES_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")

def upsert_template(name: str, campaign_prompt: str):
    items = load_templates()
    name = (name or "").strip()
    campaign_prompt = (campaign_prompt or "").strip()
    if not name:
        raise ValueError("Template name is required")
    if not campaign_prompt:
        raise ValueError("Campaign prompt is required")

    found = False
    for t in items:
        if (t.get("name") or "").strip().lower() == name.lower():
            t["name"] = name
            t["prompt"] = campaign_prompt
            found = True
            break

    if not found:
        items.insert(0, {"name": name, "prompt": campaign_prompt})

    save_templates(items)
    return items

def delete_template(name: str):
    items = load_templates()
    name_l = (name or "").strip().lower()
    items2 = [t for t in items if (t.get("name") or "").strip().lower() != name_l]
    save_templates(items2)
    return items2

# ----------------------------
# Sent History storage
# ----------------------------
def append_sent_history(to_email: str, subject: str, body: str, status: str = "sent", error: str = ""):
    rec = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "to": to_email,
        "subject": subject,
        "body": body,
        "status": status,
        "error": error,
    }
    with open(SENT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def read_sent_history(limit: int = 50):
    if not SENT_LOG_FILE.exists():
        return []
    lines = SENT_LOG_FILE.read_text(encoding="utf-8").splitlines()
    out = []
    for line in reversed(lines[-max(limit, 1):]):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out

# ----------------------------
# UI
# ----------------------------
HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{title}}</title>
  <style>
    :root{
      --bg:#0b0a12;
      --panel:#121027;
      --panel2:#171433;
      --border:#2a2450;
      --text:#eae7ff;
      --muted:#b9b2ff;
      --purple:#7c3aed;
      --purple2:#a855f7;
      --good:#22c55e;
      --danger:#ef4444;
      --btn:#2a2450;
      --btn2:#3a2f6a;
      --input:#0f0d1e;
    }
    *{box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Noto Sans,sans-serif;}
    body{
      margin:0; padding:24px;
      background: radial-gradient(900px 600px at 20% 0%, rgba(124,58,237,.25), transparent 60%),
                  radial-gradient(900px 600px at 80% 20%, rgba(168,85,247,.18), transparent 55%),
                  var(--bg);
      color:var(--text);
    }
    .topbar{
      display:flex; align-items:center; justify-content:space-between;
      margin-bottom:18px;
      gap:12px;
      flex-wrap:wrap;
    }
    .brand{display:flex; gap:12px; align-items:center;}
    .logo{
      width:42px;height:42px;border-radius:12px;
      background: linear-gradient(135deg, var(--purple), var(--purple2));
      box-shadow: 0 10px 30px rgba(124,58,237,.25);
    }
    .titlewrap h1{margin:0;font-size:18px;letter-spacing:.2px}
    .titlewrap p{margin:2px 0 0;color:var(--muted);font-size:12px}
    .status{
      display:flex; align-items:center; gap:10px;
      padding:10px 12px; border:1px solid var(--border); border-radius:12px;
      background: rgba(18,16,39,.6);
    }
    .dot{width:10px;height:10px;border-radius:50%;background:var(--good);box-shadow:0 0 0 4px rgba(34,197,94,.15)}
    .grid{
      display:grid; gap:16px;
      grid-template-columns: 1.1fr .9fr;
    }
    .card{
      border:1px solid var(--border);
      background: linear-gradient(180deg, rgba(18,16,39,.92), rgba(23,20,51,.92));
      border-radius:18px;
      padding:16px;
      box-shadow: 0 18px 60px rgba(0,0,0,.35);
    }
    .card h2{margin:0 0 6px; font-size:14px; color:var(--text)}
    .card p{margin:0 0 14px; font-size:12px; color:var(--muted)}
    label{font-size:12px;color:var(--muted);display:block;margin:10px 0 6px}
    textarea, input, select{
      width:100%;
      background: var(--input);
      color: var(--text);
      border:1px solid rgba(185,178,255,.18);
      border-radius:12px;
      padding:12px;
      outline:none;
    }
    textarea{min-height:140px; resize:vertical;}
    input::placeholder, textarea::placeholder{color: rgba(185,178,255,.55);}
    .row{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:12px}
    button{
      background: linear-gradient(135deg, var(--btn), var(--btn2));
      border:1px solid rgba(185,178,255,.18);
      color:var(--text);
      padding:10px 14px;
      border-radius:12px;
      cursor:pointer;
      font-weight:600;
    }
    button.primary{
      background: linear-gradient(135deg, var(--purple), var(--purple2));
      border:none;
      box-shadow: 0 12px 35px rgba(124,58,237,.25);
    }
    button:disabled{opacity:.6; cursor:not-allowed;}
    .pill{
      display:inline-flex; gap:8px; align-items:center;
      padding:6px 10px; border-radius:999px;
      border:1px solid rgba(185,178,255,.18);
      background: rgba(15,13,30,.65);
      font-size:12px; color:var(--muted);
    }
    .msg{
      margin-top:12px;
      padding:12px;
      border-radius:12px;
      border:1px solid rgba(185,178,255,.18);
      background: rgba(15,13,30,.65);
      white-space:pre-wrap;
    }
    .msg.good{border-color: rgba(34,197,94,.35)}
    .msg.bad{border-color: rgba(239,68,68,.35)}
    .hint{font-size:12px;color:rgba(185,178,255,.75); margin-top:10px; line-height:1.4}
    .small{font-size:11px;color:rgba(185,178,255,.65); margin-top:10px}

    .plist{
      margin-top:12px;
      display:flex;
      flex-direction:column;
      gap:10px;
      max-height:360px;
      overflow:auto;
      padding-right:4px;
    }
    .pitem{
      border:1px solid rgba(185,178,255,.18);
      border-radius:14px;
      padding:10px 12px;
      background: rgba(15,13,30,.55);
      cursor:pointer;
    }
    .pitem:hover{border-color: rgba(168,85,247,.45);}
    .pitem.active{
      border-color: rgba(124,58,237,.85);
      box-shadow: 0 0 0 2px rgba(124,58,237,.25) inset;
    }
    .pname{font-weight:800;font-size:13px;margin:0;}
    .pemail{margin-top:4px;font-size:12px;color: rgba(185,178,255,.9);word-break:break-word;}
    .split{display:grid;grid-template-columns: 1fr 1fr;gap:12px;}
    .history{
      margin-top:12px;
      display:flex;
      flex-direction:column;
      gap:10px;
      max-height:360px;
      overflow:auto;
      padding-right:4px;
    }
    .hitem{
      border:1px solid rgba(185,178,255,.18);
      border-radius:14px;
      padding:10px 12px;
      background: rgba(15,13,30,.55);
      cursor:pointer;
    }
    .hmeta{font-size:11px;color:rgba(185,178,255,.75);}
    .hsub{font-weight:800;font-size:12px;margin-top:4px;}
    .hto{font-size:12px;color:rgba(185,178,255,.95);margin-top:4px;word-break:break-word;}
    .hstatus{margin-top:6px;font-size:11px;color:rgba(185,178,255,.75);}

    .tinygrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
    .minihelp{font-size:11px;color:rgba(185,178,255,.75);line-height:1.35;margin-top:10px;}

    @media (max-width: 980px){
      .grid{grid-template-columns:1fr}
      .split{grid-template-columns:1fr}
      .tinygrid{grid-template-columns:1fr}
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand">
      <div class="logo"></div>
      <div class="titlewrap">
        <h1>{{title}}</h1>
        <p>Prospecting Stack • Templates • Follow-ups • Sent History • Play Mode</p>
      </div>
    </div>
    <div class="status">
      <div class="dot"></div>
      <div>
        <div style="font-weight:700;font-size:12px">Online</div>
        <div style="font-size:11px;color:var(--muted)">Dashboard</div>
      </div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Prompt</h2>
      <p>Write your campaign prompt once. Clicking prospects only swaps the recipient lines.</p>

      <label>Prompt</label>
      <textarea id="prompt" placeholder="Click a prospect to auto-fill recipient lines, then customize your campaign prompt below the divider."></textarea>

      <div class="row">
        <button class="primary" id="generateBtn">Generate Email</button>
        <button id="clearBtn">Clear Prompt</button>
        <span class="pill">Keeps campaign prompt intact</span>
      </div>

      <div id="aiOut" class="msg" style="display:none"></div>
      <div class="hint">Safety: Nothing sends automatically. You review before sending.</div>
    </div>

    <div class="card">
      <h2>Send Email</h2>
      <p>Play Mode auto-generates per prospect. You approve the send.</p>

      <label>To</label>
      <input id="to" placeholder="name@email.com" />

      <label>Subject</label>
      <input id="subject" placeholder="Subject line" />

      <label>Body</label>
      <textarea id="body" placeholder="Email body..."></textarea>

      <div class="row">
        <button class="primary" id="approveSendBtn" disabled>Approve + Send</button>
        <button id="sendBtn">Send</button>
        <button id="followUpBtn">Generate Follow-up</button>
        <button id="clearEmailBtn">Clear Email</button>
        <button id="nextBtn">Next Prospect</button>
      </div>

      <div class="row">
        <button class="primary" id="playBtn">Play Mode</button>
        <button id="pauseBtn" disabled>Pause</button>
        <span class="pill">Auto generates • You approve send</span>
      </div>

      <div id="sendOut" class="msg" style="display:none"></div>
      <div class="small">SMTP: {{smtp_host}} • Port {{smtp_port}} • User {{smtp_user_masked}}</div>
    </div>

    <div class="card">
      <h2>Templates</h2>
      <p>Save and reuse campaign prompts. Loading a template only replaces the campaign section.</p>

      <label>Saved Templates</label>
      <select id="templateSelect"></select>

      <div class="row">
        <button class="primary" id="loadTemplateBtn">Load Template</button>
        <button id="deleteTemplateBtn">Delete</button>
        <button id="refreshTemplatesBtn">Refresh</button>
      </div>

      <label>Save Current Campaign Prompt As</label>
      <input id="templateName" placeholder="Example: Local Biz Outreach" />

      <div class="row">
        <button class="primary" id="saveTemplateBtn">Save Template</button>
      </div>

      <div id="tplMsg" class="msg" style="display:none"></div>
      <div class="hint">Tip: Build one perfect prompt, save it, then run it across any prospect list.</div>
    </div>

    <div class="card">
      <h2>Sent History</h2>
      <p>Click a history item to load its subject and body back into the email fields.</p>

      <div class="row">
        <button class="primary" id="refreshHistoryBtn">Refresh History</button>
      </div>

      <div id="history" class="history" style="display:none"></div>
      <div id="historyEmpty" class="msg" style="display:none"></div>
      <div class="hint">History is saved locally in sent_history.jsonl.</div>
    </div>

    <div class="card">
      <h2>Prospect List</h2>
      <p>Paste emails (one per line) or <b>Name, email</b>. Saved to <b>prospects_list.txt</b>.</p>

      <div class="split">
        <div>
          <label>Prospects (paste list)</label>
          <textarea id="plistRaw" placeholder="Example:
Coastal Plumbing, info@coastalplumbing.com
hello@shoregym.com
Roadie Joe’s, contact@roadiejoes.com"></textarea>

          <div class="row">
            <button class="primary" id="saveProspectsBtn">Save List</button>
            <button id="reloadProspectsBtn">Reload</button>
          </div>

          <div id="plistMsg" class="msg" style="display:none"></div>
        </div>

        <div>
          <label>Clickable Prospects</label>
          <div id="plist" class="plist" style="display:none"></div>
          <div id="plistEmpty" class="msg" style="display:none"></div>
          <div class="hint">Click prospect swaps recipient lines only. Your campaign prompt stays.</div>
        </div>
      </div>
    </div>

    <!-- NEW: Full Automation Queue card (bottom right) -->
    <div class="card">
      <h2>Full Automation Queue</h2>
      <p>Auto generate + send, then move to the next prospect with a delay. Hard capped for safety.</p>

      <div class="tinygrid">
        <div>
          <label>Max Sends (1 to 15)</label>
          <input id="autoMax" type="number" min="1" max="15" value="15" />
        </div>
        <div>
          <label>Delay Between Sends (seconds)</label>
          <input id="autoDelay" type="number" min="2" max="600" value="12" />
        </div>
      </div>

      <div class="row">
        <button class="primary" id="autoStartBtn">Start Auto</button>
        <button id="autoStopBtn" disabled>Stop</button>
        <span class="pill">Stops on errors</span>
      </div>

      <div id="autoOut" class="msg" style="display:none"></div>
      <div class="minihelp">
        Starts from your currently selected prospect. It will send up to your Max Sends, waiting the Delay between each send.
      </div>
    </div>
  </div>

<script>
  const aiOut = document.getElementById('aiOut');
  const sendOut = document.getElementById('sendOut');
  const plistMsg = document.getElementById('plistMsg');
  const tplMsg = document.getElementById('tplMsg');

  const plistRaw = document.getElementById('plistRaw');
  const plist = document.getElementById('plist');
  const plistEmpty = document.getElementById('plistEmpty');

  const historyEl = document.getElementById('history');
  const historyEmpty = document.getElementById('historyEmpty');

  const templateSelect = document.getElementById('templateSelect');

  const approveSendBtn = document.getElementById('approveSendBtn');
  const playBtn = document.getElementById('playBtn');
  const pauseBtn = document.getElementById('pauseBtn');

  // Full Automation Queue UI
  const autoOut = document.getElementById('autoOut');
  const autoStartBtn = document.getElementById('autoStartBtn');
  const autoStopBtn = document.getElementById('autoStopBtn');
  const autoMaxEl = document.getElementById('autoMax');
  const autoDelayEl = document.getElementById('autoDelay');

  let prospects = [];
  let activeIndex = -1;

  let templates = [];

  let playRunning = false;
  let awaitingApproval = false;

  // Full Automation Queue state
  let autoRunning = false;
  let autoStopRequested = false;

  const DIVIDER = "\\n\\n--- CAMPAIGN PROMPT ---\\n";

  function showBox(el, text, ok=true){
    el.style.display = 'block';
    el.textContent = text;
    el.className = 'msg ' + (ok ? 'good' : 'bad');
  }
  function hideBox(el){ el.style.display='none'; el.textContent=''; }

  function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

  function getCampaignPrompt(){
    const full = document.getElementById("prompt").value || "";
    if(full.includes(DIVIDER)){
      return full.split(DIVIDER, 2)[1] || "";
    }
    return "";
  }

  function getRecipientFromPrompt(){
    const full = document.getElementById("prompt").value || "";
    const emailMatch = full.match(/Recipient Email:\\s*(.*)/i);
    const nameMatch = full.match(/Prospect Name:\\s*(.*)/i);
    const email = emailMatch ? (emailMatch[1] || "").trim() : "";
    const name = nameMatch ? (nameMatch[1] || "").trim() : "";
    return { email, name };
  }

  function ensureCampaignPromptExists(){
    const full = document.getElementById("prompt").value || "";
    if(full.includes(DIVIDER)) return;

    const starter =
"Write a short, friendly outreach email offering a free 10 minute Facebook page review and 3 quick improvements. Keep it under 120 words. Close with a simple question asking if they want me to send the 3 improvements.";
    document.getElementById("prompt").value = "Recipient Email: \\nProspect Name: " + DIVIDER + starter;
  }

  function setRecipientLines(email, name){
    ensureCampaignPromptExists();
    const campaign = getCampaignPrompt().trim();

    const nameLine = name ? name : "";
    const newFull =
`Recipient Email: ${email || ""}
Prospect Name: ${nameLine}${DIVIDER}${campaign}`;

    document.getElementById("prompt").value = newFull;
  }

  function setCampaignPromptOnly(campaignText){
    ensureCampaignPromptExists();
    const r = getRecipientFromPrompt();
    const newFull =
`Recipient Email: ${r.email || ""}
Prospect Name: ${r.name || ""}${DIVIDER}${(campaignText || "").trim()}`;
    document.getElementById("prompt").value = newFull;
  }

  function fillEmailFields(emailObj){
    document.getElementById('to').value = emailObj.to || document.getElementById('to').value;
    document.getElementById('subject').value = emailObj.subject || "";
    document.getElementById('body').value = emailObj.body || "";
  }

  async function generateNow(){
    hideBox(aiOut);
    const prompt = document.getElementById('prompt').value.trim();
    if(!prompt){
      showBox(aiOut, "Click a prospect or write a prompt first.", false);
      return { ok:false };
    }

    showBox(aiOut, "Generating...", true);

    const res = await fetch("/generate", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ prompt })
    });

    const data = await res.json();
    if(!data.ok){
      showBox(aiOut, data.error || "AI error", false);
      return { ok:false };
    }

    fillEmailFields(data.email);
    const preview = `TO: ${data.email.to}\\nSUBJECT: ${data.email.subject}\\n\\n${data.email.body}`;
    showBox(aiOut, preview, true);

    return { ok:true };
  }

  async function followUpNow(){
    hideBox(aiOut);

    const toEmail = document.getElementById('to').value.trim();
    const prevSubject = document.getElementById('subject').value.trim();
    const prevBody = document.getElementById('body').value.trim();
    const r = getRecipientFromPrompt();

    if(!toEmail){
      showBox(aiOut, "Select a prospect first so To is filled.", false);
      return;
    }
    if(!prevSubject || !prevBody){
      showBox(aiOut, "Generate an email first (or load one from history) so I can create a follow-up.", false);
      return;
    }

    showBox(aiOut, "Generating follow-up...", true);

    const res = await fetch("/followup", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({
        to: toEmail,
        prospect_name: r.name || "",
        previous_subject: prevSubject,
        previous_body: prevBody,
        campaign_prompt: (getCampaignPrompt() || "").trim()
      })
    });

    const data = await res.json();
    if(!data.ok){
      showBox(aiOut, data.error || "Follow-up error", false);
      return;
    }

    fillEmailFields(data.email);
    const preview = `TO: ${data.email.to}\\nSUBJECT: ${data.email.subject}\\n\\n${data.email.body}`;
    showBox(aiOut, preview, true);
  }

  async function sendNow(){
    hideBox(sendOut);

    const payload = {
      to: document.getElementById('to').value.trim(),
      subject: document.getElementById('subject').value.trim(),
      body: document.getElementById('body').value
    };

    if(!payload.to || !payload.subject || !payload.body){
      showBox(sendOut, "Fill To, Subject, and Body first.", false);
      return { ok:false };
    }

    showBox(sendOut, "Sending...", true);

    const res = await fetch("/send", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if(!data.ok){
      showBox(sendOut, data.error || "Send error", false);
      return { ok:false };
    }

    showBox(sendOut, "Sent successfully.", true);
    return { ok:true };
  }

  // Buttons
  document.getElementById('clearBtn').onclick = () => {
    document.getElementById('prompt').value = '';
    hideBox(aiOut);
  };

  document.getElementById('clearEmailBtn').onclick = () => {
    document.getElementById('to').value = '';
    document.getElementById('subject').value = '';
    document.getElementById('body').value = '';
    hideBox(sendOut);
    approveSendBtn.disabled = true;
    awaitingApproval = false;
  };

  document.getElementById('generateBtn').onclick = async () => {
    awaitingApproval = false;
    approveSendBtn.disabled = true;
    await generateNow();
  };

  document.getElementById('sendBtn').onclick = async () => {
    awaitingApproval = false;
    approveSendBtn.disabled = true;
    await sendNow();
    await loadHistory();
  };

  document.getElementById('followUpBtn').onclick = async () => {
    awaitingApproval = false;
    approveSendBtn.disabled = true;
    await followUpNow();
  };

  function setActive(index){
    activeIndex = index;

    const nodes = document.querySelectorAll(".pitem");
    nodes.forEach((n, i) => {
      if(i === activeIndex) n.classList.add("active");
      else n.classList.remove("active");
    });

    const p = prospects[activeIndex];
    if(!p) return;

    document.getElementById("to").value = p.email || "";
    setRecipientLines(p.email || "", p.name || "");
    showBox(plistMsg, `Selected: ${p.email}`, true);
  }

  function renderProspects(){
    plist.innerHTML = "";
    if(!prospects.length){
      plist.style.display = "none";
      plistEmpty.style.display = "block";
      plistEmpty.textContent = "No prospects saved yet. Paste some emails on the left and click Save List.";
      return;
    }

    plist.style.display = "block";
    plistEmpty.style.display = "none";

    prospects.forEach((p, idx) => {
      const div = document.createElement("div");
      div.className = "pitem";
      div.onclick = () => setActive(idx);

      const n = document.createElement("div");
      n.className = "pname";
      n.textContent = p.name ? p.name : "Prospect";

      const e = document.createElement("div");
      e.className = "pemail";
      e.textContent = p.email;

      div.appendChild(n);
      div.appendChild(e);
      plist.appendChild(div);
    });

    if(activeIndex >= 0 && activeIndex < prospects.length){
      setActive(activeIndex);
    } else {
      setActive(0);
    }
  }

  async function loadProspectsFromServer(){
    const res = await fetch("/prospect_list");
    const data = await res.json();
    if(!data.ok){
      showBox(plistMsg, data.error || "Could not load list", false);
      return;
    }
    plistRaw.value = data.raw || "";
    prospects = data.items || [];
    renderProspects();
  }

  document.getElementById("reloadProspectsBtn").onclick = () => loadProspectsFromServer();

  document.getElementById("saveProspectsBtn").onclick = async () => {
    hideBox(plistMsg);
    const raw = plistRaw.value || "";

    showBox(plistMsg, "Saving...", true);

    const res = await fetch("/prospect_list", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ raw })
    });

    const data = await res.json();
    if(!data.ok){
      showBox(plistMsg, data.error || "Could not save list", false);
      return;
    }

    showBox(plistMsg, `Saved. Loaded ${data.items.length} prospects.`, true);
    prospects = data.items || [];
    renderProspects();
  };

  document.getElementById("nextBtn").onclick = () => {
    if(!prospects.length) return;
    const next = Math.min(activeIndex + 1, prospects.length - 1);
    setActive(next);

    if(playRunning){
      startCycleForCurrentProspect();
    }
  };

  function setPlayUI(running){
    playBtn.disabled = running;
    pauseBtn.disabled = !running;
  }

  async function startCycleForCurrentProspect(){
    if(!prospects.length){
      showBox(sendOut, "Add prospects first.", false);
      return;
    }

    if(activeIndex < 0) setActive(0);

    awaitingApproval = false;
    approveSendBtn.disabled = true;

    const gen = await generateNow();
    if(!gen.ok){
      awaitingApproval = false;
      approveSendBtn.disabled = true;
      return;
    }

    awaitingApproval = true;
    approveSendBtn.disabled = false;
    showBox(sendOut, "Ready. Click Approve + Send.", true);
  }

  playBtn.onclick = async () => {
    if(!prospects.length){
      showBox(sendOut, "Add prospects first.", false);
      return;
    }

    playRunning = true;
    setPlayUI(true);

    if(activeIndex < 0) setActive(0);

    await startCycleForCurrentProspect();
  };

  pauseBtn.onclick = () => {
    playRunning = false;
    awaitingApproval = false;
    approveSendBtn.disabled = true;
    setPlayUI(false);
    showBox(sendOut, "Play Mode paused.", true);
  };

  approveSendBtn.onclick = async () => {
    if(!awaitingApproval){
      showBox(sendOut, "Generate first, then approve.", false);
      return;
    }

    const sent = await sendNow();
    await loadHistory();
    if(!sent.ok) return;

    awaitingApproval = false;
    approveSendBtn.disabled = true;

    if(!playRunning){
      showBox(sendOut, "Sent. Play Mode is off.", true);
      return;
    }

    if(activeIndex >= prospects.length - 1){
      playRunning = false;
      setPlayUI(false);
      showBox(sendOut, "Sent. Reached end of list. Play Mode stopped.", true);
      return;
    }

    setActive(activeIndex + 1);
    await startCycleForCurrentProspect();
  };

  // Full Automation Queue (NEW)
  function setAutoUI(running){
    autoStartBtn.disabled = running;
    autoStopBtn.disabled = !running;
    autoMaxEl.disabled = running;
    autoDelayEl.disabled = running;
  }

  async function runFullAutomationQueue(){
    if(!prospects.length){
      showBox(autoOut, "Add prospects first.", false);
      return;
    }

    // If Play Mode is running, pause it so the two systems do not fight.
    if(playRunning){
      playRunning = false;
      awaitingApproval = false;
      approveSendBtn.disabled = true;
      setPlayUI(false);
    }

    let maxSends = parseInt(autoMaxEl.value || "15", 10);
    if(isNaN(maxSends)) maxSends = 15;
    maxSends = Math.max(1, Math.min(15, maxSends));

    let delaySec = parseInt(autoDelayEl.value || "12", 10);
    if(isNaN(delaySec)) delaySec = 12;
    delaySec = Math.max(2, Math.min(600, delaySec));

    if(activeIndex < 0) setActive(0);

    autoRunning = true;
    autoStopRequested = false;
    setAutoUI(true);

    let sentCount = 0;
    let i = activeIndex;

    showBox(autoOut, `Auto started. Starting at prospect ${i + 1} of ${prospects.length}.`, true);

    while(autoRunning && !autoStopRequested && sentCount < maxSends && i < prospects.length){
      setActive(i);

      const p = prospects[i] || {};
      showBox(autoOut, `Working: ${p.email || ""} (${i + 1}/${prospects.length})`, true);

      const gen = await generateNow();
      if(!gen.ok){
        showBox(autoOut, "Stopped. Generation failed.", false);
        break;
      }

      // sanity check before sending
      const toVal = (document.getElementById("to").value || "").trim();
      const subVal = (document.getElementById("subject").value || "").trim();
      const bodyVal = (document.getElementById("body").value || "").trim();
      if(!toVal || !subVal || !bodyVal){
        showBox(autoOut, "Stopped. Missing To, Subject, or Body after generation.", false);
        break;
      }

      const sent = await sendNow();
      await loadHistory();
      if(!sent.ok){
        showBox(autoOut, "Stopped. Send failed.", false);
        break;
      }

      sentCount += 1;

      if(sentCount >= maxSends){
        showBox(autoOut, `Done. Sent ${sentCount}. (Reached max sends)`, true);
        break;
      }

      if(i >= prospects.length - 1){
        showBox(autoOut, `Done. Sent ${sentCount}. (Reached end of list)`, true);
        break;
      }

      // delay then continue
      showBox(autoOut, `Sent ${sentCount}. Waiting ${delaySec}s then moving to next...`, true);
      await sleep(delaySec * 1000);

      i += 1;
    }

    autoRunning = false;
    autoStopRequested = false;
    setAutoUI(false);
    if(!autoOut.textContent){
      showBox(autoOut, "Auto stopped.", true);
    }
  }

  autoStartBtn.onclick = async () => {
    if(autoRunning) return;
    await runFullAutomationQueue();
  };

  autoStopBtn.onclick = () => {
    if(!autoRunning) return;
    autoStopRequested = true;
    autoRunning = false;
    setAutoUI(false);
    showBox(autoOut, "Stopping auto...", true);
  };

  // Templates
  function renderTemplates(){
    templateSelect.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = templates.length ? "Select a template" : "No templates saved yet";
    templateSelect.appendChild(opt0);

    templates.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.name;
      opt.textContent = t.name;
      templateSelect.appendChild(opt);
    });
  }

  async function loadTemplates(){
    const res = await fetch("/templates");
    const data = await res.json();
    if(!data.ok){
      showBox(tplMsg, data.error || "Could not load templates", false);
      return;
    }
    templates = data.items || [];
    renderTemplates();
    hideBox(tplMsg);
  }

  document.getElementById("refreshTemplatesBtn").onclick = () => loadTemplates();

  document.getElementById("saveTemplateBtn").onclick = async () => {
    const name = (document.getElementById("templateName").value || "").trim();
    const promptText = (getCampaignPrompt() || "").trim();
    if(!name){
      showBox(tplMsg, "Template name is required.", false);
      return;
    }
    if(!promptText){
      showBox(tplMsg, "Campaign prompt is empty. Add it after the divider first.", false);
      return;
    }

    showBox(tplMsg, "Saving template...", true);

    const res = await fetch("/templates", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ action:"save", name, prompt: promptText })
    });

    const data = await res.json();
    if(!data.ok){
      showBox(tplMsg, data.error || "Could not save template", false);
      return;
    }

    templates = data.items || [];
    renderTemplates();
    showBox(tplMsg, `Saved: ${name}`, true);
  };

  document.getElementById("loadTemplateBtn").onclick = () => {
    const selected = (templateSelect.value || "").trim();
    if(!selected){
      showBox(tplMsg, "Pick a template first.", false);
      return;
    }
    const t = templates.find(x => x.name === selected);
    if(!t){
      showBox(tplMsg, "Template not found. Refresh.", false);
      return;
    }
    setCampaignPromptOnly(t.prompt || "");
    showBox(tplMsg, `Loaded: ${selected}`, true);
  };

  document.getElementById("deleteTemplateBtn").onclick = async () => {
    const selected = (templateSelect.value || "").trim();
    if(!selected){
      showBox(tplMsg, "Pick a template first.", false);
      return;
    }

    showBox(tplMsg, "Deleting...", true);

    const res = await fetch("/templates", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ action:"delete", name: selected })
    });

    const data = await res.json();
    if(!data.ok){
      showBox(tplMsg, data.error || "Could not delete template", false);
      return;
    }

    templates = data.items || [];
    renderTemplates();
    showBox(tplMsg, `Deleted: ${selected}`, true);
  };

  // History
  function renderHistory(items){
    historyEl.innerHTML = "";
    if(!items || !items.length){
      historyEl.style.display = "none";
      historyEmpty.style.display = "block";
      historyEmpty.textContent = "No sent emails yet.";
      return;
    }

    historyEl.style.display = "block";
    historyEmpty.style.display = "none";

    items.forEach((h) => {
      const div = document.createElement("div");
      div.className = "hitem";
      div.onclick = () => {
        document.getElementById("to").value = h.to || "";
        document.getElementById("subject").value = h.subject || "";
        document.getElementById("body").value = h.body || "";
        showBox(sendOut, "Loaded from history.", true);
      };

      const meta = document.createElement("div");
      meta.className = "hmeta";
      meta.textContent = (h.ts || "") + "  |  " + (h.status || "");

      const sub = document.createElement("div");
      sub.className = "hsub";
      sub.textContent = h.subject || "(no subject)";

      const to = document.createElement("div");
      to.className = "hto";
      to.textContent = h.to || "";

      const st = document.createElement("div");
      st.className = "hstatus";
      st.textContent = h.error ? ("Error: " + h.error) : "";

      div.appendChild(meta);
      div.appendChild(sub);
      div.appendChild(to);
      if(h.error) div.appendChild(st);

      historyEl.appendChild(div);
    });
  }

  async function loadHistory(){
    const res = await fetch("/history?limit=60");
    const data = await res.json();
    if(!data.ok){
      showBox(sendOut, data.error || "Could not load history", false);
      return;
    }
    renderHistory(data.items || []);
  }

  document.getElementById("refreshHistoryBtn").onclick = () => loadHistory();

  // initialize
  ensureCampaignPromptExists();
  loadProspectsFromServer();
  loadTemplates();
  loadHistory();
  setPlayUI(false);
  setAutoUI(false);
</script>
</body>
</html>
"""

def masked_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "(not set)"
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        return "*" * len(name) + "@" + domain
    return name[0] + "*" * (len(name) - 2) + name[-1] + "@" + domain

def send_email_smtp(to_email: str, subject: str, body: str):
    if not (SMTP_USER and SMTP_PASS):
        raise ValueError("Missing SMTP_USER or SMTP_PASS in your .env file")

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def index():
    return render_template_string(
        HTML,
        title=APP_TITLE,
        smtp_host=SMTP_HOST,
        smtp_port=SMTP_PORT,
        smtp_user_masked=masked_email(SMTP_USER),
    )

@app.get("/prospect_list")
def get_prospect_list():
    raw = load_prospect_list_raw()
    items = parse_prospect_lines(raw)
    return jsonify(ok=True, raw=raw, items=items)

@app.post("/prospect_list")
def set_prospect_list():
    try:
        data = request.get_json(force=True)
        raw = data.get("raw") or ""
        save_prospect_list_raw(raw)
        items = parse_prospect_lines(raw)
        return jsonify(ok=True, items=items)
    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.get("/templates")
def get_templates_route():
    return jsonify(ok=True, items=load_templates())

@app.post("/templates")
def templates_route():
    try:
        data = request.get_json(force=True)
        action = (data.get("action") or "").strip().lower()
        if action == "save":
            name = data.get("name") or ""
            prompt = data.get("prompt") or ""
            items = upsert_template(name, prompt)
            return jsonify(ok=True, items=items)
        if action == "delete":
            name = data.get("name") or ""
            items = delete_template(name)
            return jsonify(ok=True, items=items)
        return jsonify(ok=False, error="Invalid action")
    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.get("/history")
def history_route():
    try:
        limit = int(request.args.get("limit", "50"))
        limit = max(1, min(limit, 300))
        return jsonify(ok=True, items=read_sent_history(limit))
    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.post("/generate")
def generate():
    try:
        data = request.get_json(force=True)
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return jsonify(ok=False, error="Prompt is required")

        system = (
            "You are an email drafting assistant. "
            "Return ONLY valid JSON with keys: to, subject, body. "
            "If the user provides a line like 'Recipient Email: someone@domain.com', you MUST set 'to' to that exact email. "
            "If the user did not provide a recipient email, set 'to' to an empty string. "
            "Keep it clear, professional, and ready to send."
        )

        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
        )

        text = resp.choices[0].message.content.strip()
        email = json.loads(text)

        out = {
            "to": (email.get("to") or "").strip(),
            "subject": (email.get("subject") or "").strip(),
            "body": (email.get("body") or "").strip(),
        }

        return jsonify(ok=True, email=out)

    except json.JSONDecodeError:
        return jsonify(ok=False, error="AI response was not valid JSON. Try again with a clearer prompt.")
    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.post("/followup")
def followup():
    try:
        data = request.get_json(force=True)
        to_email = (data.get("to") or "").strip()
        prospect_name = (data.get("prospect_name") or "").strip()
        prev_subject = (data.get("previous_subject") or "").strip()
        prev_body = (data.get("previous_body") or "").strip()
        campaign_prompt = (data.get("campaign_prompt") or "").strip()

        if not to_email or not prev_subject or not prev_body:
            return jsonify(ok=False, error="To, previous_subject, and previous_body are required")

        system = (
            "You write email follow-ups. "
            "Return ONLY valid JSON with keys: to, subject, body. "
            "The follow-up must be short, friendly, and easy to reply to. "
            "Do not mention that you are an AI."
        )

        user_msg = (
            f"Recipient Email: {to_email}\n"
            f"Prospect Name: {prospect_name}\n\n"
            "Create a follow-up email to the previous email below.\n"
            "Keep it under 110 words. One clear question at the end.\n"
        )
        if campaign_prompt:
            user_msg += f"\nCampaign context:\n{campaign_prompt}\n"

        user_msg += f"\nPrevious subject:\n{prev_subject}\n\nPrevious body:\n{prev_body}\n"

        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.6,
        )

        text = resp.choices[0].message.content.strip()
        email = json.loads(text)

        out = {
            "to": (email.get("to") or "").strip() or to_email,
            "subject": (email.get("subject") or "").strip(),
            "body": (email.get("body") or "").strip(),
        }

        if not out["subject"]:
            out["subject"] = "Quick follow-up"

        return jsonify(ok=True, email=out)

    except json.JSONDecodeError:
        return jsonify(ok=False, error="AI response was not valid JSON. Try again.")
    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.post("/send")
def send():
    to_email = ""
    subject = ""
    body = ""
    try:
        data = request.get_json(force=True)
        to_email = (data.get("to") or "").strip()
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()

        if not to_email or not subject or not body:
            return jsonify(ok=False, error="To, subject, and body are required")

        send_email_smtp(to_email, subject, body)
        append_sent_history(to_email, subject, body, status="sent", error="")
        return jsonify(ok=True)

    except Exception as e:
        try:
            if to_email or subject or body:
                append_sent_history(to_email, subject, body, status="failed", error=str(e))
        except Exception:
            pass
        return jsonify(ok=False, error=str(e))

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)


