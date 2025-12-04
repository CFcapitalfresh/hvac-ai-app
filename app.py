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
st.set_page_config(page_title="HVAC Master", page_icon="🔧", layout="centered")

# --- CSS (ΓΙΑ ΝΑ ΜΗΝ ΕΧΕΙ ΜΑΥΡΑ ΚΟΥΤΙΑ) ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; background-color: #1e293b; color: white; }
    /* Εξαφάνιση κωδικών σφαλμάτων */
    .element-container:has(code) { display: none; }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ (ΑΥΤΟΜΑΤΗ) ---
auth_status = "⏳ ..."
drive_service = None

try:
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'"): gcp_raw = gcp_raw[1:-1]
        
        info = json.loads(gcp_raw)
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
            
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Σύνδεση OK"
except Exception:
    auth_status = "⚠️ Drive εκτός"

# --- SIDEBAR ---
with st.sidebar:
    st.caption(auth_status)
    st.divider()
    if st.button("🗑️ Νέα Συζήτηση"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER ---
st.title("🔧 HVAC Master")

# --- FUNCTIONS ---
def get_drive_file(file_id):
    try:
        req = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while done is False: status, done = downloader.next_chunk()
        fh.seek(0)
        return fh
    except: return None

# --- UI ---
if "messages" not in st.session_state: st.session_state.messages = []

# Mode
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"
st.caption(f"Ειδικότητα: **{st.session_state.mode}**")

# TABS
tab1, tab2 = st.tabs(["📸 Live", "☁️ Drive"])

with tab1:
    use_cam = st.checkbox("Κάμερα")
    cam_img = st.camera_input("Λήψη") if use_cam else None

sel_file_id = None
sel_file_name = None

with tab2:
    if drive_service:
        if st.button("🔄 Φόρτωση Λίστας"):
            with st.spinner("..."):
                q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
                res = drive_service.files().list(q=q, fields="files(id, name)", pageSize=20).execute()
                st.session_state.files = res.get('files', [])
        
        if "files" in st.session_state and st.session_state.files:
            opts = {f['name']: f['id'] for f in st.session_state.files}
            s = st.selectbox("Επίλεξε αρχείο:", ["--"] + list(opts.keys()))
            if s != "--": 
                sel_file_id = opts[s]
                sel_file_name = s

# --- CHAT ---
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

prompt = st.chat_input("Ερώτηση...")

if prompt:
    # 1. Εμφάνιση ερώτησης χρήστη
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    media = []
    
    # Επεξεργασία Live Φώτο
    if cam_img: media.append(Image.open(cam_img))
    
    # Επεξεργασία Drive File
    if sel_file_id:
        with st.spinner(f"Μελετάω το {sel_file_name}..."):
            stream = get_drive_file(sel_file_id)
            if stream:
                suf = ".pdf" if "pdf" in sel_file_name.lower() else ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
                    tmp.write(stream.getvalue())
                    path = tmp.name
                
                gfile = genai.upload_file(path)
                while gfile.state.name == "PROCESSING": time.sleep(1); gfile = genai.get_file(gfile.name)
                media.append(gfile)

    # 2. Απάντηση AI (STREAMING)
    with st.chat_message("assistant"):
        try:
            # Χρησιμοποιούμε το 1.5 Flash για ταχύτητα
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            # Δημιουργία ροής απάντησης (Streaming)
            response_stream = model.generate_content(
                [f"Είσαι {st.session_state.mode}. Απάντησε καθαρά στα Ελληνικά.\nΕρώτηση: {prompt}", *media],
                stream=True
            )
            
            # ΕΔΩ ΕΙΝΑΙ ΤΟ ΚΛΕΙΔΙ: Το write_stream γράφει καθαρό κείμενο
            full_response = st.write_stream(response_stream)
            
            # Αποθήκευση στο ιστορικό
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            st.error("Κάτι κόλλησε. Πάτα ξανά αποστολή.")
