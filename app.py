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
st.set_page_config(page_title="HVAC Auto-Pilot", page_icon="🚀", layout="centered")

# CSS
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
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
        auth_status = "✅ Σύστημα Έτοιμο"
    else:
        auth_status = "⚠️ Λείπει το Drive Key"
except Exception as e:
    auth_status = f"⚠️ Status: {str(e)}"

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Auto-Pilot")
    if "✅" in auth_status:
        st.success(auth_status)
    else:
        st.warning(auth_status)
    
    st.divider()
    st.info("🤖 Το σύστημα επιλέγει αυτόματα το καλύτερο μοντέλο.")
    if st.button("🗑️ Καθαρισμός"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER ---
st.title("🚀 HVAC Auto-Pilot")

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

# --- SMART MODEL SELECTOR ---
def generate_smart_response(prompt_content):
    # Λίστα προτεραιότητας μοντέλων
    models_to_try = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]
    
    for model_name in models_to_try:
        try:
            # Δοκιμή μοντέλου
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt_content)
            return response.text, model_name # Επιστροφή απάντησης ΚΑΙ ονόματος μοντέλου
        except Exception as e:
            # Αν αποτύχει, προχωράμε στο επόμενο
            continue
    
    # Αν αποτύχουν όλα
    raise Exception("Όλα τα μοντέλα είναι απασχολημένα. Δοκίμασε σε λίγο.")

# --- UI ---
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
        if st.button("🔄 Φόρτωση Drive"):
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
    
    # 2. Drive File
    if sel_file:
        with st.spinner(f"📥 Κατεβάζω {sel_file['name']}..."):
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

    # 3. AI Reply (SMART MODE)
    with st.chat_message("assistant"):
        with st.spinner("🧠 Ο Αυτόματος Πιλότος σκέφτεται..."):
            try:
                # Καλούμε την έξυπνη συνάρτηση
                msg_content = [f"Είσαι {st.session_state.mode}. Απάντησε στα Ελληνικά.\nΕρώτηση: {prompt}", *media]
                reply_text, used_model = generate_smart_response(msg_content)
                
                # Εμφάνιση απάντησης και ποιο μοντέλο χρησιμοποιήθηκε (με μικρά γράμματα)
                st.markdown(reply_text)
                st.caption(f"⚡ Απαντήθηκε από: {used_model}")
                
                st.session_state.messages.append({"role": "assistant", "content": reply_text})
            except Exception as e:
                st.error(f"⚠️ Σφάλμα: {str(e)}")
