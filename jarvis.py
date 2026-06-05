import os
import json
import datetime
import re
import time
import threading

import webview
from flask import Flask, request, jsonify, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from duckduckgo_search import DDGS
from ollama import Client

# ── Ollama client ───────────────────────────────────────────────────────────
client = Client(host='http://localhost:11434')

# ── Google scopes ────────────────────────────────────────────────────────────
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/drive.metadata.readonly',
]

# ── Local model assignments (RTX 3050 / 24GB RAM) ────────────────────────────
FAST_MODEL      = "llama3.2"           # ~2GB  — snappy, sub-second
NORMAL_MODEL    = "qwen2.5:7b"         # ~5GB  — balanced daily driver
THINKING_MODEL  = "deepseek-r1:8b"    # ~5GB  — chain-of-thought reasoning
CODER_MODEL     = "qwen2.5-coder:32b" # ~20GB — heavyweight code + math

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.urandom(24).hex()

USERS_FILE = 'users.json'
MAX_USERS  = 5

# ── Google services ──────────────────────────────────────────────────────────
def get_google_services():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as f:
            f.write(creds.to_json())
    return (
        build('gmail',    'v1', credentials=creds),
        build('calendar', 'v3', credentials=creds),
        build('drive',    'v3', credentials=creds),
    )

# ── User / profile helpers ────────────────────────────────────────────────────
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

def load_user_profile(username):
    path = f"profile_{username}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def save_user_profile(username, profile):
    with open(f"profile_{username}.json", 'w') as f:
        json.dump(profile, f, indent=4)

# ── Error translation ─────────────────────────────────────────────────────────
def friendly_error(e):
    t = str(e).lower()
    if 'invalid_grant' in t:
        return "Your Google session expired. Please reauthenticate."
    if 'permission' in t:
        return "I don't have permission for that Google resource."
    if 'quota' in t:
        return "Google API quota hit. Try again later."
    return f"Service error: {e}"

# ── Model router ──────────────────────────────────────────────────────────────
def get_model(mode):
    return {
        'fast':      FAST_MODEL,
        'normal':    NORMAL_MODEL,
        'thinking':  THINKING_MODEL,
        'code_math': CODER_MODEL,
    }.get(mode, NORMAL_MODEL)

# ── Google action helpers ─────────────────────────────────────────────────────
def send_email_action(recipient, subject, body, gmail_svc):
    from email.message import EmailMessage
    import base64
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['To']      = recipient
        msg['Subject'] = subject
        raw = {'raw': base64.urlsafe_b64encode(msg.as_bytes()).decode()}
        gmail_svc.users().messages().send(userId='me', body=raw).execute()
        return f"✅ Email sent to {recipient}."
    except Exception as e:
        return friendly_error(e)

def read_recent_emails_action(limit, gmail_svc):
    try:
        results  = gmail_svc.users().messages().list(userId='me', maxResults=limit).execute()
        messages = results.get('messages', [])
        if not messages:
            return "No recent emails."
        out = []
        for m in messages:
            detail  = gmail_svc.users().messages().get(userId='me', id=m['id']).execute()
            headers = detail['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender  = next((h['value'] for h in headers if h['name'] == 'From'),    'Unknown')
            out.append(f"From: {sender} | {subject}")
        return "\n".join(out)
    except Exception as e:
        return friendly_error(e)

def add_calendar_event_action(title, start, end, cal_svc):
    try:
        tz = '-04:00'
        if tz not in start: start += tz
        if tz not in end:   end   += tz
        event = {'summary': title, 'start': {'dateTime': start}, 'end': {'dateTime': end}}
        cal_svc.events().insert(calendarId='primary', body=event).execute()
        return f"✅ Added '{title}' to your calendar."
    except Exception as e:
        return friendly_error(e)

def list_calendar_events_action(days_ahead, cal_svc):
    try:
        now  = datetime.datetime.now(datetime.timezone.utc)
        end  = now + datetime.timedelta(days=days_ahead)
        res  = cal_svc.events().list(
            calendarId='primary', timeMin=now.isoformat(), timeMax=end.isoformat(),
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = res.get('items', [])
        if not events:
            return "No upcoming events."
        return "\n".join(
            f"{e['start'].get('dateTime', e['start'].get('date'))} — {e.get('summary', 'Untitled')}"
            for e in events
        )
    except Exception as e:
        return friendly_error(e)

def search_drive_action(query, drive_svc):
    try:
        res   = drive_svc.files().list(q=f"name contains '{query}'", pageSize=5, fields='files(name)').execute()
        files = res.get('files', [])
        return f"📁 {', '.join(f['name'] for f in files)}" if files else "No files found."
    except Exception as e:
        return friendly_error(e)

def web_search_action(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results:
            return "No results found."
        return "Web results:\n" + "\n".join(f"- {r['title']}: {r['body']}" for r in results)
    except Exception as e:
        return f"Search failed: {e}"

def keyword_fallback(msg, gmail_svc, cal_svc, drive_svc):
    lower = msg.lower()
    if 'search drive' in lower or 'find file' in lower:
        m = re.search(r'(?:search|find)\s+(?:drive\s+)?(?:for\s+)?(.+)$', msg, re.I)
        return search_drive_action(m.group(1) if m else msg, drive_svc)
    return None

# ── Tool schemas ──────────────────────────────────────────────────────────────
AGENT_TOOLS = [
    {"type": "function", "function": {
        "name": "send_email",
        "description": "Send an email when the user wants to email someone.",
        "parameters": {"type": "object", "properties": {
            "recipient": {"type": "string", "description": "Recipient email address."},
            "subject":   {"type": "string", "description": "Email subject."},
            "body":      {"type": "string", "description": "Email body text."},
        }, "required": ["recipient", "subject", "body"]},
    }},
    {"type": "function", "function": {
        "name": "read_recent_emails",
        "description": "Read recent inbox emails.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "How many emails (default 5)."},
        }, "required": ["limit"]},
    }},
    {"type": "function", "function": {
        "name": "add_calendar_event",
        "description": "Add an event to Google Calendar.",
        "parameters": {"type": "object", "properties": {
            "event_title": {"type": "string"},
            "start_time":  {"type": "string", "description": "ISO 8601, e.g. 2026-06-13T14:00:00"},
            "end_time":    {"type": "string", "description": "ISO 8601, e.g. 2026-06-13T15:00:00"},
        }, "required": ["event_title", "start_time", "end_time"]},
    }},
    {"type": "function", "function": {
        "name": "list_calendar_events",
        "description": "List upcoming calendar events.",
        "parameters": {"type": "object", "properties": {
            "days_ahead": {"type": "integer", "description": "Days to look ahead."},
        }, "required": ["days_ahead"]},
    }},
    {"type": "function", "function": {
        "name": "search_drive",
        "description": "Search Google Drive for files.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
        }, "required": ["query"]},
    }},
]

# ── Session store ─────────────────────────────────────────────────────────────
active_sessions: dict[str, list] = {}

# ── Core inference loop ───────────────────────────────────────────────────────
def run_jarvis(username: str, user_message: str, search_enabled: bool, agent_mode: str) -> str:
    if username not in active_sessions:
        active_sessions[username] = []

    history = active_sessions[username]
    profile = load_user_profile(username)
    mem     = json.dumps(profile, indent=2) if profile else "No profile set."

    # ── Build mode-specific system prompt ────────────────────────────────────
    base = (
        f"You are Jarvis, a private AI assistant running locally on {username}'s machine. "
        f"USER PROFILE:\n{mem}\n"
        "Be direct, accurate, and helpful. Avoid filler phrases."
    )

    if agent_mode == 'fast':
        system_content = base + " Keep responses under 80 words. Be punchy and concise."

    elif agent_mode == 'thinking':
        system_content = (
            base +
            " You are in deep reasoning mode. Wrap your internal chain-of-thought inside "
            "<think>...</think> tags BEFORE your final answer. Be thorough in reasoning, "
            "concise in the final answer."
        )

    elif agent_mode == 'code_math':
        system_content = (
            f"You are Jarvis running qwen2.5-coder:32b — a world-class software architect "
            f"and mathematician assisting {username}. "
            f"USER PROFILE:\n{mem}\n"
            "Write production-quality, well-commented code. Use LaTeX delimiters ($...$, $$...$$) "
            "for all mathematical notation. Explain architectural decisions clearly."
        )

    else:  # normal
        system_content = base

    # ── Update or insert system message ──────────────────────────────────────
    if history and history[0].get('role') == 'system':
        history[0]['content'] = system_content
    else:
        history.insert(0, {'role': 'system', 'content': system_content})

    # ── Inject web search context into user turn ──────────────────────────────
    if search_enabled:
        search_result = web_search_action(user_message)
        content = f"[Live web search results]\n{search_result}\n\n[User message]\n{user_message}"
    else:
        content = user_message

    history.append({'role': 'user', 'content': content})

    model_name = get_model(agent_mode)

    # ── Google auth ───────────────────────────────────────────────────────────
    try:
        gmail_svc, cal_svc, drive_svc = get_google_services()
    except Exception as e:
        return f"Google auth error: {e}"

    # ── Inference ─────────────────────────────────────────────────────────────
    try:
        # Code & Math: no tools — dedicate all VRAM to pure generation
        if agent_mode == 'code_math':
            resp  = client.chat(model=model_name, messages=history)
            reply = resp['message']['content'].strip()
            history.append({'role': 'assistant', 'content': reply})
            return reply

        # All other modes: tool-calling enabled
        resp       = client.chat(model=model_name, messages=history, tools=AGENT_TOOLS)
        msg        = resp.get('message', {})
        tool_calls = msg.get('tool_calls', [])

        if tool_calls:
            history.append(msg)
            for tool in tool_calls:
                fn   = tool['function']['name']
                args = tool['function']['arguments']
                try:
                    if fn == 'send_email':
                        result = send_email_action(args['recipient'], args['subject'], args['body'], gmail_svc)
                    elif fn == 'read_recent_emails':
                        result = read_recent_emails_action(args.get('limit', 5), gmail_svc)
                    elif fn == 'add_calendar_event':
                        result = add_calendar_event_action(args['event_title'], args['start_time'], args['end_time'], cal_svc)
                    elif fn == 'list_calendar_events':
                        result = list_calendar_events_action(args.get('days_ahead', 7), cal_svc)
                    elif fn == 'search_drive':
                        result = search_drive_action(args['query'], drive_svc)
                    else:
                        result = f"Unknown tool: {fn}"
                except Exception as e:
                    result = friendly_error(e)
                history.append({'role': 'tool', 'content': result, 'name': fn})

            final = client.chat(model=model_name, messages=history)
            reply = final['message']['content'].strip()

        else:
            reply = msg.get('content', '').strip()
            if not reply:
                fb = keyword_fallback(user_message, gmail_svc, cal_svc, drive_svc)
                if fb:
                    history.append({'role': 'assistant', 'content': fb})
                    return fb
                reply = "Ready. What do you need?"

        history.append({'role': 'assistant', 'content': reply})
        return reply

    except Exception as e:
        fb = keyword_fallback(user_message, gmail_svc, cal_svc, drive_svc)
        if fb:
            history.append({'role': 'assistant', 'content': fb})
            return fb
        return f"Error: {e}. Make sure Ollama is running and the model '{model_name}' is pulled."


# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/auth/status')
def auth_status():
    if 'username' in session:
        return jsonify({'logged_in': True, 'username': session['username']})
    return jsonify({'logged_in': False})

@app.route('/auth/login', methods=['POST'])
def login():
    data     = request.json
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')
    users    = load_users()

    if username in users:
        if check_password_hash(users[username], password):
            session['username'] = username
            return jsonify({'success': True, 'message': f'Welcome back, {username.capitalize()}.'})
        return jsonify({'success': False, 'message': 'Incorrect password.'})
    else:
        if len(users) >= MAX_USERS:
            return jsonify({'success': False, 'message': 'Max users reached.'})
        users[username] = generate_password_hash(password)
        save_users(users)
        session['username'] = username
        return jsonify({'success': True, 'message': f'Account created. Welcome, {username.capitalize()}.'})

@app.route('/auth/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return jsonify({'success': True})

@app.route('/chat', methods=['POST'])
def chat():
    if 'username' not in session:
        return jsonify({'reply': 'Unauthorized'}), 401
    data  = request.json
    reply = run_jarvis(
        session['username'],
        data.get('message', ''),
        data.get('search_enabled', False),
        data.get('agent_mode', 'normal'),
    )
    return jsonify({'reply': reply})

@app.route('/get_profile')
def get_profile():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(load_user_profile(session['username']))

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        save_user_profile(session['username'], request.get_json())
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/clear_history', methods=['POST'])
def clear_history():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    active_sessions.pop(session['username'], None)
    return jsonify({'success': True})

# ── Entry point ───────────────────────────────────────────────────────────────
def start_flask():
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(1.2)
    webview.create_window('Jarvis', 'http://127.0.0.1:5000', width=1280, height=800)
    webview.start()