import streamlit as st
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.api_core import exceptions
import json
import io
import time
import bcrypt
import datetime
import re
import tempfile

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="CF Capital Fresh | Ultimate HVAC Pro", page_icon="❄️", layout="wide")

# --- CSS STYLING ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    .manual-box { background-color: #e0f2fe; color: #0369a1; padding: 15px; border-radius: 8px; border-left: 5px solid #0284c7; margin-bottom: 15px; }
    .ai-box { background-color: #f3e8ff; color: #6b21a8; padding: 15px; border-radius: 8px; border-left: 5px solid #9333ea; margin-bottom: 15px; }
    .analysis-box { background-color: #ecfccb; color: #3f6212; padding: 10px; border-radius: 8px; border: 1px dashed #84cc16; font-size: 14px; margin-bottom: 10px; }
    .error-box { background-color: #fef2f2; color: #991b1b; padding: 10px; border-radius: 8px; border: 1px solid #f87171; margin-bottom: 10px; }
</style>""", unsafe_allow_html=True)

# --- GLOBAL CONSTANTS ---
INDEX_FILE_NAME = "hvac_master_index_v13_auto.json"
USERS_FILE_NAME = "hvac_users.json"
LOGS_FILE_NAME = "hvac_logs.json"

# --- 1. SETUP GOOGLE SERVICES (AUTO-DETECT MODE) ---
auth_status = "⏳ Connecting..."
drive_service = None
CURRENT_MODEL_NAME = "gemini-pro" # Fallback default

try:
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        
        # --- AUTO-DISCOVERY LOGIC ---
        try:
            # Ζητάμε όλα τα μοντέλα που υποστηρίζουν 'generateContent'
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            
            # Λίστα Επιθυμίας (Από το καλύτερο στο παλαιότερο)
            wishlist = [
                "models/gemini-2.0-flash-exp", 
                "models/gemini-1.5-pro", 
                "models/gemini-1.5-flash",
                "models/gemini-1.0-pro",
                "models/gemini-pro"
            ]
            
            found_model = None
            for wish in wishlist:
                if wish in available_models:
                    found_model = wish
                    break
            
            if found_model:
                CURRENT_MODEL_NAME = found_model
                auth_status = f"✅ AI Online ({CURRENT_MODEL_NAME})"
            else:
                # Αν δεν βρει κανένα από τη λίστα, παίρνει το πρώτο διαθέσιμο
                if available_models:
                    CURRENT_MODEL_NAME = available_models[0]
                    auth_status = f"⚠️ Fallback AI: {CURRENT_MODEL_NAME}"
                else:
                    auth_status = "❌ No Models Found"

        except Exception as e:
            auth_status = f"⚠️ Model List Error: {e}"
            
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        info = json.loads(gcp_raw)
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status += " | ✅ Drive Online"
except Exception as e:
    auth_status = f"⚠️ Setup Error: {str(e)}"

# --- 2. DRIVE FUNCTIONS ---

def load_json_from_drive(filename):
    if not drive_service: return None
    try:
        results = drive_service.files().list(q=f"name = '{filename}' and trashed = false", fields="files(id)").execute()
        files = results.get('files', [])
        if files:
            file_id = files[0]['id']
            request = drive_service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False: _, done = downloader.next_chunk()
            content = fh.getvalue().decode('utf-8')
            if not content: return None
            return json.loads(content)
    except: pass
    return None

def save_json_to_drive(filename, data):
    if not drive_service: return
    try:
        results = drive_service.files().list(q=f"name = '{filename}' and trashed = false").execute()
        files = results.get('files', [])
        media = MediaIoBaseUpload(io.BytesIO(json.dumps(data, indent=2).encode('utf-8')), mimetype='application/json')
        if files:
            drive_service.files().update(fileId=files[0]['id'], media_body=media).execute()
        else:
            file_metadata = {'name': filename, 'mimeType': 'application/json'}
            drive_service.files().create(body=file_metadata, media_body=media).execute()
    except Exception as e:
        st.error(f"Save Error: {e}")

def get_all_pdf_files():
    if not drive_service: return []
    all_files = []
    page_token = None
    try:
        while True:
            response = drive_service.files().list(
                q="(mimeType = 'application/pdf' or mimeType = 'image/jpeg') and trashed = false",
                fields='nextPageToken, files(id, name)',
                pageSize=1000,
                pageToken=page_token
            ).execute()
            all_files.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None: break
        return all_files
    except: return []

def download_temp_for_ai(file_id, file_name):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    suffix = ".pdf" if ".pdf" in file_name.lower() else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(fh.getvalue())
        return tmp.name

# --- 3. INTELLIGENT AI CORE (AUTO-DETECTED MODEL) ---

def identify_model_deep_scan(file_path):
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME) 
        gfile = genai.upload_file(file_path)
        while gfile.state.name == "PROCESSING": 
            time.sleep(1)
            gfile = genai.get_file(gfile.name)
        
        prompt = """
        Εντόπισε: Brand, Model, Type (Service/User/Install), Device (AC/Boiler).
        JSON only: {"brand": "...", "model": "...", "type": "...", "device": "..."}
        """
        response = model.generate_content([prompt, gfile])
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match: return json.loads(match.group(0))
        return {"full_desc": response.text.strip(), "brand": "Unknown"}
    except: 
        return {"full_desc": "Detection Failed", "brand": "Error"}

def analyze_user_query_intent(query, history):
    """
    PRE-ANALYSIS (DEBUGGED)
    """
    prompt = f"""
    Είσαι ειδικός διαγνώστης HVAC.
    User Query: "{query}"
    
    1. Διόρθωσε ορθογραφικά (π.χ. "Aristn" -> "Ariston").
    2. Εντόπισε: Brand, Model, Error Code, Intent.
    
    Απάντησε ΑΥΣΤΗΡΑ σε JSON format:
    {{
        "corrected_query": "...", 
        "brand": "...",      
        "model": "...",
        "error_code": "...",
        "intent_summary": "..."
    }}
    """
    
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        resp = model.generate_content(prompt)
        text = resp.text
        
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            return {"corrected_query": query, "brand": None, "intent_summary": "Regex Parse Fail: " + text[:50]}
            
    except Exception as e:
        return {
            "corrected_query": query, 
            "brand": None, 
            "error_code": None, 
            "intent_summary": f"SYSTEM ERROR: {str(e)}"
        }

def get_ai_response_simple(full_prompt, media=None):
    """
    Απλή κλήση στο αυτο-εντοπισμένο μοντέλο.
    """
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        inputs = [full_prompt]
        if media: inputs.extend(media)
        resp = model.generate_content(inputs)
        return resp.text, None
    except Exception as e: 
        return None, str(e)

# --- 4. AUTH & LOGS ---
def hash_password(password): return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def check_password(password, hashed): 
    try: return bcrypt.checkpw(password.encode(), hashed.encode())
    except: return False
def log_activity(email, action, detail):
    logs = load_json_from_drive(LOGS_FILE_NAME) or []
    entry = {"timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": email, "action": action, "detail": detail}
    logs.append(entry)
    save_json_to_drive(LOGS_FILE_NAME, logs)

# --- 5. MAIN APP ---

if "master_index" not in st.session_state: st.session_state.master_index = load_json_from_drive(INDEX_FILE_NAME) or {}
if "users_db" not in st.session_state: st.session_state.users_db = load_json_from_drive(USERS_FILE_NAME) or {}
if "user_info" not in st.session_state: st.session_state.user_info = None

def login_page():
    st.title("🔐 CF Capital Fresh Portal")
    if "✅" in auth_status: st.success(auth_status)
    else: st.error(auth_status)
    
    t1, t2 = st.tabs(["Είσοδος", "Εγγραφή"])
    with t1:
        email = st.text_input("Email", key="l_email").lower().strip()
        password = st.text_input("Password", type="password", key="l_pass")
        if st.button("Login"):
            users = load_json_from_drive(USERS_FILE_NAME) or {}
            if email in users and check_password(password, users[email]['password']):
                if users[email].get('status') == 'active':
                    st.session_state.user_info = users[email]
                    st.session_state.user_info['email'] = email
                    st.rerun()
                else: st.warning("Ο λογαριασμός είναι υπό έγκριση.")
            else: st.error("Λάθος στοιχεία.")
    with t2:
        new_email = st.text_input("Email Εγγραφής").lower().strip()
        new_pass = st.text_input("Κωδικός", type="password")
        if st.button("Εγγραφή"):
            users = load_json_from_drive(USERS_FILE_NAME) or {}
            if new_email not in users:
                users[new_email] = {"name": "New User", "password": hash_password(new_pass), "role": "user", "status": "pending", "joined": str(datetime.date.today())}
                save_json_to_drive(USERS_FILE_NAME, users)
                st.success("Εγγραφή επιτυχής!")
            else: st.error("Το email υπάρχει ήδη.")

def main_app():
    user = st.session_state.user_info
    c1, c2 = st.columns([3,1])
    with c1: st.caption(f"👤 {user.get('name')} | 🤖 Connected to: {CURRENT_MODEL_NAME}")
    with c2: 
        if st.button("Logout"): st.session_state.user_info = None; st.rerun()

    # Admin Panel (Simplified)
    if user.get('role') == 'admin':
        with st.expander("👑 Admin Panel"):
            if st.button("Update Index"):
                st.info("Feature placeholder for safety.")

    st.divider()
    
    # Interface
    col_mode, col_tech = st.columns([2, 1])
    with col_mode:
        search_mode = st.radio("Λειτουργία:", ["🚀 Υβριδική", "📘 Μόνο Manual", "🧠 Μόνο Γενική Γνώση"], horizontal=True)
    with col_tech:
        tech_type = st.selectbox("Ειδικότητα", ["Κλιματισμός", "Ψύξη", "Λέβητες"])

    if "messages" not in st.session_state: st.session_state.messages = []
    for m in st.session_state.messages: 
        with st.chat_message(m["role"]): st.markdown(m["content"], unsafe_allow_html=True)

    if prompt := st.chat_input("Περιγραφή προβλήματος..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").markdown(prompt)
        
        with st.chat_message("assistant"):
            # 1. ANALYSIS
            with st.spinner(f"🧠 Ανάλυση (με {CURRENT_MODEL_NAME})..."):
                analysis = analyze_user_query_intent(prompt, st.session_state.messages)
            
            # Έλεγχος για σφάλμα συστήματος στην Ανάλυση
            if "SYSTEM ERROR" in str(analysis.get('intent_summary')):
                err_msg = analysis['intent_summary']
                st.markdown(f'<div class="error-box">🛑 ΣΦΑΛΜΑ ΣΥΝΔΕΣΗΣ: {err_msg}</div>', unsafe_allow_html=True)
                st.stop()
            
            debug_html = f"""<div class="analysis-box">
            <b>🕵️ Διάγνωση:</b> {analysis.get('intent_summary')}<br>
            <b>🎯 Στόχος:</b> {analysis.get('brand')} | {analysis.get('error_code')}
            </div>"""
            st.markdown(debug_html, unsafe_allow_html=True)
            st.session_state.messages.append({"role": "assistant", "content": debug_html})

            # 2. SEARCH
            found_manual_context = None
            found_media = []
            
            if "Γενική Γνώση" not in search_mode:
                if "master_index" not in st.session_state: st.session_state.master_index = load_json_from_drive(INDEX_FILE_NAME) or {}
                
                search_terms = []
                if analysis.get('brand'): search_terms.append(analysis['brand'].lower())
                if analysis.get('model'): search_terms.append(analysis['model'].lower())
                if not search_terms: search_terms = prompt.lower().split()

                candidates = []
                for fid, data in st.session_state.master_index.items():
                    meta_text = str(data).lower()
                    if any(t in meta_text for t in search_terms if len(t) > 2):
                        candidates.append((fid, data))

                if candidates:
                    fid, best_match = candidates[0]
                    st.markdown(f'<div class="manual-box">📖 Manual: {best_match["name"]}</div>', unsafe_allow_html=True)
                    with st.spinner("📥 Φόρτωση Manual..."):
                        try:
                            fpath = download_temp_for_ai(fid, best_match['name'])
                            gfile = genai.upload_file(fpath)
                            while gfile.state.name == "PROCESSING": time.sleep(1); gfile = genai.get_file(gfile.name)
                            found_media.append(gfile)
                            found_manual_context = f"Manual: {best_match['name']}"
                        except Exception as e:
                            st.error(f"File Error: {e}")

            # 3. GENERATION
            final_prompt = f"""
            Είσαι Τεχνικός {tech_type}.
            Πρόβλημα: {analysis.get('intent_summary')}
            Manual: {found_manual_context}
            Mode: {search_mode}
            
            ΟΔΗΓΙΕΣ:
            Δώσε τεχνική λύση βήμα-βήμα.
            """
            
            with st.spinner("✍️ Συγγραφή..."):
                resp, err = get_ai_response_simple(final_prompt, found_media)
            
            if resp:
                st.markdown(f'<div class="ai-box">{resp}</div>', unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": f'<div class="ai-box">{resp}</div>'})
            else:
                st.markdown(f'<div class="error-box">🛑 ΣΦΑΛΜΑ GENERATION: {err}</div>', unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": f"Error: {err}"})

if st.session_state.user_info is None: login_page()
else: main_app()
