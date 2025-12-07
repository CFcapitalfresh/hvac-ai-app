import streamlit as st
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from PIL import Image
import io
import json
import tempfile
import time
import datetime
import hashlib
from google.api_core import exceptions

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="CF HVAC SMART", page_icon="logo.png", layout="wide")

# --- CSS STYLING ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    .source-box { background-color: #d1fae5; color: #065f46; padding: 10px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #34d399;}
    .sidebar-footer { font-size: 13px; color: #444; text-align: center; padding-top: 15px; border-top: 1px solid #ddd; margin-top: 30px; background-color: #f9f9f9; border-radius: 10px; padding-bottom: 10px;}
    .sidebar-footer a { color: #0066cc; text-decoration: none;}
    .login-container { border: 1px solid #ddd; padding: 20px; border-radius: 10px; background-color: #f0f2f6; max-width: 500px; margin: auto; }
</style>""", unsafe_allow_html=True)

# --- 👑 ADMIN CONFIGURATION (ΒΑΛΕ ΤΟ EMAIL ΣΟΥ ΕΔΩ) ---
ADMIN_EMAIL = "capitalfresh@cytanet.com.cy" 
FILES = {
    "index": "hvac_master_index_v10.json",
    "users": "hvac_users.json",
    "logs": "hvac_logs.json"
}

# --- 1. ΣΥΝΔΕΣΗ & ΜΟΝΤΕΛΟ (Από Αρχείο 6 - Stable) ---
auth_status = "⏳ ..."
drive_service = None
CURRENT_MODEL_NAME = "gemini-1.5-flash" # Default safe start

try:
    # A. Setup Google AI
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        # Λογική Αυτόματης Επιλογής (File 6 Logic)
        try:
            all_models = [m.name.replace("models/", "") for m in genai.list_models()]
            priority_list = ["gemini-2.0-flash-exp", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]
            detected_model = None
            for wanted in priority_list:
                if wanted in all_models:
                    detected_model = wanted
                    break
            if detected_model:
                CURRENT_MODEL_NAME = detected_model
        except: pass

    # B. Setup Google Drive
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


# --- ΒΑΣΙΚΕΣ ΛΕΙΤΟΥΡΓΙΕΣ DATA & DRIVE ---

def load_json_file(filename, default_type={}):
    """Φορτώνει οποιοδήποτε JSON από το Drive"""
    if not drive_service: return default_type
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
            return json.loads(fh.getvalue().decode('utf-8'))
    except: pass
    return default_type

def save_json_file(filename, data):
    """Αποθηκεύει JSON στο Drive"""
    if not drive_service: return
    try:
        results = drive_service.files().list(q=f"name = '{filename}' and trashed = false").execute()
        files = results.get('files', [])
        media = MediaIoBaseUpload(io.BytesIO(json.dumps(data).encode('utf-8')), mimetype='application/json')
        if files:
            drive_service.files().update(fileId=files[0]['id'], media_body=media).execute()
        else:
            drive_service.files().create(body={'name': filename, 'mimeType': 'application/json'}, media_body=media).execute()
    except Exception as e: print(f"Save Error: {e}")

# Helper Functions
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def log_activity(user_email, action, details):
    """Ο ΚΑΤΑΣΚΟΠΟΣ: Καταγράφει τα πάντα"""
    logs = load_json_file(FILES["logs"], [])
    new_entry = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user_email,
        "action": action,
        "details": details
    }
    logs.append(new_entry)
    if len(logs) > 1000: logs = logs[-1000:] # Κρατάει τα τελευταία 1000
    save_json_file(FILES["logs"], logs)

def get_all_drive_files_meta():
    """Για το Sync"""
    if not drive_service: return []
    all_files = []
    page_token = None
    try:
        while True:
            response = drive_service.files().list(q="mimeType != 'application/vnd.google-apps.folder' and trashed = false", fields='nextPageToken, files(id, name)', pageSize=1000, pageToken=page_token).execute()
            all_files.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None: break
        return all_files
    except: return []

def download_temp(file_id, file_name):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    suffix = ".pdf" if ".pdf" in file_name.lower() else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(fh.getvalue())
        return tmp.name

def identify_model_with_ai(file_path):
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        gfile = genai.upload_file(file_path)
        while gfile.state.name == "PROCESSING": time.sleep(0.5); gfile = genai.get_file(gfile.name)
        prompt = "Διάβασε την πρώτη σελίδα. Ποια είναι η Μάρκα και το Μοντέλο; Απάντησε ΜΟΝΟ με Μάρκα/Μοντέλο. Αν δεν φαίνεται, γράψε 'Άγνωστο'."
        response = model.generate_content([prompt, gfile])
        return response.text.strip()
    except: return "Manual (Auto-detect failed)"


# --- SYSTEM LOGIC (LOGIN -> ADMIN -> USER) ---

if "user_email" not in st.session_state: st.session_state.user_email = None
if "user_role" not in st.session_state: st.session_state.user_role = None

# 1. ΟΘΟΝΗ ΕΙΣΟΔΟΥ (LOGIN)
if not st.session_state.user_email:
    col_l1, col_l2, col_l3 = st.columns([1,2,1])
    with col_l2:
        try: st.image("logo.png", use_column_width=True) 
        except: pass
        st.markdown("<h3 style='text-align: center;'>🔐 CF HVAC SMART SYSTEM</h3>", unsafe_allow_html=True)
        
        tab_in, tab_up = st.tabs(["Είσοδος", "Νέα Εγγραφή"])
        users_db = load_json_file(FILES["users"], {})

        with tab_in:
            email = st.text_input("Email", key="log_email").lower().strip()
            password = st.text_input("Κωδικός", type="password", key="log_pass")
            if st.button("Σύνδεση", type="primary", use_container_width=True):
                if email in users_db and users_db[email]["password"] == hash_password(password):
                    if users_db[email]["role"] == "pending":
                        st.warning("⏳ Ο λογαριασμός σας είναι υπό έγκριση.")
                    else:
                        st.session_state.user_email = email
                        st.session_state.user_role = "admin" if email == ADMIN_EMAIL.lower() else "user"
                        log_activity(email, "LOGIN", "Success")
                        st.rerun()
                else: st.error("❌ Λάθος στοιχεία")

        with tab_up:
            new_email = st.text_input("Email Εγγραφής", key="reg_email").lower().strip()
            new_pass = st.text_input("Κωδικός", type="password", key="reg_pass")
            
            st.markdown("""<small><b>ΔΗΛΩΣΗ ΑΠΟΡΡΗΤΟΥ (GDPR):</b> Αποδέχομαι την επεξεργασία δεδομένων για τη χρήση της εφαρμογής CF Capital Fresh.</small>""", unsafe_allow_html=True)
            gdpr = st.checkbox("Αποδέχομαι")
            
            if st.button("Εγγραφή", use_container_width=True):
                if not gdpr: st.error("Απαιτείται GDPR.")
                elif new_email in users_db: st.error("Υπάρχει ήδη.")
                elif len(new_pass) < 4: st.error("Κωδικός > 4 χαρακτήρες.")
                else:
                    role = "admin" if new_email == ADMIN_EMAIL.lower() else "pending"
                    users_db[new_email] = {
                        "password": hash_password(new_pass), 
                        "role": role, 
                        "registered_at": str(datetime.datetime.now()),
                        "gdpr_accepted": True
                    }
                    save_json_file(FILES["users"], users_db)
                    st.success("✅ Εγγραφή επιτυχής! Κάντε είσοδο.")
                    log_activity(new_email, "REGISTER", f"Role: {role}")

else:
    # === ΕΙΜΑΣΤΕ ΜΕΣΑ (LOGGED IN) ===
    
    # 2. SIDEBAR (ΜΕΝΟΥ)
    with st.sidebar:
        try: st.image("logo.png", use_column_width=True)
        except: pass
        
        st.write(f"👤 **{st.session_state.user_email}**")
        if st.session_state.user_role == "admin": st.success("👑 Administrator")
        
        if st.button("🚪 Αποσύνδεση"):
            st.session_state.user_email = None
            st.rerun()
        
        st.divider()
        
        # ΕΠΙΛΟΓΗ ΛΕΙΤΟΥΡΓΙΑΣ (ΜΟΝΟ ΓΙΑ ADMIN)
        if st.session_state.user_role == "admin":
            st.subheader("🛠️ Διαχείριση")
            admin_mode = st.radio("Εργαλεία:", ["💬 Chat", "👥 Χρήστες", "🕵️ Logs", "🔄 Sync"])
        else:
            admin_mode = "💬 Chat" # Οι χρήστες βλέπουν μόνο αυτό
            
        # FOOTER
        st.markdown("---")
        st.markdown(f"""
        <div class="sidebar-footer">
            <b>© {datetime.datetime.now().year} CF Capital Fresh</b><br>
            All Rights Reserved<br>
            📞 <a href="tel:0035796573878">+357 96573878</a><br>
            📧 <a href="mailto:capitalfresh@cytanet.com.cy">capitalfresh@cytanet.com.cy</a><br>
            🌐 <a href="https://cfcapitalfresh.github.io/CFcapitalfreshen.io./" target="_blank">Website</a>
        </div>
        """, unsafe_allow_html=True)

    # 3. ΚΥΡΙΩΣ ΠΕΡΙΕΧΟΜΕΝΟ

    # --- A. CHAT (ΚΟΙΝΟ ΓΙΑ ΟΛΟΥΣ) ---
    if admin_mode == "💬 Chat":
        st.title("CF HVAC SMART EXPERT")
        
        if "master_index" not in st.session_state:
            st.session_state.master_index = load_json_file(FILES["index"], {})

        c1, c2, c3 = st.columns(3)
        if "tech_mode" not in st.session_state: st.session_state.tech_mode = "Τεχνικός HVAC"
        if c1.button("❄️ AC Unit"): st.session_state.tech_mode = "Τεχνικός Κλιματισμού"
        if c2.button("🧊 Refrigeration"): st.session_state.tech_mode = "Ψυκτικός"
        if c3.button("🔥 Gas Burner"): st.session_state.tech_mode = "Τεχνικός Καυστήρων"
        st.caption(f"🔧 Mode: **{st.session_state.tech_mode}**")

        if "messages" not in st.session_state: st.session_state.messages = []
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

        user_input = st.chat_input("Γράψε βλάβη...")

        if user_input:
            log_activity(st.session_state.user_email, "SEARCH", user_input)
            st.session_state.messages.append({"role": "user", "content": user_input})
            with st.chat_message("user"): st.markdown(user_input)
            
            with st.chat_message("assistant"):
                found_data, media_items = None, []
                matches = []
                for fid, data in st.session_state.master_index.items():
                    full_text = (data['name'] + " " + data['model_info']).lower()
                    if user_input.lower() in full_text or any(k in full_text for k in user_input.split() if len(k)>3): 
                        matches.append((fid, data))
                
                if matches:
                    fid, data = matches[0]
                    found_data = f"{data['model_info']} ({data['name']})"
                    st.markdown(f'<div class="source-box">📖 Εντοπίστηκε: <b>{found_data}</b></div>', unsafe_allow_html=True)
                    try:
                        path = download_temp(fid, data['name'])
                        gf = genai.upload_file(path)
                        while gf.state.name == "PROCESSING": time.sleep(0.5); gf = genai.get_file(gf.name)
                        media_items.append(gf)
                    except: pass
                
                try:
                    model = genai.GenerativeModel(CURRENT_MODEL_NAME)
                    context = f"Manual: {found_data}" if found_data else "Χωρίς Manual (Γενική Γνώση)"
                    prompt = f"Είσαι {st.session_state.tech_mode}. {context}. Ερώτηση: {user_input}"
                    resp = model.generate_content([prompt, *media_items])
                    st.markdown(resp.text)
                    st.session_state.messages.append({"role": "assistant", "content": resp.text})
                except Exception as e: st.error(f"Error: {e}")

    # --- B. USER ADMIN (ΜΟΝΟ ΓΙΑ ADMIN) ---
    elif admin_mode == "👥 Χρήστες":
        st.header("Διαχείριση Πελατών")
        users_db = load_json_file(FILES["users"], {})
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.dataframe([{"Email": e, "Role": i["role"], "Joined": i.get("registered_at","")} for e, i in users_db.items()])
        with c2:
            st.subheader("Εγκρίσεις")
            pending = [u for u, d in users_db.items() if d["role"] == "pending"]
            if pending:
                u_sel = st.selectbox("Νέοι Χρήστες", pending)
                if st.button("✅ ΕΓΚΡΙΣΗ"):
                    users_db[u_sel]["role"] = "user"
                    save_json_file(FILES["users"], users_db)
                    log_activity(st.session_state.user_email, "APPROVE", u_sel)
                    st.success("Εγκρίθηκε!")
                    st.rerun()
            else: st.info("Κανένας νέος χρήστης.")
            
            st.divider()
            del_sel = st.selectbox("Διαγραφή", list(users_db.keys()))
            if st.button("🗑️ ΔΙΑΓΡΑΦΗ"):
                if del_sel == ADMIN_EMAIL.lower(): st.error("Όχι τον Admin!")
                else:
                    del users_db[del_sel]
                    save_json_file(FILES["users"], users_db)
                    st.rerun()

    # --- C. LOGS (ΜΟΝΟ ΓΙΑ ADMIN) ---
    elif admin_mode == "🕵️ Logs":
        st.header("Ο Κατάσκοπος")
        logs = load_json_file(FILES["logs"], [])
        st.dataframe(logs[::-1], height=600, use_container_width=True)

    # --- D. SYNC (ΜΟΝΟ ΓΙΑ ADMIN - ΚΩΔΙΚΑΣ ΑΡΧΕΙΟΥ 6) ---
    elif admin_mode == "🔄 Sync":
        st.header("Συγχρονισμός Βάσης")
        st.info("Ενημέρωση από το Google Drive")
        
        # --- ΑΥΤΟΣ ΕΙΝΑΙ Ο ΚΩΔΙΚΑΣ SYNC ΤΟΥ ΑΡΧΕΙΟΥ 6 ---
        enable_sync = st.toggle("Ενεργοποίηση Sync", value=False)
        
        if enable_sync:
            st.session_state.master_index = load_json_file(FILES["index"], {}) # Φόρτωση φρέσκου index
            if "drive_snapshot" not in st.session_state:
                with st.spinner("⏳ Λήψη λίστας αρχείων..."): st.session_state.drive_snapshot = get_all_drive_files_meta()
            
            drive_files_map = {f['id']: f['name'] for f in st.session_state.drive_snapshot}
            indexed_ids = set(st.session_state.master_index.keys())
            drive_ids = set(drive_files_map.keys())
            new_files_ids = list(drive_ids - indexed_ids)
            deleted_files_ids = list(indexed_ids - drive_ids)
            
            st.metric("Σύνολο Manuals", len(indexed_ids))
            
            if new_files_ids:
                st.info(f"🆕 Νέα Αρχεία: {len(new_files_ids)}")
                # SAFE SAVE (Από Αρχείο 6) -> 1 αρχείο τη φορά
                to_process = new_files_ids[:1] 
                
                for fid in to_process:
                    fname = drive_files_map[fid]
                    st.write(f"🔍 Ανάλυση: `{fname}`...")
                    try:
                        tmp_path = download_temp(fid, fname)
                        model_info = identify_model_with_ai(tmp_path)
                        st.session_state.master_index[fid] = {"name": fname, "model_info": model_info}
                    except Exception as e: print(f"Error {fname}: {e}")
                
                save_json_file(FILES["index"], st.session_state.master_index)
                st.rerun()
            
            elif deleted_files_ids:
                st.warning("🗑️ Καθαρισμός...")
                for did in deleted_files_ids: del st.session_state.master_index[did]
                save_json_file(FILES["index"], st.session_state.master_index)
                st.rerun()
            else:
                st.success("✅ Όλα ενημερωμένα")
