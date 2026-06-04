import os
import datetime
import webbrowser
import json
import ollama

# Google API Libraries
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Updated to include Google Drive Read-Only access
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/drive.readonly' 
]

def authenticate_google():
    """Handles the secure handshake with Google using your credentials.json."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("❌ Error: credentials.json not found in this folder!")
                return None
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

# --- Real System Tools ---

def open_browser(url):
    print(f"\n⚡ [Executing Tool] Opening browser to: {url}")
    webbrowser.open(url)
    return f"Success: Opened {url}"

def get_unread_emails():
    print("\n⚡ [Executing Tool] Fetching unread emails from Gmail...")
    creds = authenticate_google()
    if not creds: return "Could not authenticate with Google."
    
    try:
        service = build('gmail', 'v1', credentials=creds)
        results = service.users().messages().list(userId='me', q='is:unread', maxResults=5).execute()
        messages = results.get('messages', [])
        
        if not messages:
            return "You have no unread emails."
            
        summary = "Here are your top unread emails:\n"
        for msg in messages:
            txt = service.users().messages().get(userId='me', id=msg['id'], format='metadata').execute()
            headers = txt.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            summary += f"- From: {sender} | Subject: {subject}\n"
        return summary
    except Exception as e:
        return f"Error reading Gmail: {e}"

def get_upcoming_events():
    print("\n⚡ [Executing Tool] Accessing Google Calendar schedule...")
    creds = authenticate_google()
    if not creds: return "Could not authenticate with Google."
    
    try:
        service = build('calendar', 'v3', credentials=creds)
        now = datetime.datetime.utcnow().isoformat() + 'Z' 
        events_result = service.events().list(calendarId='primary', timeMin=now,
                                              maxResults=5, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        
        if not events:
            return "No upcoming events found on your schedule."
            
        summary = "Your next upcoming events are:\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary += f"- {start}: {event.get('summary')}\n"
        return summary
    except Exception as e:
        return f"Error reading Calendar: {e}"

def list_drive_files():
    """NEW TOOL: Scans the user's Google Drive for the most recent files."""
    print("\n⚡ [Executing Tool] Scanning Google Drive...")
    creds = authenticate_google()
    if not creds: return "Could not authenticate with Google."
    
    try:
        service = build('drive', 'v3', credentials=creds)
        # Pulls the 5 most recently modified files
        results = service.files().list(
            pageSize=5, 
            orderBy="modifiedTime desc",
            fields="files(name, mimeType)"
        ).execute()
        files = results.get('files', [])
        
        if not files:
            return "No files found in your Google Drive."
            
        summary = "Here are your most recent Google Drive files:\n"
        for file in files:
            # Clean up the display type a bit
            file_type = file['mimeType'].split('.')[-1].split('-')[-1].upper()
            summary += f"- {file['name']} [{file_type}]\n"
        return summary
    except Exception as e:
        return f"Error reading Google Drive: {e}"

# --- Main Engine Layer ---

def run_jarvis(user_message):
    system_prompt = (
        "You are Jarvis, a local desktop assistant.\n"
        "You have access to four tool protocols. If the user asks for an action matching a tool, "
        "you MUST reply with the exact tool execution line and absolutely nothing else.\n\n"
        "Tools:\n"
        "1. Open a website: TRIGGER_TOOL: open_browser | URL: <full_url>\n"
        "2. Check emails: TRIGGER_TOOL: get_unread_emails\n"
        "3. Check schedule: TRIGGER_TOOL: get_upcoming_events\n"
        "4. Check Drive files: TRIGGER_TOOL: list_drive_files\n\n"
        "If they are just chatting or asking a general question, answer normally as Jarvis."
    )
    
    print("\n🤖 Jarvis is processing...")
    
    try:
        response = ollama.chat(
            model='qwen2.5:1.5b',
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_message}
            ]
        )
        
        reply = response['message']['content'].strip()
        
        # Tool Routing Logic
        if "TRIGGER_TOOL: open_browser" in reply:
            parts = reply.split("| URL:")
            if len(parts) > 1:
                open_browser(parts[1].strip())
            else:
                print("Failed to parse URL.")
        elif "TRIGGER_TOOL: get_unread_emails" in reply:
            tool_result = get_unread_emails()
            print(f"\nJarvis: {tool_result}")
        elif "TRIGGER_TOOL: get_upcoming_events" in reply:
            tool_result = get_upcoming_events()
            print(f"\nJarvis: {tool_result}")
        elif "TRIGGER_TOOL: list_drive_files" in reply:
            tool_result = list_drive_files()
            print(f"\nJarvis: {tool_result}")
        else:
            print(f"\nJarvis: {reply}")
            
    except Exception as e:
        print(f"\n❌ Local AI Engine Error: {e}")

if __name__ == "__main__":
    print("--- Jarvis Connected Infrastructure Launching ---")
    print("[SYSTEM] Verifying secure token status...")
    authenticate_google()
    
    while True:
        prompt = input("\nYou: ")
        if prompt.lower() == 'exit':
            break
        if prompt.strip():
            run_jarvis(prompt)