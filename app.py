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

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Controller 2.0", page_icon="🎛️", layout="centered")

# --- CSS (Στυλ) ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
    div.stRadio > label { font-weight: bold; font-size: 16px; color: #60a5fa; }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ (DRIVE & AI - FIXED) ---
auth_status = "⏳ ..."
drive_service = None

try:
    # 1. Gemini Auth
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    # 2. Drive Auth (Με το fix για τα enter)
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        # Καθαρισμός αν έχει μπει με λάθος εισαγωγικά
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        
        info = json.loads(gcp_raw)
        if "private_key" in info: 
            info["private_key"] = info["private_key"].replace("\\n", "\n")
            
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Drive Συνδεδεμένο"
    else:
        auth_status = "⚠️ Χωρίς Drive"
except Exception as e:
    auth_status = f"⚠️ Drive Error: {str(e)}"

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    st.info(auth_status)
    
    st.divider()
    # ΜΟΝΟ ΤΑ ΝΕΑ ΜΟΝΤΕΛΑ 2.0
    model_option = st.selectbox(
        "Μοντέλο AI", 
        ["gemini-2.0-flash", "gemini-2.0-pro-exp-02-05"]
    )
    
    st.divider()
    if st.button("🗑️ Νέα Συζήτηση", type="primary"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER & MODES ---
st.title("🎛️ HVAC Controller 2.0")

# Επιλογή Ειδικότητας
c1, c2, c3 = st.columns(3)
if "tech_mode" not in st.session_state: st.session_state.tech_mode = "Τεχνικός HVAC"

if c1.button("❄️ AC"): st.session_state.tech_mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη"): st.session_state.tech_mode = "Ψυκτικός"
if c3.button("🔥 Αέριο"): st.session_state.tech_mode = "Τεχνικός Καυστήρων"

st.caption(f"Ειδικότητα: **{st.session_state.tech_mode}**")

# --- ΠΗΓΗ ΑΝΑΖΗΤΗΣΗΣ ---
search_source = st.radio(
    "🔎 Πού να ψάξω;",
    ["🧠 Υβριδικό (Smart)", "📂 Μόνο Αρχεία", "🌐 Μόνο Γενική Γνώση"],
    horizontal=True,
    help="Υβριδικό: Ψάχνει Drive και συμπληρώνει. Μόνο Αρχεία: Αυστηρά από manuals."
)

# --- FUNCTIONS ---
def list_drive_files():
    if not drive_service: return []
    try:
        q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id, name)", pageSize=50).execute()
        return res.get('files', [])
    except: return []

def download_file_content(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    return fh.getvalue()

def find_relevant_file(user_query, files):
    """Ψάχνει αν υπάρχει manual με βάση το όνομα"""
    user_query = user_query.lower()
    for f in files:
        fname = f['name'].lower()
        # Αν βρει λέξη κλειδί (πάνω από 3 γράμματα) στο όνομα του αρχείου
        if any(word in fname for word in user_query.split() if len(word) > 3):
            return f
    return None

# --- CHAT UI ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- INPUT ---
# Media Upload Tab
with st.expander("📸 Προσθήκη Φώτο/Βίντεο (Προαιρετικό)"):
    tab1, tab2 = st.tabs(["📸 Live", "📂 Upload"])
    with tab1:
        enable_cam = st.checkbox("Ενεργοποίηση Κάμερας")
        cam_img = st.camera_input("Λήψη") if enable_cam else None
    with tab2:
        upl_file = st.file_uploader("Ανέβασμα", type=['png', 'jpg', 'jpeg', 'pdf'])

prompt = st.chat_input("Γράψε βλάβη, κωδικό ή μάρκα...")

if prompt:
    # 1. User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    # 2. Logic Controller
    with st.chat_message("assistant"):
        media_content = []
        found_file_name = None
        
        # A. Media processing
        if cam_img:
            media_content.append(Image.open(cam_img))
        if upl_file:
             media_content.append(Image.open(upl_file) if "image" in upl_file.type else upl_file)

        # B. Drive Logic
        if ("Αρχεία" in search_source or "Υβριδικό" in search_source) and drive_service:
            with st.spinner("🕵️ Ψάχνω στα manuals..."):
                all_files = list_drive_files()
                target_file = find_relevant_file(prompt, all_files)
                
                if target_file:
                    st.toast(f"📖 Βρέθηκε: {target_file['name']}")
                    found_file_name = target_file['name']
                    
                    try:
                        file_data = download_file_content(target_file['id'])
                        suffix = ".pdf" if "pdf" in target_file['name'].lower() else ".jpg"
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(file_data)
                            tmp_path = tmp.name
                        
                        gfile = genai.upload_file(tmp_path)
                        while gfile.state.name == "PROCESSING": 
                            time.sleep(0.5)
                            gfile = genai.get_file(gfile.name)
                        media_content.append(gfile)
                    except Exception as e:
                        st.error(f"Error reading file: {e}")
                else:
                    if "Μόνο Αρχεία" in search_source:
                        st.warning("Δεν βρέθηκε σχετικό manual στο Drive.")

        # 3. AI Generation
        if media_content or "Γενική" in search_source or ("Υβριδικό" in search_source):
            try:
                model = genai.GenerativeModel(model_option)
                
                source_instruction = ""
                if found_file_name:
                    source_instruction = f"Βασίσου στο αρχείο '{found_file_name}' που σου δίνω."
                elif "Μόνο Αρχεία" in search_source and not found_file_name:
                    source_instruction = "Απάντησε ΜΟΝΟ αν βρεις την πληροφορία στα αρχεία. Αλλιώς πες 'Δεν γνωρίζω'."
                
                full_prompt = f"""
                Είσαι {st.session_state.tech_mode}. Μίλα Ελληνικά.
                {source_instruction}
                Ερώτηση: {prompt}
                """
                
                with st.spinner("🧠 Ανάλυση 2.0..."):
                    # Καθαρή κλήση generate_content
                    response = model.generate_content([full_prompt, *media_content])
                    st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                 
            except Exception as e:
                st.error(f"Σφάλμα AI: {e}")
