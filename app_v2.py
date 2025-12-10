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
import pandas as pd # Χρειαζόμαστε pandas για τον ωραίο πίνακα

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
INDEX_FILE_NAME = "hvac_master_index_v16_visual.json"
USERS_FILE_NAME = "hvac_users.json"
LOGS_FILE_NAME = "hvac_logs.json"

# --- 1. SETUP GOOGLE SERVICES (UNIVERSAL AUTO-SELECTOR) ---
auth_status = "⏳ Connecting..."
drive_service = None
CURRENT_MODEL_NAME = "gemini-pro" 

try:
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        try:
            all_models = list(genai.list_models())
            valid_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
            priority_list = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-1.0-pro", "models/gemini-pro"]
            selected_model = None
            for p in priority_list:
                if p in valid_models: selected_model = p; break
            if not selected_model and valid_models: selected_model = valid_models[0]
                
            if selected_model:
                CURRENT_MODEL_NAME = selected_model
                auth_status = f"✅ AI Online: {CURRENT_MODEL_NAME}"
            else: auth_status = "❌ No Valid Models Found"
        except Exception as e: auth_status = f"⚠️ Model Error: {e}"
            
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        info = json.loads(gcp_raw)
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/drive'])
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
        if files: drive_service.files().update(fileId=files[0]['id'], media_body=media).execute()
        else:
            file_metadata = {'name': filename, 'mimeType': 'application/json'}
            drive_service.files().create(body=file_metadata, media_body=media).execute()
    except Exception as e: st.error(f"Save Error: {e}")

def get_all_pdf_files():
    if not drive_service: return []
    all_files = []
    page_token = None
    try:
        while True:
            response = drive_service.files().list(q="(mimeType = 'application/pdf' or mimeType = 'image/jpeg') and trashed = false", fields='nextPageToken, files(id, name)', pageSize=1000, pageToken=page_token).execute()
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

# --- 3. INTELLIGENT AI CORE ---

def identify_model_deep_scan(file_path):
    try:
        time.sleep(1) 
        model = genai.GenerativeModel(CURRENT_MODEL_NAME) 
        gfile = genai.upload_file(file_path)
        while gfile.state.name == "PROCESSING": time.sleep(1); gfile = genai.get_file(gfile.name)
        
        prompt = """
        Analyze document. Return JSON only:
        {"brand": "...", "model": "...", "type": "...", "device": "..."}
        """
        response = model.generate_content([prompt, gfile])
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match: return json.loads(match.group(0))
        return {"full_desc": response.text.strip(), "brand": "Unknown"}
    except: return {"full_desc": "Detection Failed", "brand": "Error"}

def analyze_user_query_intent(query, history):
    prompt = f"""
    Act as HVAC Expert. Query: "{query}"
    Identify: Brand, Model, Error Code, Intent.
    Return STRICT JSON:
    {{ "corrected_query": "...", "brand": "...", "model": "...", "error_code": "...", "intent_summary": "..." }}
    """
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        resp = model.generate_content(prompt)
        match = re.search(r'\{.*\}', resp.text, re.DOTALL)
        if match: return json.loads(match.group(0))
        else: return {"corrected_query": query, "brand": None, "intent_summary": "Regex Fail"}
    except Exception as e: return {"corrected_query": query, "brand": None, "intent_summary": f"SYSTEM ERROR: {str(e)}"}

def get_ai_response_simple(full_prompt, media=None):
    try:
        time.sleep(1)
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        inputs = [full_prompt]
        if media: inputs.extend(media)
        resp = model.generate_content(inputs)
        return resp.text, None
    except exceptions.ResourceExhausted: return None, "Quota Exceeded. Wait 10s."
    except Exception as e: return None, str(e)

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
    with c1: st.caption(f"👤 {user.get('name')} | 🤖 Connected: **{CURRENT_MODEL_NAME}**")
    with c2: 
        if st.button("Logout"): st.session_state.user_info = None; st.rerun()

    # --- ADMIN PANEL: CONTROL & VISIBILITY ---
    if user.get('role') == 'admin':
        with st.expander("👑 Admin: Διαχείριση Βιβλιοθήκης", expanded=False):
            tab_sync, tab_view = st.tabs(["🔄 Ενημέρωση (Update)", "📊 Προβολή Αρχείων"])
            
            # TAB 1: UPDATE
            with tab_sync:
                st.info("Βήμα 1: Το κουμπί 'Scan' συγκρίνει το Drive με τη Βάση Δεδομένων.")
                if st.button("🔍 1. Scan Drive (Έλεγχος για νέα)"):
                    drive_files = get_all_pdf_files()
                    st.session_state.drive_snapshot = drive_files
                    index = load_json_from_drive(INDEX_FILE_NAME) or {}
                    st.session_state.master_index = index
                    # Βρες ποια IDs υπάρχουν στο Drive αλλά όχι στο Index
                    drive_ids = {f['id']: f['name'] for f in drive_files}
                    indexed_ids = set(index.keys())
                    st.session_state.new_files_ids = list(set(drive_ids.keys()) - indexed_ids)
                    
                    if st.session_state.new_files_ids:
                        st.warning(f"🆕 Βρέθηκαν {len(st.session_state.new_files_ids)} νέα αρχεία!")
                    else:
                        st.success("✅ Η βιβλιοθήκη είναι ενημερωμένη.")

                if "new_files_ids" in st.session_state and st.session_state.new_files_ids:
                    st.info("Βήμα 2: Το 'Deep Indexing' διαβάζει τα νέα αρχεία.")
                    if st.button(f"🚀 2. Deep Indexing ({len(st.session_state.new_files_ids)} αρχεία)"):
                        pbar = st.progress(0); txt = st.empty()
                        for i, fid in enumerate(st.session_state.new_files_ids):
                            fname = next((f['name'] for f in st.session_state.drive_snapshot if f['id'] == fid), "Unknown")
                            txt.text(f"Scanning: {fname}")
                            try:
                                path = download_temp_for_ai(fid, fname)
                                meta_data = identify_model_deep_scan(path)
                                # Αποθήκευση στο Index
                                st.session_state.master_index[fid] = {"name": fname, "deep_meta": meta_data}
                                save_json_to_drive(INDEX_FILE_NAME, st.session_state.master_index)
                            except Exception as e: print(e)
                            pbar.progress((i+1)/len(st.session_state.new_files_ids))
                        st.success("Ολοκληρώθηκε!"); st.session_state.new_files_ids = []
                        st.rerun()

            # TAB 2: VISIBILITY (ΠΙΝΑΚΑΣ)
            with tab_view:
                st.write("### 📂 Τι περιέχει η Βιβλιοθήκη;")
                if st.session_state.master_index:
                    # Μετατροπή JSON σε πίνακα για εύκολη ανάγνωση
                    table_data = []
                    for fid, data in st.session_state.master_index.items():
                        meta = data.get('deep_meta', {})
                        table_data.append({
                            "Filename": data['name'],
                            "Brand": meta.get('brand', '-'),
                            "Model": meta.get('model', '-'),
                            "Type": meta.get('type', '-')
                        })
                    df = pd.DataFrame(table_data)
                    st.dataframe(df, use_container_width=True)
                    st.caption(f"Σύνολο: {len(table_data)} αρχεία.")
                else:
                    st.warning("Η βιβλιοθήκη είναι άδεια.")

    st.divider()
    
    # --- INTERFACE ---
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
            
            if "SYSTEM ERROR" in str(analysis.get('intent_summary')):
                st.error(f"Σφάλμα: {analysis['intent_summary']}"); st.stop()
            
            debug_html = f"""<div class="analysis-box"><b>🕵️ Διάγνωση:</b> {analysis.get('intent_summary')}<br><b>🎯 Στόχος:</b> {analysis.get('brand')} | {analysis.get('error_code')}</div>"""
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
                    # Ψάχνουμε στα "Έξυπνα" Metadata
                    meta = data.get('deep_meta', {})
                    meta_text = (str(meta.get('brand')) + " " + str(meta.get('model')) + " " + data['name']).lower()
                    
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
                            found_manual_context = f"Manual Content from file: {best_match['name']}"
                        except Exception as e: st.error(f"File Error: {e}")

            # 3. GENERATION (ΜΕ ΔΙΑΧΩΡΙΣΜΟ ΠΗΓΩΝ)
            final_prompt = f"""
            Είσαι Τεχνικός {tech_type}.
            Πρόβλημα: {analysis.get('intent_summary')}
            Δεδομένα Manual: {found_manual_context if found_manual_context else "ΚΑΝΕΝΑ (Δεν βρέθηκε σχετικό αρχείο)"}
            Mode: {search_mode}
            
            ΟΔΗΓΙΕΣ ΑΠΑΝΤΗΣΗΣ (ΑΥΣΤΗΡΗ ΔΟΜΗ):
            
            1. Ξεκίνα με τίτλο: **📘 ΑΠΟ ΤΟ MANUAL**
            - Αν υπάρχει Manual, γράψε ΤΙ ΑΚΡΙΒΩΣ λέει για το πρόβλημα.
            - Αν δεν υπάρχει Manual, γράψε "Δεν βρέθηκε σχετική πληροφορία στα αρχεία".
            
            2. Άφησε μια κενή γραμμή.
            
            3. Συνέχισε με τίτλο: **🧠 ΑΠΟ ΓΕΝΙΚΗ ΓΝΩΣΗ**
            - Γράψε τη δική σου τεχνική άποψη, πιθανές λύσεις που ξέρεις από εμπειρία.
            
            Να είσαι ξεκάθαρος στο τι προέρχεται από πού.
            """
            
            with st.spinner("✍️ Συγγραφή..."):
                resp, err = get_ai_response_simple(final_prompt, found_media)
            
            if resp:
                st.markdown(f'<div class="ai-box">{resp}</div>', unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": f'<div class="ai-box">{resp}</div>'})
            else:
                st.error(f"Error: {err}")

if st.session_state.user_info is None: login_page()
else: main_app()
