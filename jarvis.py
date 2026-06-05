import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import json
import ollama
import secrets
import datetime
import re
from flask import Flask, request, jsonify, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash
from duckduckgo_search import DDGS

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/drive.metadata.readonly'
]

def get_google_services():
    """Authenticates the user and returns the Google API service objects."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    gmail_service = build('gmail', 'v1', credentials=creds)
    calendar_service = build('calendar', 'v3', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return gmail_service, calendar_service, drive_service

app = Flask(__name__)
app.secret_key = os.urandom(24).hex() 

USERS_FILE = 'users.json'
MAX_USERS = 5
ADMIN_USER = "oliver"
MODEL_NAME = "llama3.2"   # This is the 3B model, which is much better at logic   # More reliable for tool calling

pending_resets = {}

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

def load_user_profile(username):
    path = f"profile_{username}.json"
    if os.path.exists(path):
        with open(path, 'r') as file:
            return json.load(file)
    return {}

def save_user_profile(username, profile: dict):
    with open(f"profile_{username}.json", 'w') as f:
        json.dump(profile, f, indent=4)

# --- REAL GOOGLE API ACTIONS (no fallback) ---
def send_email_action(recipient, subject, body, gmail_svc):
    from email.message import EmailMessage
    import base64
    msg = EmailMessage()
    msg.set_content(body)
    msg['To'] = recipient
    msg['Subject'] = subject
    raw_msg = {'raw': base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    gmail_svc.users().messages().send(userId="me", body=raw_msg).execute()
    return f"✅ Email sent to {recipient}."

def add_calendar_event_action(event_title, start_time, end_time, calendar_svc):
    # This forces the formatting to ensure Google doesn't reject the request
    # Expecting input like "2026-06-13T13:00:00"
    # We append "-04:00" for Eastern Daylight Time (June)
    if "-04:00" not in start_time:
        start_time = f"{start_time}-04:00"
    if "-04:00" not in end_time:
        end_time = f"{end_time}-04:00"

    event = {
        'summary': event_title,
        'start': {'dateTime': start_time},
        'end': {'dateTime': end_time},
    }
    
    # Execute the actual API call
    result = calendar_svc.events().insert(calendarId='primary', body=event).execute()
    return f"✅ Success! Added '{event_title}' to your calendar."

def search_drive_action(query, drive_svc):
    results = drive_svc.files().list(
        q=f"name contains '{query}'", 
        pageSize=5, 
        fields="files(name)"
    ).execute()
    files = results.get('files', [])
    if files:
        return f"📁 Found files: {', '.join([f['name'] for f in files])}"
    return "No files found."

def web_search_action(query):
    try:
        results = DDGS().text(query, max_results=3)
        if not results: return "No search results."
        formatted = "\n".join([f"- {res['title']}: {res['body']}" for res in results])
        return f"🌐 Web search results:\n{formatted}"
    except Exception as e:
        return f"Search failed: {e}"

# --- KEYWORD FALLBACK (when LLM fails to call tools) ---
def keyword_fallback(user_message, gmail_svc, cal_svc, drive_svc):
    msg_lower = user_message.lower()
    
    # Email detection
    if "email" in msg_lower or "mail" in msg_lower:
        # Try to extract recipient, subject, body using simple patterns
        recipient_match = re.search(r'to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', user_message, re.I)
        if not recipient_match:
            return "I need an email address. Please say: 'Send email to address@example.com subject Hello body Hi'"
        recipient = recipient_match.group(1)
        
        subject_match = re.search(r'subject\s+(.+?)(?:\s+body\s+|$)', user_message, re.I)
        subject = subject_match.group(1) if subject_match else "No subject"
        
        body_match = re.search(r'body\s+(.+)$', user_message, re.I)
        body = body_match.group(1) if body_match else "Message from Jarvis"
        
        return send_email_action(recipient, subject, body, gmail_svc)
    
    # Calendar detection
    if "calendar" in msg_lower or "event" in msg_lower or "meeting" in msg_lower:
        # Expect format: "Add event Title tomorrow at 2pm for 1 hour"
        title_match = re.search(r'(?:event|meeting)\s+(.+?)\s+(?:on|at|tomorrow|today)', user_message, re.I)
        title = title_match.group(1) if title_match else "Untitled Event"
        # For simplicity, use current time + 1 hour as demo
        now = datetime.datetime.utcnow()
        start = now.isoformat() + "Z"
        end = (now + datetime.timedelta(hours=1)).isoformat() + "Z"
        return add_calendar_event_action(title, start, end, cal_svc)
    
    # Drive search
    if "drive" in msg_lower or "search drive" in msg_lower or "find file" in msg_lower:
        query_match = re.search(r'(?:search|find)\s+(?:drive\s+)?(?:for\s+)?(.+)$', user_message, re.I)
        query = query_match.group(1) if query_match else user_message
        return search_drive_action(query, drive_svc)
    
    # Web search
    if "search" in msg_lower or "google" in msg_lower or "what is" in msg_lower or "who is" in msg_lower:
        query_match = re.search(r'(?:search|google|what is|who is)\s+(.+)', user_message, re.I)
        if query_match:
            return web_search_action(query_match.group(1))
    
    return None  # No fallback triggered

# --- TOOL SCHEMA (unchanged but now used with fallback) ---
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"}
                },
                "required": ["recipient", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_calendar_event",
            "description": "Add calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_title": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"}
                },
                "required": ["event_title", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_drive",
            "description": "Search Google Drive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Web search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }
    }
]

active_sessions = {}

def run_jarvis(username, user_message):
    global active_sessions
    if username not in active_sessions:
        active_sessions[username] = []
    
    history = active_sessions[username]
    is_admin = (username.lower() == ADMIN_USER)
    
    # Add system prompt once
    if is_admin and not any(m.get('role') == 'system' for m in history):
        history.insert(0, {
            'role': 'system',
            'content': 'You are Jarvis, a helpful assistant. Use the provided tools when asked to send emails, add calendar events, search Drive, or search the web. If you cannot use tools, just answer conversationally.'
        })
    
    # Authenticate Google services
    try:
        gmail_svc, cal_svc, drive_svc = get_google_services()
    except Exception as e:
        return f"Authentication error: {e}"
    
    history.append({'role': 'user', 'content': user_message})
    
    # Attempt LLM tool calling
    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=history,
            tools=AGENT_TOOLS if is_admin else []
        )
        
        msg = response.get('message', {})
        tool_calls = msg.get('tool_calls', [])
        
        if tool_calls:
            # Execute the tool calls
            history.append(msg)
            for tool in tool_calls:
                func_name = tool['function']['name']
                args = tool['function']['arguments']
                result = ""
                try:
                    if func_name == 'send_email':
                        result = send_email_action(args['recipient'], args['subject'], args['body'], gmail_svc)
                    elif func_name == 'add_calendar_event':
                        result = add_calendar_event_action(args['event_title'], args['start_time'], args['end_time'], cal_svc)
                    elif func_name == 'search_drive':
                        result = search_drive_action(args['query'], drive_svc)
                    elif func_name == 'web_search':
                        result = web_search_action(args['query'])
                    else:
                        result = f"Unknown tool: {func_name}"
                except Exception as e:
                    result = f"Tool execution error: {e}"
                history.append({'role': 'tool', 'content': result, 'name': func_name})
            
            # Get final response after tool calls
            final = ollama.chat(model=MODEL_NAME, messages=history)
            reply = final['message']['content'].strip()
            history.append({'role': 'assistant', 'content': reply})
            return reply
        
        else:
            # No tool calls – normal text response
            reply = msg.get('content', '').strip()
            if not reply:
                # Empty response – fallback to keyword matching
                fallback = keyword_fallback(user_message, gmail_svc, cal_svc, drive_svc)
                if fallback:
                    history.append({'role': 'assistant', 'content': fallback})
                    return fallback
                else:
                    reply = "I'm here. How can I help?"
            history.append({'role': 'assistant', 'content': reply})
            return reply
    
    except Exception as e:
        # Ollama error – fallback to keyword matching
        print(f"Ollama error: {e}")
        fallback = keyword_fallback(user_message, gmail_svc, cal_svc, drive_svc)
        if fallback:
            history.append({'role': 'assistant', 'content': fallback})
            return fallback
        return f"Agent error: {e}"

# --- FLASK ROUTES (unchanged) ---
@app.route("/")
def home(): 
    return render_template("index.html")

@app.route("/auth/status", methods=["GET"])
def auth_status():
    if 'username' in session:
        return jsonify({"logged_in": True, "username": session['username']})
    return jsonify({"logged_in": False})

@app.route("/auth/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    users = load_users()
    
    if username in users:
        if check_password_hash(users[username], password):
            session['username'] = username
            return jsonify({"success": True, "message": f"Welcome back, {username.capitalize()}."})
        return jsonify({"success": False, "message": "Incorrect password."})
    else:
        if len(users) >= MAX_USERS:
            return jsonify({"success": False, "message": "Max users reached."})
        users[username] = generate_password_hash(password)
        save_users(users)
        session['username'] = username
        return jsonify({"success": True, "message": f"Welcome, {username.capitalize()}."})

@app.route("/auth/logout", methods=["POST"])
def logout():
    session.pop('username', None)
    return jsonify({"success": True})

@app.route("/auth/request_reset", methods=["POST"])
def request_reset():
    username = request.json.get("username", "").lower()
    if username not in load_users():
        return jsonify({"success": False, "message": "User not found."})
    token = secrets.token_hex(3)
    pending_resets[username] = token
    print(f"\n[!!!] PASSWORD RESET REQUESTED [!!!]\nUser: {username}\nTOKEN: {token}\n----------------------------------\n")
    return jsonify({"success": True, "message": "Check the server terminal for your token."})

@app.route("/auth/confirm_reset", methods=["POST"])
def confirm_reset():
    data = request.json
    u, t, p = data.get("username").lower(), data.get("token"), data.get("new_password")
    if pending_resets.get(u) == t:
        users = load_users()
        users[u] = generate_password_hash(p)
        save_users(users)
        del pending_resets[u]
        return jsonify({"success": True, "message": "Password updated successfully."})
    return jsonify({"success": False, "message": "Invalid token."})

@app.route("/chat", methods=["POST"])
def chat():
    if 'username' not in session: 
        return jsonify({"reply": "Unauthorized"}), 401
    return jsonify({"reply": run_jarvis(session['username'], request.json.get("message", ""))})

@app.route("/get_profile", methods=["GET"])
def get_profile():
    if 'username' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    profile = load_user_profile(session['username'])
    return jsonify(profile)

@app.route("/update_profile", methods=["POST"])
def update_profile():
    if 'username' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        new_profile = request.get_json()
        if isinstance(new_profile, dict):
            save_user_profile(session['username'], new_profile)
            return jsonify({"success": True})
        return jsonify({"error": "Invalid format"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)