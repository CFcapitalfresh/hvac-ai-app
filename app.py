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

# --- SETUP ---
st.set_page_config(page_title="HVAC Ultimate", page_icon="🎛️", layout="centered")

# CSS (Dark Mode & Clean Look)
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
    /* Κάνουμε τα μηνύματα του AI πιο διακριτά */
    div[data-testid="stChatMessage"]:nth-child(even) { background-color: #1e293b; }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ (ROBUST AUTH) ---
auth_status = "⏳ Σύνδεση..."
drive_service = None

try:
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        info = json.loads(gcp_raw)
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
            
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        drive_service.files().list(pageSize=1).execute()
        auth_status = "✅ Όλα Συνδεδεμένα"
    else:
        auth_status = "⚠️ Λείπει το Drive Key"
except Exception as e:
    auth_status = f"⚠️ Status: {str(e)}"

# --- SIDEBAR (ΡΥΘΜΙΣΕΙΣ) ---
with st.sidebar:
    st.title("🎛️ Κέντρο Ελέγχου")
    if "✅" in auth_status:
        st.success(auth_status)
    else:
        st.warning(auth_status)
    
    st.divider()
    
    # 1. ΕΠΙΛΟΓΗ ΠΗΓΗΣ ΓΝΩΣΗΣ
    st.subheader("🔍 Πού να ψάξω;")
    search_mode = st.radio(
        "Πηγή Δεδομένων:",
        ["🧠 Συνδυασμός (Smart)", "📚 Μόνο Manuals (Drive)", "🌐 Γενική Γνώση (AI)"],
        index=0,
        help="Επίλεξε πού θα βασιστεί η απάντηση."
    )
    
    st.divider()
    
    # 2. ΕΠΙΛΟΓΗ ΜΟΝΤΕΛΟΥ (Χειροκίνητη ή Αυτόματη)
    use_autopilot = st.toggle("🤖 Αυτόματη Επιλογή Μοντέλου", value=True)
    if not use_autopilot:
        model_option = st.selectbox("Επίλεξε Μοντέλο", ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"])
    
    st.divider()
    if st.button("🗑️ Νέα Συζήτηση"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER ---
st.title("🎛️ HVAC Ultimate Control")

# --- FUNCTIONS ---
def list_drive_files():
    if not drive_service: return []
    try:
        q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id, name, mimeType)", pageSize=20).execute()
        return res.get('files', [])
    except: return []

def download_drive_file(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

# --- SMART MODEL LOGIC ---
def generate_response(prompt_content, forced_model=None):
    # Αν ο χρήστης διάλεξε μοντέλο χειροκίνητα
    if forced_model:
        model = genai.GenerativeModel(forced_model)
        return model.generate_content(prompt_content).text, forced_model

    # Αλλιώς Αυτόματος Πιλότος (σειρά προτεραιότητας)
    models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]
    for m in models:
        try:
            model = genai.GenerativeModel(m)
            return model.generate_content(prompt_content).text, m
        except: continue
    raise Exception("Busy")

# --- UI STATE ---
if "messages" not in st.session_state: st.session_state.messages = []

# Ειδικότητα
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"
st.caption(f"Ειδικότητα: **{st.session_state.mode}**")

# Tabs
tab1, tab2 = st.tabs(["📸 Live", "☁️ Drive"])

with tab1:
    use_cam = st.checkbox("Κάμερα")
    cam_img = st.camera_input("Λήψη") if use_cam else None

with tab2:
    if drive_service:
        # Φορτώνουμε λίστα μόνο αν ζητηθεί για να μην αργεί
        if "files" not in st.session_state:
             if st.button("🔄 Φόρτωση Λίστας Drive"):
                with st.spinner("Σάρωση..."):
                    st.session_state.files = list_drive_files()
        
        sel_file = None
        if "files" in st.session_state and st.session_state.files:
            opts = {f['name']: f['id'] for f in st.session_state.files}
            s = st.selectbox("Αρχείο:", ["--"] + list(opts.keys()))
            if s != "--": sel_file = {"id": opts[s], "name": s}

# --- CHAT ---
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

prompt = st.chat_input("Ερώτηση...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    media = []
    # 1. Camera
    if cam_img: media.append(Image.open(cam_img))
    
    # 2. Drive File (Μόνο αν ΔΕΝ είναι "Γενική Γνώση")
    if "Γενική Γνώση" not in search_mode and sel_file:
        with st.spinner(f"📥 Μελέτη {sel_file['name']}..."):
            try:
                stream = download_drive_file(sel_file['id'])
                suffix = ".pdf" if "pdf" in sel_file['name'].lower() else ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(stream.getvalue())
                    path = tmp.name
                
                gfile = genai.upload_file(path)
                while gfile.state.name == "PROCESSING": time.sleep(1); gfile = genai.get_file(gfile.name)
                media.append(gfile)
            except Exception as e:
                st.error(f"Error file: {e}")

    # 3. Δημιουργία System Prompt (Ευγένεια & Έλεγχος)
    system_instruction = f"""
    Είσαι ένας εξαιρετικά ευγενικός και έμπειρος {st.session_state.mode}.
    Μιλάς πάντα στον πληθυντικό ευγενείας ή φιλικά αλλά με σεβασμό.
    
    ΟΔΗΓΙΕΣ ΣΥΜΠΕΡΙΦΟΡΑΣ:
    1. Αν ο χρήστης σε διορθώσει, ζήτα συγγνώμη αμέσως και διόρθωσε την απάντησή σου. Μην επιμένεις.
    2. Αν δεν ξέρεις κάτι, πες το ειλικρινά και ευγενικά.
    3. Απάντα στα Ελληνικά.
    
    ΟΔΗΓΙΕΣ ΑΝΑΖΗΤΗΣΗΣ ({search_mode}):
    """
    
    if "Μόνο Manuals" in search_mode:
        system_instruction += "\n- ΑΠΑΝΤΑ ΜΟΝΟ βάσει των αρχείων που σου δόθηκαν. Αν η απάντηση δεν είναι στα αρχεία, πες 'Δυστυχώς δεν το βρίσκω στα εγχειρίδια'."
    elif "Γενική Γνώση" in search_mode:
        system_instruction += "\n- Χρησιμοποίησε ΜΟΝΟ τις γενικές σου γνώσεις. Μην αναζητάς σε αρχεία."
    else: # Συνδυασμός
        system_instruction += "\n- Συνδύασε πληροφορίες από τα αρχεία και τις γνώσεις σου για την καλύτερη λύση."

    # 4. Generate Answer
    with st.chat_message("assistant"):
        with st.spinner("🧠 Επεξεργασία..."):
            try:
                # Επιλογή μοντέλου (Auto ή Manual)
                forced = None if use_autopilot else model_option
                
                reply, model_used = generate_response([f"{system_instruction}\nΕρώτηση: {prompt}", *media], forced)
                
                st.markdown(reply)
                st.caption(f"🔧 {model_used} | 📂 {search_mode}")
                st.session_state.messages.append({"role": "assistant", "content": reply})
            except Exception as e:
                st.error(f"Σφάλμα: {str(e)}")
