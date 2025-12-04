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

# --- 1. ΒΑΣΙΚΕΣ ΡΥΘΜΙΣΕΙΣ ---
st.set_page_config(page_title="HVAC Ultimate", page_icon="🔧", layout="centered")

st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
    div.stButton > button:first-child { border-radius: 8px; font-weight: bold; border: 1px solid #334155; }
</style>""", unsafe_allow_html=True)

# --- 2. ΣΥΝΔΕΣΗ (DRIVE & AI) ---
auth_status = "⏳"
drive_service = None

try:
    # Gemini Auth
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    # Drive Auth (Auto-Repair Logic)
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        
        info = json.loads(gcp_raw)
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
            
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        # Test call
        drive_service.files().list(pageSize=1).execute()
        auth_status = "✅ Συνδέθηκε"
    else:
        auth_status = "⚠️ Χωρίς Drive"

except Exception as e:
    auth_status = "⚠️ Drive Error"

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    st.info(f"Drive: {auth_status}")
    st.divider()
    model_opt = st.selectbox("Μοντέλο", ["gemini-1.5-flash", "gemini-1.5-pro"])
    if st.button("🗑️ Νέα Συζήτηση"):
        st.session_state.messages = []
        st.rerun()

# --- 4. HEADER & MODES ---
st.title("🔧 HVAC Ultimate")

# Κουμπιά Ειδικότητας
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): 
    st.session_state.mode = "Τεχνικός Κλιματισμού"
    st.toast("Mode: AC")
if c2.button("🧊 Ψύξη", use_container_width=True): 
    st.session_state.mode = "Ψυκτικός"
    st.toast("Mode: Ψύξη")
if c3.button("🔥 Αέριο", use_container_width=True): 
    st.session_state.mode = "Τεχνικός Καυστήρων"
    st.toast("Mode: Αέριο")

if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"
st.caption(f"Ειδικότητα: **{st.session_state.mode}**")

# --- 5. ΠΟΛΥΜΕΣΑ (3 TABS: LIVE, UPLOAD, DRIVE) ---
tab1, tab2, tab3 = st.tabs(["📸 Live", "📂 Αρχεία Κινητού", "☁️ Drive"])

# Tab 1: Live Camera
with tab1:
    use_cam = st.checkbox("Ενεργοποίηση Κάμερας")
    cam_img = st.camera_input("Λήψη") if use_cam else None

# Tab 2: Upload από Κινητό (Video/PDF/Images)
with tab2:
    uploaded_file = st.file_uploader("Ανέβασμα", type=['jpg','png','pdf','mp4','mov'])

# Tab 3: Google Drive
sel_drive_file = None
with tab3:
    if drive_service:
        if st.button("🔄 Φόρτωση Λίστας"):
            with st.spinner("..."):
                q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
                res = drive_service.files().list(q=q, fields="files(id, name)", pageSize=20).execute()
                st.session_state.drive_files = res.get('files', [])
        
        if "drive_files" in st.session_state and st.session_state.drive_files:
            opts = {f['name']: f['id'] for f in st.session_state.drive_files}
            s = st.selectbox("Επιλογή:", ["--"] + list(opts.keys()))
            if s != "--": sel_drive_file = {"id": opts[s], "name": s}
    else:
        st.warning("Drive μη συνδεδεμένο")

# --- 6. CHAT DISPLAY ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- 7. ΕΠΕΞΕΡΓΑΣΙΑ (HELPER) ---
def process_media(source_type, file_data, file_name, file_type):
    """Ενιαία συνάρτηση για όλα τα αρχεία"""
    suffix = f".{file_name.split('.')[-1]}" if "." in file_name else ".tmp"
    
    # 1. Save Temp
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_data)
        path = tmp.name
    
    # 2. Upload to Gemini (Video/PDF)
    if "video" in file_type or "pdf" in file_type:
        gfile = genai.upload_file(path, mime_type=file_type)
        # Wait for processing
        while gfile.state.name == "PROCESSING":
            time.sleep(1)
            gfile = genai.get_file(gfile.name)
        return gfile
    
    # 3. Image
    return Image.open(path)

def get_drive_content(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    return fh.getvalue()

# --- 8. INPUT & LOGIC ---
prompt = st.chat_input("Γράψε ερώτηση...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    media_items = []
    
    # A. Από Κάμερα
    if cam_img:
        media_items.append(Image.open(cam_img))
        
    # B. Από Upload Κινητού
    if uploaded_file:
        with st.spinner("Επεξεργασία αρχείου..."):
            m = process_media("upload", uploaded_file.getvalue(), uploaded_file.name, uploaded_file.type)
            media_items.append(m)
            
    # C. Από Drive
    if sel_drive_file:
        with st.spinner("Λήψη από Drive..."):
            data = get_drive_content(sel_drive_file['id'])
            # Guess mime type based on extension
            fname = sel_drive_file['name'].lower()
            ftype = "application/pdf" if "pdf" in fname else "image/jpeg"
            m = process_media("drive", data, sel_drive_file['name'], ftype)
            media_items.append(m)

    # D. Απάντηση (STREAMING - ΚΑΘΑΡΟ ΚΕΙΜΕΝΟ)
    with st.chat_message("assistant"):
        try:
            model = genai.GenerativeModel(model_opt)
            stream = model.generate_content(
                [f"Είσαι {st.session_state.mode}. Απάντησε στα Ελληνικά.\nΕρώτηση: {prompt}", *media_items],
                stream=True
            )
            response = st.write_stream(stream)
            st.session_state.messages.append({"role": "assistant", "content": response})
        except Exception as e:
            st.error("Σφάλμα. Δοκίμασε ξανά.")
            
