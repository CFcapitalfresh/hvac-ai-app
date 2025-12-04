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
st.set_page_config(page_title="HVAC Cloud", page_icon="☁️", layout="centered")

# CSS
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
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
    
    auth_status = "✅ Συνδέθηκε στο Drive!"
except Exception as e:
    auth_status = f"⚠️ Σφάλμα Σύνδεσης: {e}"

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Κατάσταση")
    st.info(auth_status)
    st.divider()
    if st.button("🗑️ Καθαρισμός Chat"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER ---
st.title("☁️ HVAC Cloud Expert")

# --- DRIVE FUNCTIONS ---
def list_drive_files():
    try:
        query = "(mimeType = 'application/pdf' or mimeType contains 'image/') and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name, mimeType)", pageSize=50).execute()
        return results.get('files', [])
    except Exception as e:
        st.error(f"Drive Error: {e}")
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

c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

st.caption(f"Ειδικότητα: **{st.session_state.mode}**")

# --- TABS ---
tab1, tab2 = st.tabs(["📸 Live", "☁️ Google Drive"])

with tab1:
    enable_cam = st.checkbox("Κάμερα")
    camera_img = st.camera_input("Λήψη") if enable_cam else None

with tab2:
    if st.button("🔄 Ανανέωση"):
        st.session_state.drive_files = list_drive_files()
            
    if "drive_files" not in st.session_state:
        st.session_state.drive_files = list_drive_files()
    
    selected_drive_file = None
    if st.session_state.drive_files:
        file_map = {f['name']: f['id'] for f in st.session_state.drive_files}
        selected_name = st.selectbox("Επίλεξε Manual/Αρχείο:", ["-- Χωρίς Αρχείο --"] + list(file_map.keys()))
        
        if selected_name != "-- Χωρίς Αρχείο --":
            selected_drive_file = {"id": file_map[selected_name], "name": selected_name}
            st.success(f"📎 Έτοιμο για ανάλυση: {selected_name}")
    else:
        st.warning("Δεν βρέθηκαν PDF/Εικόνες.")

# --- CHAT ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

prompt = st.chat_input("Γράψε τη βλάβη...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    media_items = []
    
    if enable_cam and camera_img:
        media_items.append(Image.open(camera_img))
    
    if selected_drive_file:
        with st.spinner(f"📥 Διαβάζω το {selected_drive_file['name']}..."):
            try:
                file_stream = download_file_from_drive(selected_drive_file['id'])
                suffix = ".pdf" if "pdf" in selected_drive_file['name'].lower() else ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(file_stream.getvalue())
                    tmp_path = tmp.name
                
                gemini_file = genai.upload_file(tmp_path)
                while gemini_file.state.name == "PROCESSING": time.sleep(1); gemini_file = genai.get_file(gemini_file.name)
                media_items.append(gemini_file)
            except Exception as e:
                st.error(f"Σφάλμα αρχείου: {e}")

    with st.chat_message("assistant"):
        with st.spinner("🧠 Ανάλυση..."):
            try:
                model = genai.GenerativeModel("gemini-2.0-flash")
                msg = [f"Είσαι {st.session_state.mode}. Ελληνικά.\nΕρώτηση: {prompt}"]
                msg.extend(media_items)
                
                stream = model.generate_content(msg, stream=True)
                response = st.write_stream(stream)
                st.session_state.messages.append({"role": "assistant", "content": response})
            except Exception as e:
                st.error(f"Σφάλμα: {e}")
