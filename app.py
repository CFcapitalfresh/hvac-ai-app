import streamlit as st
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from PIL import Image
import io
import json
import tempfile
import os
import time

# --- ΡΥΘΜΙΣΕΙΣ ---
st.set_page_config(page_title="HVAC Auto-Pilot", page_icon="🤖", layout="centered")

# CSS
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ (AUTO-REPAIR KEY) ---
drive_service = None
auth_status = "⏳ Εκκίνηση..."

try:
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_info = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
        if "private_key" in gcp_info:
            gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")
        
        creds = service_account.Credentials.from_service_account_info(
            gcp_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Σύστημα: ON"
    else:
        auth_status = "⚠️ Λείπουν Secrets"
except Exception as e:
    auth_status = f"❌ Σφάλμα: {e}"

# --- STATE MANAGEMENT (ΜΝΗΜΗ) ---
if "messages" not in st.session_state: st.session_state.messages = []
if "active_file" not in st.session_state: st.session_state.active_file = None # Το manual που διαβάζει τώρα
if "file_list" not in st.session_state: st.session_state.file_list = [] # Λίστα αρχείων Drive

# --- FUNCTIONS ---
def get_drive_files():
    """Φέρνει τη λίστα αρχείων από το Drive (Cache)"""
    if not drive_service: return []
    try:
        # Αν έχουμε ήδη τη λίστα, δεν ξαναρωτάμε την Google (για ταχύτητα)
        if st.session_state.file_list: return st.session_state.file_list
        
        q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id, name, mimeType)", pageSize=50).execute()
        files = res.get('files', [])
        st.session_state.file_list = files
        return files
    except: return []

def find_relevant_file(query, files):
    """Ψάχνει ποιο αρχείο ταιριάζει με αυτό που έγραψε ο χρήστης"""
    query = query.lower()
    best_match = None
    for f in files:
        # Απλή λογική: Αν το όνομα του αρχείου υπάρχει στην ερώτηση
        # π.χ. Ερώτηση "Daikin" -> Αρχείο "Manual_Daikin.pdf"
        fname = f['name'].lower().replace(".pdf", "").replace(".jpg", "")
        if fname in query or query in fname:
            # Εξαιρούμε πολύ μικρές λέξεις για να μην μπερδεύεται
            if len(fname) > 3: 
                best_match = f
                break
    return best_match

def load_file_to_gemini(file_id, file_name):
    """Κατεβάζει και ανεβάζει στο Gemini"""
    with st.spinner(f"📖 Μελετάω το εγχειρίδιο: {file_name}..."):
        # 1. Download form Drive
        req = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while done is False: status, done = downloader.next_chunk()
        fh.seek(0)
        
        # 2. Save Temp
        suffix = ".pdf" if "pdf" in file_name.lower() else ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(fh.getvalue())
            tmp_path = tmp.name
        
        # 3. Upload to Gemini
        g_file = genai.upload_file(tmp_path)
        
        # Wait if video (optional check)
        if "video" in file_name:
             while g_file.state.name == "PROCESSING": time.sleep(1); g_file = genai.get_file(g_file.name)
             
        return g_file

def clear_chat():
    """Καθαρίζει τα πάντα για νέα βλάβη"""
    st.session_state.messages = []
    st.session_state.active_file = None
    st.toast("Μνήμη καθαρίστηκε! Έτοιμος για νέα βλάβη.", icon="🧹")

# --- SIDEBAR ---
with st.sidebar:
    st.title("🎛️ Χειριστήριο")
    st.caption(auth_status)
    
    if st.button("🗑️ ΝΕΑ ΒΛΑΒΗ / RESET", type="primary", use_container_width=True):
        clear_chat()
    
    st.divider()
    
    # Χειροκίνητη επιλογή (αν το αυτόματο δεν πιάσει)
    st.subheader("📂 Ενεργό Αρχείο")
    if st.session_state.active_file:
        st.info(f"📄 {st.session_state.active_file['user_name']}")
    else:
        st.warning("Κανένα (Γενική Γνώση)")
        
    st.divider()
    if st.button("🔄 Ανανέωση Λίστας Drive"):
        st.session_state.file_list = []
        get_drive_files()
        st.success("Λίστα ενημερώθηκε")

# --- MAIN UI ---
st.title("🤖 HVAC Auto-Pilot")

# Ειδικότητα
col1, col2, col3 = st.columns(3)
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"
if col1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if col2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if col3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"
st.caption(f"Λειτουργία: **{st.session_state.mode}**")

# Chat History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# --- INPUT LOGIC ---
prompt = st.chat_input("Γράψε βλάβη ή μάρκα (π.χ. 'Error E1 σε Daikin')...")

if prompt:
    # 1. Εμφάνιση ερώτησης
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    # 2. ΛΟΓΙΚΗ ΑΥΤΟΜΑΤΟΥ ΠΙΛΟΤΟΥ
    # Αν ΔΕΝ έχουμε ήδη ανοιχτό manual, ψάχνουμε τώρα
    if not st.session_state.active_file:
        files = get_drive_files() # Φέρνουμε λίστα
        match = find_relevant_file(prompt, files) # Ψάχνουμε match
        
        if match:
            # ΒΡΗΚΑΜΕ ΑΡΧΕΙΟ!
            msg_placeholder = st.empty()
            msg_placeholder.info(f"🔎 Βρήκα σχετικό αρχείο: **{match['name']}**. Το ανοίγω...")
            
            # Ανέβασμα στο AI
            gemini_file = load_file_to_gemini(match['id'], match['name'])
            
            # Αποθήκευση στη μνήμη
            st.session_state.active_file = {
                "obj": gemini_file,
                "user_name": match['name']
            }
            msg_placeholder.empty() # Σβήνουμε το μήνυμα "ψάχνω"
        else:
            # Δεν βρήκαμε, πάμε με γενική γνώση
            pass

    # 3. ΕΤΟΙΜΑΣΙΑ ΑΠΑΝΤΗΣΗΣ
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    parts = [f"Είσαι {st.session_state.mode}. Απάντησε στα Ελληνικά."]
    
    # Αν έχουμε ενεργό αρχείο, το βάζουμε στη συζήτηση
    if st.session_state.active_file:
        parts.append(st.session_state.active_file["obj"])
        parts.append(f"Βάση του εγχειριδίου '{st.session_state.active_file['user_name']}', απάντησε:")
    else:
        parts.append("Δεν βρέθηκε εγχειρίδιο. Απάντησε βάσει της εμπειρίας σου:")
        
    parts.append(prompt)

    # 4. STREAMING RESPONSE
    with st.chat_message("assistant"):
        try:
            stream = model.generate_content(parts, stream=True)
            response = st.write_stream(stream)
            st.session_state.messages.append({"role": "assistant", "content": response})
        except Exception as e:
            st.error(f"Σφάλμα: {e}")
