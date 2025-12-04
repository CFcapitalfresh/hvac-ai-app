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
st.set_page_config(page_title="HVAC Memory", page_icon="🧠", layout="centered")

# CSS
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
    div[data-testid="stChatMessage"]:nth-child(even) { background-color: #1e293b; }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ ---
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

# --- SIDEBAR ---
with st.sidebar:
    st.title("🎛️ Ρυθμίσεις")
    if "✅" in auth_status:
        st.success(auth_status)
    else:
        st.warning(auth_status)
    
    st.divider()
    st.subheader("🔍 Πηγή & Μνήμη")
    search_mode = st.radio(
        "Λειτουργία:",
        ["🧠 Συνδυασμός (Smart)", "📚 Μόνο Manuals", "🌐 Γενική Γνώση"],
        index=0
    )
    
    st.divider()
    if st.button("🗑️ Νέα Συζήτηση (Reset)"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER ---
st.title("🧠 HVAC Smart Memory")

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

# --- UI ---
if "messages" not in st.session_state: st.session_state.messages = []

# Mode
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
        if "files" not in st.session_state:
             if st.button("🔄 Φόρτωση Λίστας"):
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
    # 1. Προσθήκη μηνύματος χρήστη
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    media = []
    # Εικόνα
    if cam_img: media.append(Image.open(cam_img))
    
    # Αρχείο Drive
    file_context = ""
    if "Γενική Γνώση" not in search_mode and sel_file:
        with st.spinner(f"📥 Μελέτη {sel_file['name']}..."):
            try:
                stream = download_drive_file(sel_file['id'])
                suffix = ".pdf" if "pdf" in sel_file['name'].lower() else ".jpg"
                
                # Αποθήκευση & Upload
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(stream.getvalue())
                    path = tmp.name
                
                gfile = genai.upload_file(path)
                while gfile.state.name == "PROCESSING": time.sleep(1); gfile = genai.get_file(gfile.name)
                media.append(gfile)
                file_context = f"(Ο χρήστης έχει φορτώσει το αρχείο: {sel_file['name']})"
            except Exception as e:
                st.error(f"Error file: {e}")

    # 2. Κατασκευή Ιστορικού (Μνήμη)
    # Παίρνουμε τα τελευταία 6 μηνύματα για να μην γεμίζει η μνήμη υπερβολικά
    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages[-6:]])

    # 3. Οδηγίες Συστήματος (System Prompt)
    system_instruction = f"""
    Είσαι ο {st.session_state.mode}.
    
    ΙΣΤΟΡΙΚΟ ΣΥΖΗΤΗΣΗΣ (Θυμήσου τι είπαμε):
    {history_text}
    
    ΟΔΗΓΙΕΣ ΑΠΑΝΤΗΣΗΣ ({search_mode}):
    1. Πρέπει να αναφέρεις ΡΗΤΑ την πηγή σου σε κάθε πληροφορία.
    2. Χρησιμοποίησε τις ετικέτες: [Πηγή: Manual] ή [Πηγή: Γνώση AI].
    3. Αν η πληροφορία υπάρχει στο αρχείο που βλέπεις, δώσε προτεραιότητα σε αυτό.
    4. Αν σε ρωτήσω "από πού το βρήκες", ανατρέξε στο ιστορικό και πες μου.
    
    Απάντα στα Ελληνικά, ευγενικά και τεκμηριωμένα.
    """

    # 4. Κλήση AI
    with st.chat_message("assistant"):
        with st.spinner("🧠 Σκέφτεται (με μνήμη)..."):
            try:
                # Χρησιμοποιούμε το 1.5 Pro για καλύτερη μνήμη/λογική
                model = genai.GenerativeModel("gemini-1.5-pro")
                
                response = model.generate_content([system_instruction, *media])
                
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.error(f"Σφάλμα: {str(e)}")
