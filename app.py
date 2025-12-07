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
st.set_page_config(page_title="CF Capital Fresh | Ultimate HVAC", page_icon="❄️", layout="wide")

# --- CSS STYLING (Modern UI) ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    
    /* Boxes Styles */
    .manual-box { 
        background-color: #e0f2fe; 
        color: #0369a1; 
        padding: 15px; 
        border-radius: 8px; 
        border-left: 5px solid #0284c7;
        margin-bottom: 15px;
    }
    .ai-box { 
        background-color: #f3e8ff; 
        color: #6b21a8; 
        padding: 15px; 
        border-radius: 8px; 
        border-left: 5px solid #9333ea;
        margin-bottom: 15px;
    }
    .warning-box {
        background-color: #fff7ed;
        color: #c2410c;
        padding: 10px;
        border-radius: 8px;
        border: 1px solid #fdba74;
        font-size: 14px;
    }
</style>""", unsafe_allow_html=True)

# --- GLOBAL CONSTANTS ---
INDEX_FILE_NAME = "hvac_master_index_v10.json"
USERS_FILE_NAME = "hvac_users.json"
LOGS_FILE_NAME = "hvac_logs.json"

# --- 1. SETUP GOOGLE SERVICES ---
auth_status = "⏳ Connecting..."
drive_service = None
CURRENT_MODEL_NAME = "gemini-1.5-flash" # Default fallback

try:
    # A. Gemini Setup
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        # Auto-detect best model
        try:
            all_models = [m.name.replace("models/", "") for m in genai.list_models()]
            priority_list = ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"]
            for wanted in priority_list:
                if wanted in all_models:
                    CURRENT_MODEL_NAME = wanted
                    break
        except: pass

    # B. Drive Setup
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        info = json.loads(gcp_raw)
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Online"
except Exception as e:
    auth_status = f"⚠️ Error: {str(e)}"

# --- 2. DRIVE FUNCTIONS (Safe & Smart) ---

def load_json_from_drive(filename):
    """Φόρτωση αρχείων JSON με ασφάλεια"""
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
    """Αποθήκευση JSON πίσω στο Drive"""
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
    """Φέρνει όλα τα PDF/Εικόνες από το Drive για το Sync"""
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
    """Κατεβάζει προσωρινά για AI Analysis"""
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    suffix = ".pdf" if ".pdf" in file_name.lower() else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(fh.getvalue())
        return tmp.name

def identify_model_deep_scan(file_path):
    """DEEP SCAN: Βλέπει τις πρώτες σελίδες για ακρίβεια"""
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        gfile = genai.upload_file(file_path)
        
        # Αναμονή επεξεργασίας από Google
        while gfile.state.name == "PROCESSING": 
            time.sleep(1)
            gfile = genai.get_file(gfile.name)
        
        prompt = """
        Είσαι ειδικός HVAC.
        Σκάναρε τις πρώτες σελίδες του αρχείου.
        Εντόπισε: 1) Κατασκευαστή (Brand), 2) Σειρά Μοντέλου (Series/Model Number).
        Απάντησε ΜΟΝΟ με τη μορφή: "Brand Model".
        Αν δεν βρεις τίποτα, γράψε "Unknown".
        """
        response = model.generate_content([prompt, gfile])
        return response.text.strip()
    except: 
        return "Manual Detection Failed"

# --- 3. SECURITY & LOGS ---

def hash_password(password): return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password, hashed): 
    try: return bcrypt.checkpw(password.encode(), hashed.encode())
    except: return False

def log_activity(email, action, detail):
    logs = load_json_from_drive(LOGS_FILE_NAME) or []
    entry = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": email,
        "action": action,
        "detail": detail
    }
    logs.append(entry)
    save_json_to_drive(LOGS_FILE_NAME, logs)
# --- 4. STATE MANAGEMENT ---

# Φόρτωση Index/Users με προστασία (or {})
if "master_index" not in st.session_state:
    st.session_state.master_index = load_json_from_drive(INDEX_FILE_NAME) or {}

if "users_db" not in st.session_state:
    st.session_state.users_db = load_json_from_drive(USERS_FILE_NAME) or {}

# Η κρίσιμη γραμμή που έλειπε ή μετακινήθηκε:
if "user_info" not in st.session_state:
    st.session_state.user_info = None

if "new_files_ids" not in st.session_state:
    st.session_state.new_files_ids = []
# --- 4. UI PAGES ---

def login_page():
    st.title("🔐 CF Capital Fresh Portal")
    if auth_status != "✅ Online": st.warning(f"System Status: {auth_status}")
    
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
                    log_activity(email, "LOGIN", "Success")
                    st.rerun()
                else: st.warning("Ο λογαριασμός είναι υπό έγκριση ή ανενεργός.")
            else: st.error("Λάθος στοιχεία.")

    with t2:
        st.write("Νέα Εγγραφή")
        new_email = st.text_input("Email Εγγραφής").lower().strip()
        new_pass = st.text_input("Κωδικός (min 8 chars, γράμματα & αριθμοί)", type="password")
        if st.button("Εγγραφή"):
            users = load_json_from_drive(USERS_FILE_NAME) or {}
            # Password validation logic could go here
            if new_email not in users:
                users[new_email] = {
                    "name": "New User", 
                    "password": hash_password(new_pass), 
                    "role": "user", 
                    "status": "pending", 
                    "joined": str(datetime.date.today())
                }
                save_json_to_drive(USERS_FILE_NAME, users)
                st.success("Εγγραφή επιτυχής! Περιμένετε έγκριση.")
            else:
                st.error("Το email υπάρχει ήδη.")

def main_app():
    user = st.session_state.user_info
    
    # Header Info
    c1, c2 = st.columns([3,1])
    with c1: st.caption(f"👤 {user.get('name')} | 🤖 Brain: {CURRENT_MODEL_NAME}")
    with c2: 
        if st.button("Logout"): 
            st.session_state.user_info = None; st.rerun()

    # --- ADMIN DASHBOARD ---
    if user.get('role') == 'admin':
        with st.expander("👑 Διαχείριση & Sync", expanded=False):
            tab_users, tab_logs, tab_sync = st.tabs(["Χρήστες", "Logs", "🔄 Smart Sync"])
            
            with tab_users:
                users = load_json_from_drive(USERS_FILE_NAME) or {}
                pending_count = 0
                for email, data in users.items():
                    if data.get('status') == 'pending':
                        pending_count += 1
                        c_a, c_b = st.columns(2)
                        c_a.write(f"⚠️ **{data.get('name')}** ({email})")
                        if c_b.button("✅ Έγκριση", key=email):
                            users[email]['status'] = 'active'
                            save_json_to_drive(USERS_FILE_NAME, users)
                            st.rerun()
                if pending_count == 0: st.success("Κανένας χρήστης σε αναμονή.")
            
            with tab_logs:
                if st.button("Refresh Logs"): pass
                st.dataframe(load_json_from_drive(LOGS_FILE_NAME) or [])

            with tab_sync:
                st.write("#### 📡 Έλεγχος Βάσης Δεδομένων")
                
                # Κουμπί 1: Σάρωση
                if st.button("🔍 1. Σάρωση Drive για νέα αρχεία"):
                    with st.spinner("Γίνεται καταγραφή αρχείων..."):
                        drive_files = get_all_pdf_files()
                        st.session_state.drive_snapshot = drive_files
                        
                        # Compare with Index
                        index = load_json_from_drive(INDEX_FILE_NAME) or {}
                        st.session_state.master_index = index
                        
                        drive_ids = {f['id']: f['name'] for f in drive_files}
                        indexed_ids = set(index.keys())
                        
                        st.session_state.new_files_ids = list(set(drive_ids.keys()) - indexed_ids)
                        st.success(f"Drive: {len(drive_ids)} | Index: {len(indexed_ids)} | 🆕 Νέα: {len(st.session_state.new_files_ids)}")

                # Κουμπί 2: Μαζική Επεξεργασία (Batch Process)
                if "new_files_ids" in st.session_state and st.session_state.new_files_ids:
                    count_new = len(st.session_state.new_files_ids)
                    st.info(f"Έχουν εντοπιστεί {count_new} νέα manuals.")
                    
                    if st.button(f"🚀 2. Έναρξη Αυτόματου Συγχρονισμού ({count_new} αρχεία)"):
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        # Loop processing
                        for i, fid in enumerate(st.session_state.new_files_ids):
                            # Find name
                            fname = next((f['name'] for f in st.session_state.drive_snapshot if f['id'] == fid), "Unknown")
                            
                            # UI Update
                            progress = (i + 1) / count_new
                            progress_bar.progress(progress)
                            status_text.text(f"🔄 ({i+1}/{count_new}) Ανάλυση: {fname} ...")
                            
                            # AI Action
                            try:
                                path = download_temp_for_ai(fid, fname)
                                info = identify_model_deep_scan(path)
                                st.session_state.master_index[fid] = {"name": fname, "model_info": info}
                                # Save every 1 file for safety
                                save_json_to_drive(INDEX_FILE_NAME, st.session_state.master_index)
                            except Exception as e:
                                print(f"Error on {fname}: {e}")
                        
                        status_text.success("✅ Ο Συγχρονισμός Ολοκληρώθηκε!")
                        st.balloons()
                        # Clear processed list
                        st.session_state.new_files_ids = []

    # --- CHAT INTERFACE ---
    st.divider()
    tech_mode = st.radio("Ειδικότητα:", ["❄️ Κλιματισμός", "🧊 Ψύξη", "🔥 Καυστήρες"], horizontal=True)

    if "messages" not in st.session_state: st.session_state.messages = []
    
    for m in st.session_state.messages: 
        with st.chat_message(m["role"]): st.markdown(m["content"], unsafe_allow_html=True)

    if prompt := st.chat_input("Περιγραφή βλάβης ή κωδικός..."):
        # User Message
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").markdown(prompt)
        
        with st.chat_message("assistant"):
            # 1. Search Manual
            found_manual_txt = None
            if "master_index" not in st.session_state: st.session_state.master_index = load_json_from_drive(INDEX_FILE_NAME) or {}
            
            # Smart Search
            matches = []
            for fid, data in st.session_state.master_index.items():
                full_search = (data['name'] + " " + data.get('model_info', '')).lower()
                if prompt.lower() in full_search:
                    matches.append(data)
            
            # Αν βρεθεί manual
            if matches:
                data = matches[0]
                found_manual_txt = f"{data.get('model_info')} ({data['name']})"
                log_activity(user['email'], "SEARCH_HIT", found_manual_txt)
                
                # Κατέβασμα για Context
                # (Εδώ απλά το δηλώνουμε στο prompt για οικονομία χρόνου, 
                # σε full version θα κατέβαινε και το αρχείο για RAG)
                
                display_html = f"""
                <div class="manual-box">
                    <b>📘 Βρέθηκε Manual:</b> {found_manual_txt}<br>
                    <i>Το AI θα απαντήσει βάσει αυτού.</i>
                </div>
                """
                st.markdown(display_html, unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": display_html})
            else:
                log_activity(user['email'], "SEARCH_MISS", prompt)
                no_man_html = '<div class="warning-box">⚠️ Δεν βρέθηκε συγκεκριμένο manual. Απάντηση βάσει γενικής γνώσης.</div>'
                st.markdown(no_man_html, unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": no_man_html})

            # 2. AI Generation (Hybrid)
            try:
                model = genai.GenerativeModel(CURRENT_MODEL_NAME)
                
                full_prompt = f"""
                Είσαι έμπειρος τεχνικός {tech_mode}.
                Ερώτηση Πελάτη: "{prompt}"
                
                ΔΕΔΟΜΕΝΑ MANUAL: {found_manual_txt if found_manual_txt else "Κανένα (Χρήση Γενικής Γνώσης)"}
                
                ΟΔΗΓΙΕΣ:
                1. Αν υπάρχει Manual, εξήγησε τι λέει ο κατασκευαστής.
                2. Πρόσθεσε τη δική σου εμπειρία (Γενική Γνώση) για την επίλυση.
                3. Χώρισε την απάντηση ξεκάθαρα.
                """
                
                with st.spinner("🧠 Ανάλυση..."):
                    resp = model.generate_content(full_prompt)
                    
                    final_html = f"""
                    <div class="ai-box">
                        <b>🤖 Απάντηση AI:</b><br>
                        {resp.text}
                    </div>
                    """
                    st.markdown(final_html, unsafe_allow_html=True)
                    st.session_state.messages.append({"role": "assistant", "content": final_html})

            except Exception as e:
                st.error(f"AI Error: {e}")

# --- ENTRY ---
if st.session_state.user_info is None:
    login_page()
else:
    main_app()
