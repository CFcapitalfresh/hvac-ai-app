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
import re

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="CF HVAC SMART SaaS", page_icon="logo.png", layout="wide")

# --- CSS STYLING ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    .source-box { background-color: #d1fae5; color: #065f46; padding: 10px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #34d399;}
    .sidebar-footer { font-size: 12px; color: #444; text-align: center; padding-top: 15px; border-top: 1px solid #ddd; margin-top: 30px; background-color: #f9f9f9; border-radius: 10px; padding-bottom: 10px;}
    .sidebar-footer a { color: #0066cc; text-decoration: none;}
    .login-box { border: 1px solid #ddd; padding: 20px; border-radius: 10px; background-color: #f8f9fa; max-width: 500px; margin: auto;}
</style>""", unsafe_allow_html=True)

# --- 👑 ADMIN CONFIGURATION (ΒΑΛΕ ΤΟ EMAIL ΣΟΥ ΕΔΩ!) ---
ADMIN_EMAIL = "nektal007@gmil.com"  # <--- ΑΛΛΑΞΕ ΤΟ ΑΝ ΘΕΣ ΑΛΛΟ EMAIL
FILES = {
    "index": "hvac_master_index_v10.json",
    "users": "hvac_users.json",
    "logs": "hvac_logs.json"
}

# --- GLOBAL VARIABLES ---
CURRENT_YEAR = datetime.datetime.now().year
drive_service = None

# --- AUTHENTICATION & DRIVE SETUP ---
def setup_services():
    global drive_service
    auth_status = "⏳ ..."
    try:
        if "GEMINI_KEY" in st.secrets:
            genai.configure(api_key=st.secrets["GEMINI_KEY"])
        if "GCP_SERVICE_ACCOUNT" in st.secrets:
            gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
            if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
            info = json.loads(gcp_raw)
            if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
            creds = service_account.Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/drive'])
            drive_service = build('drive', 'v3', credentials=creds)
            auth_status = "✅ Online"
    except Exception as e:
        auth_status = f"⚠️ Connection Error: {str(e)}"
    return auth_status

auth_msg = setup_services()

# --- DATABASE FUNCTIONS (Load/Save) ---
def load_json_file(filename, default_type={}):
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

# --- HELPER FUNCTIONS ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def log_activity(user_email, action, details):
    """Καταγράφει κινήσεις στο hvac_logs.json"""
    logs = load_json_file(FILES["logs"], [])
    new_entry = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user_email,
        "action": action,
        "details": details
    }
    logs.append(new_entry)
    # Κρατάμε μόνο τα τελευταία 1000 logs για ταχύτητα
    if len(logs) > 1000: logs = logs[-1000:]
    save_json_file(FILES["logs"], logs)

# --- LOGIN / REGISTER LOGIC ---
if "user_email" not in st.session_state: st.session_state.user_email = None
if "user_role" not in st.session_state: st.session_state.user_role = None

def login_screen():
    st.markdown("<h2 style='text-align: center;'>🔐 CF HVAC SMART EXPERT</h2>", unsafe_allow_html=True)
    
    tab_login, tab_register = st.tabs(["Είσοδος", "Νέα Εγγραφή"])
    
    users_db = load_json_file(FILES["users"], {})

    with tab_login:
        email = st.text_input("Email", key="login_email").lower().strip()
        password = st.text_input("Κωδικός", type="password", key="login_pass")
        
        if st.button("Σύνδεση", type="primary"):
            if email in users_db:
                if users_db[email]["password"] == hash_password(password):
                    if users_db[email]["role"] == "pending":
                        st.warning("⏳ Ο λογαριασμός σας είναι υπό έγκριση από τον διαχειριστή.")
                    else:
                        st.session_state.user_email = email
                        # Αν είναι το email του Admin, του δίνουμε ρόλο admin
                        if email == ADMIN_EMAIL.lower():
                            st.session_state.user_role = "admin"
                        else:
                            st.session_state.user_role = "user"
                        
                        log_activity(email, "LOGIN", "Επιτυχής σύνδεση")
                        st.rerun()
                else:
                    st.error("❌ Λάθος κωδικός")
            else:
                st.error("❌ Το email δεν βρέθηκε")

    with tab_register:
        st.info("Δημιουργήστε λογαριασμό για να αποκτήσετε πρόσβαση.")
        new_email = st.text_input("Email Εγγραφής", key="reg_email").lower().strip()
        new_pass = st.text_input("Κωδικός", type="password", key="reg_pass")
        new_pass_conf = st.text_input("Επιβεβαίωση Κωδικού", type="password", key="reg_pass_conf")
        
        # GDPR Checkbox
        gdpr_text = """
        **ΔΗΛΩΣΗ ΑΠΟΡΡΗΤΟΥ (GDPR):** Αποδέχομαι την επεξεργασία του email και του ιστορικού αναζητήσεων 
        για τη λειτουργία της υπηρεσίας CF Capital Fresh. Τα δεδομένα δεν πωλούνται σε τρίτους.
        """
        gdpr_check = st.checkbox("Διάβασα και αποδέχομαι τους όρους χρήσης και GDPR.")
        
        if st.button("Εγγραφή"):
            if not gdpr_check:
                st.error("⚠️ Πρέπει να αποδεχτείτε τους όρους GDPR.")
            elif new_pass != new_pass_conf:
                st.error("⚠️ Οι κωδικοί δεν ταιριάζουν.")
            elif len(new_pass) < 4:
                st.error("⚠️ Ο κωδικός πρέπει να είναι τουλάχιστον 4 ψηφία.")
            elif new_email in users_db:
                st.error("⚠️ Αυτό το email υπάρχει ήδη.")
            elif "@" not in new_email:
                st.error("⚠️ Μη έγκυρο email.")
            else:
                # Δημιουργία Χρήστη (Pending)
                # Αν είναι το δικό σου email, γίνεσαι αυτόματα approved admin
                role = "admin" if new_email == ADMIN_EMAIL.lower() else "pending"
                
                users_db[new_email] = {
                    "password": hash_password(new_pass),
                    "role": role,
                    "gdpr_date": str(datetime.datetime.now()),
                    "registered_at": str(datetime.datetime.now())
                }
                save_json_file(FILES["users"], users_db)
                st.success("✅ Η εγγραφή ολοκληρώθηκε! Αν είστε χρήστης, περιμένετε έγκριση.")
                log_activity(new_email, "REGISTER", "Νέα εγγραφή")

# --- MAIN APP LOGIC ---
if not st.session_state.user_email:
    login_screen()
    
else:
    # === ΕΙΜΑΣΤΕ ΜΕΣΑ (LOGGED IN) ===
    
    # 1. SIDEBAR (ΔΙΑΦΟΡΕΤΙΚΟ ΓΙΑ ADMIN / USER)
    with st.sidebar:
        try: st.image("logo.png", use_column_width=True)
        except: st.warning("No Logo")
        
        st.write(f"👤 **{st.session_state.user_email}**")
        if st.session_state.user_role == "admin":
            st.success("👑 Administrator")
        
        if st.button("🚪 Αποσύνδεση"):
            st.session_state.user_email = None
            st.session_state.user_role = None
            st.rerun()
            
        st.divider()
        
        # ADMIN PANEL ΜΟΝΟ ΓΙΑ ΕΣΕΝΑ
        if st.session_state.user_role == "admin":
            st.subheader("🛠️ Admin Tools")
            admin_mode = st.radio("Επιλογή:", ["💬 Chat", "👥 Χρήστες", "🕵️ Logs", "🔄 Sync"])
        else:
            admin_mode = "💬 Chat" # Οι χρήστες βλέπουν μόνο chat
            
        # FOOTER (Για όλους)
        st.markdown("---")
        st.markdown(f"""
        <div class="sidebar-footer">
            <b>© {CURRENT_YEAR} CF Capital Fresh</b><br>
            All Rights Reserved<br>
            📞 <a href="tel:0035796573878">+357 96573878</a><br>
            📧 <a href="mailto:capitalfresh@cytanet.com.cy">Support Email</a>
        </div>
        """, unsafe_allow_html=True)

    # 2. MAIN CONTENT AREA
    
    # --- A. CHAT (Η ΚΥΡΙΑ ΕΦΑΡΜΟΓΗ) ---
    if admin_mode == "💬 Chat":
        st.title("CF HVAC SMART EXPERT")
        
        # Load Index only when needed
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
            # Καταγραφή στο LOG
            log_activity(st.session_state.user_email, "SEARCH", user_input)
            
            st.session_state.messages.append({"role": "user", "content": user_input})
            with st.chat_message("user"): st.markdown(user_input)
            
            with st.chat_message("assistant"):
                # Search
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
                        # Download logic (reused)
                        req = drive_service.files().get_media(fileId=fid)
                        fh = io.BytesIO()
                        downloader = MediaIoBaseDownload(fh, req)
                        done = False
                        while done is False: _, done = downloader.next_chunk()
                        suffix = ".pdf" if ".pdf" in data['name'].lower() else ".jpg"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(fh.getvalue())
                            path = tmp.name
                        
                        gf = genai.upload_file(path)
                        while gf.state.name == "PROCESSING": time.sleep(0.5); gf = genai.get_file(gf.name)
                        media_items.append(gf)
                    except: pass
                
                # Generate Answer
                try:
                    model = genai.GenerativeModel("gemini-1.5-flash") # Ή το dynamic logic αν το θες
                    prompt = f"Είσαι {st.session_state.tech_mode}. Manual: {found_data or 'Όχι'}. Ερώτηση: {user_input}"
                    resp = model.generate_content([prompt, *media_items])
                    st.markdown(resp.text)
                    st.session_state.messages.append({"role": "assistant", "content": resp.text})
                except Exception as e: st.error(f"Error: {e}")

    # --- B. USER MANAGEMENT (MONO ADMIN) ---
    elif admin_mode == "👥 Χρήστες":
        st.header("Διαχείριση Χρηστών")
        users_db = load_json_file(FILES["users"], {})
        
        col_list, col_action = st.columns([2, 1])
        
        with col_list:
            st.subheader("Εγγεγραμμένοι")
            # Μετατροπή σε λίστα για εμφάνιση
            user_list = []
            for email, info in users_db.items():
                user_list.append({"Email": email, "Role": info["role"], "Date": info.get("registered_at", "-")})
            st.dataframe(user_list)
            
        with col_action:
            st.subheader("Ενέργειες")
            # Λίστα με Pending
            pending_users = [e for e, i in users_db.items() if i["role"] == "pending"]
            
            if pending_users:
                st.warning(f"⚠️ {len(pending_users)} χρήστες περιμένουν έγκριση!")
                user_to_approve = st.selectbox("Επιλογή για Έγκριση", pending_users)
                if st.button("✅ Έγκριση Χρήστη"):
                    users_db[user_to_approve]["role"] = "user"
                    save_json_file(FILES["users"], users_db)
                    st.success(f"Ο χρήστης {user_to_approve} εγκρίθηκε!")
                    log_activity(st.session_state.user_email, "ADMIN_APPROVE", user_to_approve)
                    st.rerun()
            else:
                st.success("Κανένας νέος χρήστης.")
                
            st.divider()
            # Διαγραφή
            user_to_delete = st.selectbox("Επιλογή για Διαγραφή", list(users_db.keys()))
            if st.button("🗑️ Διαγραφή Χρήστη"):
                if user_to_delete == ADMIN_EMAIL.lower():
                    st.error("Δεν μπορείς να διαγράψεις τον Admin!")
                else:
                    del users_db[user_to_delete]
                    save_json_file(FILES["users"], users_db)
                    st.warning(f"Διαγράφηκε: {user_to_delete}")
                    st.rerun()

    # --- C. ACTIVITY LOGS (MONO ADMIN) ---
    elif admin_mode == "🕵️ Logs":
        st.header("Ιστορικό Δραστηριότητας")
        logs = load_json_file(FILES["logs"], [])
        # Εμφάνιση των τελευταίων πρώτα
        st.dataframe(logs[::-1], height=500)

    # --- D. SYNC (MONO ADMIN) ---
    elif admin_mode == "🔄 Sync":
        st.header("Συγχρονισμός Βάσης")
        
        # Λογική Sync (ίδια με παλιά, απλά μέσα στο admin panel)
        if st.button("Εκκίνηση Σάρωσης Drive", type="primary"):
            st.session_state.master_index = load_json_file(FILES["index"], {})
            
            def get_all_drive_files_meta():
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

            drive_snapshot = get_all_drive_files_meta()
            drive_files_map = {f['id']: f['name'] for f in drive_snapshot}
            indexed_ids = set(st.session_state.master_index.keys())
            drive_ids = set(drive_files_map.keys())
            new_files_ids = list(drive_ids - indexed_ids)
            
            if new_files_ids:
                st.info(f"🆕 Βρέθηκαν {len(new_files_ids)} νέα αρχεία. Ξεκινάω...")
                progress_bar = st.progress(0)
                
                for i, fid in enumerate(new_files_ids):
                    fname = drive_files_map[fid]
                    st.write(f"🔍 Ανάλυση ({i+1}/{len(new_files_ids)}): `{fname}`")
                    
                    # AI Vision Logic
                    try:
                        # Download temp
                        req = drive_service.files().get_media(fileId=fid)
                        fh = io.BytesIO()
                        downloader = MediaIoBaseDownload(fh, req)
                        done = False
                        while done is False: _, done = downloader.next_chunk()
                        suffix = ".pdf" if ".pdf" in fname.lower() else ".jpg"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(fh.getvalue())
                            tmp_path = tmp.name
                        
                        # AI Identify
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        gfile = genai.upload_file(tmp_path)
                        while gfile.state.name == "PROCESSING": time.sleep(0.5); gfile = genai.get_file(gfile.name)
                        prompt = "Διάβασε την πρώτη σελίδα. Ποια είναι η Μάρκα και το Μοντέλο; Απάντησε ΜΟΝΟ με Μάρκα/Μοντέλο."
                        res = model.generate_content([prompt, gfile])
                        model_info = res.text.strip()
                        
                        # Update & Save per file
                        st.session_state.master_index[fid] = {"name": fname, "model_info": model_info}
                        save_json_file(FILES["index"], st.session_state.master_index)
                        
                    except Exception as e: st.error(f"Error on {fname}: {e}")
                    
                    progress_bar.progress((i + 1) / len(new_files_ids))
                
                st.success("✅ Ολοκληρώθηκε!")
                log_activity(st.session_state.user_email, "SYNC", f"Προστέθηκαν {len(new_files_ids)} manuals")
            else:
                st.success("✅ Όλα ενημερωμένα.")
