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
    .stChatMessage { border-radius: 12px; }
</style>""", unsafe_allow_html=True)

# --- ΕΞΥΠΝΗ ΣΥΝΔΕΣΗ (AUTO-REPAIR KEY) ---
auth_status = "⏳ Προσπάθεια σύνδεσης..."
drive_service = None

try:
    # 1. Gemini Auth
    if "GEMINI_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_KEY"]
        genai.configure(api_key=api_key)
    else:
        st.error("Λείπει το GEMINI_KEY από τα Secrets.")

    # 2. Google Drive Auth με "Χειρουργική Επέμβαση" στο κλειδί
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        # Φόρτωση του JSON
        gcp_info = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
        
        # *** FIX 1: Διόρθωση Private Key ***
        if "private_key" in gcp_info:
            pk = gcp_info["private_key"]
            # Αντικατάσταση των 'σπασμένων' newlines
            pk = pk.replace("\\n", "\n")
            gcp_info["private_key"] = pk
        
        # *** FIX 2: Διόρθωση Token URI (αν λείπει) ***
        if "token_uri" not in gcp_info:
            gcp_info["token_uri"] = "https://oauth2.googleapis.com/token"

        creds = service_account.Credentials.from_service_account_info(
            gcp_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Επιτυχία: Drive & AI Συνδέθηκαν!"
        st.toast("Σύνδεση OK!", icon="🟢")
    else:
        auth_status = "⚠️ Λείπει το GCP_SERVICE_ACCOUNT από τα Secrets."

except Exception as e:
    auth_status = f"❌ Σφάλμα: {str(e)}"
    st.error(f"Δεν μπόρεσα να φτιάξω το κλειδί: {e}")

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Κατάσταση")
    if "✅" in auth_status:
        st.success(auth_status)
    else:
        st.error(auth_status)
        st.info("Συμβουλή: Αν βλέπεις ακόμα Invalid JWT, ξανα-αντέγραψε το JSON στα Secrets προσεκτικά.")
        
    st.divider()
    model_option = st.selectbox("Μοντέλο", ["gemini-2.0-flash", "gemini-1.5-pro"])

# --- HEADER ---
st.title("☁️ HVAC Drive Expert")

# --- DRIVE FUNCTIONS ---
def list_drive_files():
    if not drive_service: return []
    try:
        # Ψάχνουμε PDF και Εικόνες (όχι φακέλους)
        query = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        results = drive_service.files().list(
            q=query, 
            fields="files(id, name, mimeType)",
            pageSize=20
        ).execute()
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

# Mode
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

st.caption(f"Ειδικότητα: **{st.session_state.mode}**")

# --- TABS ---
tab1, tab2 = st.tabs(["📸 Live", "☁️ Google Drive"])

with tab1:
    enable_cam = st.checkbox("Ενεργοποίηση Κάμερας")
    camera_img = None
    if enable_cam:
        camera_img = st.camera_input("Λήψη")

with tab2:
    if "drive_files" not in st.session_state:
        st.session_state.drive_files = []

    if st.button("🔄 Φόρτωση Αρχείων Drive"):
        if drive_service:
            with st.spinner("Σάρωση Drive..."):
                files = list_drive_files()
                if files:
                    st.session_state.drive_files = files
                    st.success(f"Βρέθηκαν {len(files)} αρχεία!")
                else:
                    st.warning("Ο φάκελος φαίνεται άδειος. Σίγουρα έκανες Share στο σωστό email;")
        else:
            st.error("Δεν υπάρχει σύνδεση με το Drive.")
    
    selected_drive_file = None
    if st.session_state.drive_files:
        file_options = {f['name']: f['id'] for f in st.session_state.drive_files}
        selected_name = st.selectbox("Επίλεξε Αρχείο:", ["-- Κανένα --"] + list(file_options.keys()))
        
        if selected_name != "-- Κανένα --":
            selected_drive_file = {"id": file_options[selected_name], "name": selected_name}
            st.info(f"Επιλέχθηκε: {selected_name}")

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
    
    # 2. Από Drive
    if selected_drive_file:
        with st.spinner(f"📥 Μελέτη αρχείου {selected_drive_file['name']}..."):
            try:
                file_stream = download_file_from_drive(selected_drive_file['id'])
                
                # Save temp
                suffix = ".pdf" if "pdf" in selected_drive_file['name'].lower() else ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(file_stream.getvalue())
                    tmp_path = tmp.name
                
                # Upload to Gemini
                gemini_file = genai.upload_file(tmp_path)
                media_items.append(gemini_file)
            except Exception as e:
                st.error(f"Σφάλμα ανάγνωσης αρχείου: {e}")

    # 3. AI Response
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
                st.error(f"Σφάλμα AI: {e}")
