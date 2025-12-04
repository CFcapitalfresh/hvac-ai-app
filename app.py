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

st.set_page_config(page_title="HVAC Expert", page_icon="🔧")

# CSS
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
</style>""", unsafe_allow_html=True)

# --- ΔΙΑΓΝΩΣΤΙΚΟΣ ΕΛΕΓΧΟΣ ΚΛΕΙΔΙΟΥ ---
st.sidebar.title("🛠️ Διάγνωση Σύνδεσης")
drive_service = None
auth_status = "⏳ Εκκίνηση..."

try:
    # 1. Gemini Check
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        st.sidebar.success("✅ AI (Gemini): OK")
    else:
        st.sidebar.error("❌ AI: Λείπει το GEMINI_KEY")

    # 2. Drive Check
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        try:
            info = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
            
            # ΕΛΕΓΧΟΣ 1: Υπάρχει το private_key;
            if "private_key" not in info:
                st.error("❌ ΣΦΑΛΜΑ: Λείπει το 'private_key' από το JSON.")
                st.stop()
            
            pk = info["private_key"]
            st.sidebar.info(f"🔑 Μήκος Κλειδιού: {len(pk)} χαρακτήρες")

            # ΕΛΕΓΧΟΣ 2: Έχει σωστή αρχή/τέλος;
            if "-----BEGIN PRIVATE KEY-----" not in pk:
                st.error("❌ ΣΦΑΛΜΑ: Το κλειδί δεν έχει σωστή αρχή (BEGIN PRIVATE KEY). Έλεγξε την αντιγραφή.")
                st.stop()

            # FIX: Διόρθωση των \n
            fixed_pk = pk.replace("\\n", "\n")
            info["private_key"] = fixed_pk

            # Προσπάθεια Σύνδεσης
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
            drive_service = build('drive', 'v3', credentials=creds)
            
            # Τελικό Τεστ: Ζητάμε λίστα αρχείων
            drive_service.files().list(pageSize=1).execute()
            
            auth_status = "✅ Drive: ΣΥΝΔΕΘΗΚΕ!"
            st.sidebar.success(auth_status)
            
        except json.JSONDecodeError:
            st.error("❌ ΣΦΑΛΜΑ: Τα Secrets δεν είναι σωστό JSON. Ξανακάνε επικόλληση.")
        except Exception as e:
            st.error(f"❌ ΣΦΑΛΜΑ DRIVE:\n{str(e)}")
            st.sidebar.error("❌ Drive: Απέτυχε")
    else:
        st.sidebar.warning("⚠️ Λείπει το GCP_SERVICE_ACCOUNT")

except Exception as e:
    st.error(f"Γενικό Σφάλμα: {e}")

# --- ΚΥΡΙΩΣ ΕΦΑΡΜΟΓΗ ---
st.title("🔧 HVAC Drive Expert")

if not drive_service:
    st.warning("⚠️ Η σύνδεση με το Drive απέτυχε. Δες τα σφάλματα αριστερά ή πάνω.")
    st.stop()

# Αν φτάσαμε εδώ, όλα δουλεύουν!
# --- DRIVE FUNCTIONS ---
def list_files():
    q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
    res = drive_service.files().list(q=q, fields="files(id, name, mimeType)", pageSize=20).execute()
    return res.get('files', [])

def download_file(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

# --- UI ---
if "messages" not in st.session_state: st.session_state.messages = []

# TABS
tab1, tab2 = st.tabs(["📂 Βιβλιοθήκη Drive", "📸 Live Κάμερα"])

with tab1:
    if st.button("🔄 Ανανέωση Λίστας"):
        with st.spinner("Φόρτωση..."):
            st.session_state.files = list_files()
    
    selected_file = None
    if "files" in st.session_state and st.session_state.files:
        opts = {f['name']: f['id'] for f in st.session_state.files}
        sel = st.selectbox("Επίλεξε αρχείο:", ["--"] + list(opts.keys()))
        if sel != "--": selected_file = {"id": opts[sel], "name": sel}

with tab2:
    cam = st.checkbox("Κάμερα")
    img = st.camera_input("Λήψη") if cam else None

# CHAT
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

prompt = st.chat_input("Ερώτηση...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    
    media = []
    if img: media.append(Image.open(img))
    
    if selected_file:
        with st.spinner(f"Μελετάω το {selected_file['name']}..."):
            stream = download_file(selected_file['id'])
            suf = ".pdf" if "pdf" in selected_file['name'].lower() else ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
                tmp.write(stream.getvalue())
                path = tmp.name
            media.append(genai.upload_file(path))

    with st.chat_message("assistant"):
        try:
            model = genai.GenerativeModel("gemini-2.0-flash")
            res = model.generate_content([f"Είσαι τεχνικός HVAC. Ελληνικά.\n{prompt}", *media])
            st.markdown(res.text)
            st.session_state.messages.append({"role": "assistant", "content": res.text})
        except Exception as e:
            st.error(f"Error: {e}")
