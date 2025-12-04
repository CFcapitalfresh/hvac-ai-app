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

# --- SETUP ---
st.set_page_config(page_title="HVAC Drive Expert", page_icon="☁️", layout="centered")

# CSS
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .reportview-container .main .block-container {padding-top: 2rem;}
</style>""", unsafe_allow_html=True)

# --- AUTHENTICATION ---
try:
    # 1. Gemini Auth
    api_key = st.secrets["GEMINI_KEY"]
    genai.configure(api_key=api_key)
    
    # 2. Google Drive Auth
    drive_info = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
    creds = service_account.Credentials.from_service_account_info(
        drive_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    drive_service = build('drive', 'v3', credentials=creds)
    
    # ΠΑΙΡΝΟΥΜΕ TO EMAIL ΤΟΥ ΡΟΜΠΟΤ ΓΙΑ ΝΑ ΤΟ ΔΕΙΞΟΥΜΕ
    robot_email = drive_info.get("client_email", "Άγνωστο")
    auth_status = "✅ Συνδέθηκε"
    
except Exception as e:
    auth_status = f"⚠️ Σφάλμα: {str(e)}"
    robot_email = "Κανένα"

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Ρυθμίσεις")
    st.info(f"Status: {auth_status}")
    
    st.markdown("### 🤖 Το Email του Ρομπότ:")
    st.code(robot_email, language="text")
    st.caption("👆 Αντίγραψε αυτό το email και κάνε Κοινοποίηση (Share) τον φάκελο στο Google Drive σε αυτόν τον χρήστη.")
    
    st.divider()
    model_option = st.selectbox("Μοντέλο", ["gemini-2.0-flash", "gemini-1.5-pro"])

# --- HEADER ---
st.title("☁️ HVAC Drive Expert")

# --- DRIVE FUNCTIONS ---
def list_drive_files():
    try:
        # Αναζήτηση με supportsAllDrives για να αποφύγουμε 404/403 σε μερικά accounts
        query = "mimeType = 'application/pdf' or mimeType contains 'image/' and trashed = false"
        results = drive_service.files().list(
            q=query, 
            fields="files(id, name, mimeType)",
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        return results.get('files', [])
    except Exception as e:
        st.error(f"❌ Drive Error: {e}")
        return []

def download_file_from_drive(file_id):
    request = drive_service.files().get_media(fileId=file_id)
    file_stream = io.BytesIO()
    downloader = MediaIoBaseDownload(file_stream, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    file_stream.seek(0)
    return file_stream

# --- UI LOGIC ---
if "messages" not in st.session_state: st.session_state.messages = []

# Mode Selection
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

st.caption(f"Λειτουργία: **{st.session_state.mode}**")

# --- TABS ---
tab1, tab2 = st.tabs(["📸 Live / Upload", "☁️ Google Drive"])

with tab1:
    enable_cam = st.checkbox("Κάμερα")
    camera_img = st.camera_input("Λήψη") if enable_cam else None
    uploaded_file_local = st.file_uploader("Ανέβασμα από κινητό", type=['jpg','png','pdf','mp4'])

with tab2:
    if "drive_files" not in st.session_state:
        if st.button("🔄 Φόρτωση Αρχείων Drive"):
            files = list_drive_files()
            if not files:
                st.warning("Δεν βρέθηκαν αρχεία. Τσέκαρες την Κοινοποίηση;")
            st.session_state.drive_files = files
    
    selected_drive_file = None
    if "drive_files" in st.session_state and st.session_state.drive_files:
        file_options = {f['name']: f['id'] for f in st.session_state.drive_files}
        selected_name = st.selectbox("Επίλεξε Manual:", ["-- Κανένα --"] + list(file_options.keys()))
        
        if selected_name != "-- Κανένα --":
            selected_drive_file = {"id": file_options[selected_name], "name": selected_name}
            st.success(f"Επιλέχθηκε: {selected_name}")

# --- CHAT ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

prompt = st.chat_input("Γράψε τη βλάβη...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    media_items = []
    
    # 1. Από Κάμερα
    if enable_cam and camera_img:
        media_items.append(Image.open(camera_img))
        
    # 2. Από Local Upload
    if uploaded_file_local:
        # (Απλοποιημένη λογική για συντομία - θα χρειαστεί tempfile για βίντεο όπως πριν)
        if "image" in uploaded_file_local.type:
            media_items.append(Image.open(uploaded_file_local))
    
    # 3. Από Drive
    if selected_drive_file:
        with st.spinner(f"📥 Κατεβάζω {selected_drive_file['name']}..."):
            file_stream = download_file_from_drive(selected_drive_file['id'])
            
            suffix = ".pdf" if "pdf" in selected_drive_file['name'].lower() else ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_stream.getvalue())
                tmp_path = tmp.name
            
            gemini_file = genai.upload_file(tmp_path)
            media_items.append(gemini_file)

    # 4. AI Response
    with st.chat_message("assistant"):
        with st.spinner("🧠 Ανάλυση..."):
            try:
                model = genai.GenerativeModel(model_option)
                msg = [f"Είσαι {st.session_state.mode}. Ελληνικά.\nΕρώτηση: {prompt}"]
                msg.extend(media_items)
                
                resp = model.generate_content(msg)
                st.markdown(resp.text)
                st.session_state.messages.append({"role": "assistant", "content": resp.text})
            except Exception as e:
                st.error(f"Σφάλμα: {e}")
