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
st.set_page_config(page_title="HVAC Next Gen", page_icon="⚡", layout="centered")

st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; background-color: #1e293b; color: #e2e8f0; }
    div.stToast { background-color: #22c55e; color: white; }
</style>""", unsafe_allow_html=True)

# --- 2. ΑΥΤΟΜΑΤΗ ΣΥΝΔΕΣΗ ---
auth_status = "⏳ Σύνδεση..."
drive_service = None

try:
    # Gemini Connection
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    # Drive Connection
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
        drive_service.files().list(pageSize=1).execute() # Test
        auth_status = "✅ Next Gen Ready"
    else:
        auth_status = "⚠️ Λείπει το Drive Key"

except Exception as e:
    auth_status = f"⚠️ Σφάλμα: {str(e)}"

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    if "✅" in auth_status:
        st.success(auth_status)
    else:
        st.error(auth_status)
    
    st.divider()
    # ΛΙΣΤΑ ΜΟΝΤΕΛΩΝ ΠΟΥ ΔΟΥΛΕΥΟΥΝ ΜΕ ΤΟ ΚΛΕΙΔΙ ΣΟΥ
    model_option = st.selectbox("Μοντέλο AI", ["gemini-2.0-flash", "gemini-2.0-flash-exp", "gemini-2.5-flash"])
    
    if st.button("🗑️ Νέα Συζήτηση"):
        st.session_state.messages = []
        st.rerun()

# --- 4. ΚΥΡΙΩΣ ΟΘΟΝΗ ---
st.title("⚡ HVAC Next Gen")

# Α. Ειδικότητα
st.write("🔧 **Ειδικότητα:**")
c1, c2, c3, c4 = st.columns(4)
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Αερίου"
if c4.button("♨️ Αντλίες", use_container_width=True): st.session_state.mode = "Τεχνικός Αντλιών"

st.info(f"Ρόλος: **{st.session_state.mode}**")

# Β. Πηγή
search_scope = st.radio(
    "🔎 **Λειτουργία:**",
    ["🤖 Αυτόματο (Drive + AI)", "📂 Μόνο Drive", "🧠 Μόνο AI"],
    horizontal=True
)

# Γ. Media (Video/Photo)
with st.expander("📷 Πολυμέσα (Φώτο/Βίντεο)", expanded=False):
    tab1, tab2 = st.tabs(["📸 Live", "📁 Upload"])
    media_items = []
    
    with tab1:
        if st.checkbox("Ενεργοποίηση Κάμερας"):
            cam_img = st.camera_input("Λήψη")
            if cam_img: media_items.append(Image.open(cam_img))
            
    with tab2:
        uploaded_file = st.file_uploader("Αρχείο", type=['jpg','png','mp4','mov','avi'])
        if uploaded_file:
            suffix = f".{uploaded_file.name.split('.')[-1]}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name
            
            if "video" in uploaded_file.type:
                with st.spinner("Μεταφόρτωση βίντεο..."):
                    vid_file = genai.upload_file(tmp_path)
                    while vid_file.state.name == "PROCESSING":
                        time.sleep(1)
                        vid_file = genai.get_file(vid_file.name)
                    media_items.append(vid_file)
            else:
                media_items.append(Image.open(tmp_path))

# --- 5. FUNCTIONS ---
def search_drive(query):
    if not drive_service: return None
    try:
        keywords = query.split()
        q_parts = [f"name contains '{word}'" for word in keywords if len(word) > 2]
        if not q_parts: return None
        
        q_filter = "(" + " or ".join(q_parts) + ") and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        res = drive_service.files().list(q=q_filter, fields="files(id, name, mimeType)", pageSize=3).execute()
        files = res.get('files', [])
        return files[0] if files else None
    except: return None

def download_drive_file(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

# --- 6. CHAT & LOGIC ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

prompt = st.chat_input("Γράψε τη βλάβη...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    # Λογική Αυτόματης Επιλογής Αρχείου
    found_file = None
    context_text = ""
    
    if "Μόνο AI" not in search_scope and drive_service:
        with st.spinner("🔎 Ψάχνω στα manuals..."):
            found_file = search_drive(prompt)
            if found_file:
                st.toast(f"Βρέθηκε: {found_file['name']}", icon="📂")
                try:
                    stream = download_drive_file(found_file['id'])
                    suf = ".pdf" if "pdf" in found_file['name'].lower() else ".jpg"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
                        tmp.write(stream.getvalue())
                        path = tmp.name
                    
                    gfile = genai.upload_file(path)
                    while gfile.state.name == "PROCESSING": time.sleep(1); gfile = genai.get_file(gfile.name)
                    media_items.append(gfile)
                    context_text += f"\n[Χρησιμοποίησε το αρχείο '{found_file['name']}' για την απάντηση]"
                except: st.error("Σφάλμα ανάγνωσης αρχείου.")
            elif "Μόνο Drive" in search_scope:
                st.error("Δεν βρέθηκε σχετικό manual.")
                st.stop()

    with st.chat_message("assistant"):
        with st.spinner("🧠 Ανάλυση..."):
            try:
                # ΧΡΗΣΗ ΤΟΥ ΕΠΙΛΕΓΜΕΝΟΥ ΜΟΝΤΕΛΟΥ (2.0/2.5)
                model = genai.GenerativeModel(model_option)
                
                sys_prompt = f"""
                Είσαι {st.session_state.mode}. Μιλάς Ελληνικά.
                ΚΑΝΟΝΕΣ:
                1. Αν έχεις αρχείο, γράψε στο τέλος: '📂 Πηγή: [Όνομα Αρχείου]'.
                2. Αν απαντάς από γνώσεις, γράψε: '🧠 Πηγή: Γνώση AI'.
                {context_text}
                Ερώτηση: {prompt}
                """
                
                # Streaming Response
                stream = model.generate_content([sys_prompt, *media_items], stream=True)
                response = st.write_stream(stream)
                st.session_state.messages.append({"role": "assistant", "content": response})
                
            except Exception as e:
                st.error(f"Σφάλμα AI: {e}")
