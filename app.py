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

# --- ΕΞΥΠΝΗ ΣΥΝΔΕΣΗ (AUTO-REPAIR KEY v2) ---
auth_status = "⏳ Εκκίνηση..."
drive_service = None

def try_connect_drive(info_dict):
    """Προσπαθεί να συνδεθεί με το Drive χρησιμοποιώντας το λεξικό"""
    try:
        creds = service_account.Credentials.from_service_account_info(
            info_dict, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        service = build('drive', 'v3', credentials=creds)
        # Test call
        service.files().list(pageSize=1).execute()
        return service, "Success"
    except Exception as e:
        return None, str(e)

try:
    # 1. Gemini Auth
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    # 2. Google Drive Auth (Με πολλαπλές δοκιμές)
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        # Φόρτωση του JSON
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"]
        try:
            # Προσπάθεια καθαρισμού αν έχει μπει με λάθος εισαγωγικά
            gcp_raw = gcp_raw.strip()
            if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
            
            gcp_info = json.loads(gcp_raw)
            
            # --- ΔΟΚΙΜΗ 1: Όπως είναι ---
            drive_service, msg = try_connect_drive(gcp_info)
            
            # --- ΔΟΚΙΜΗ 2: Fix Newlines (Το πιο συχνό) ---
            if not drive_service and "private_key" in gcp_info:
                gcp_info_fix1 = gcp_info.copy()
                gcp_info_fix1["private_key"] = gcp_info["private_key"].replace("\\n", "\n")
                drive_service, msg = try_connect_drive(gcp_info_fix1)
                
            # --- ΔΟΚΙΜΗ 3: Strict Formatting ---
            if not drive_service and "private_key" in gcp_info:
                # Αν έχει πραγματικά Enters, τα ενώνουμε και ξαναβάζουμε \n
                pk = gcp_info["private_key"]
                pk_clean = pk.replace("\n", "").replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "").replace(" ", "")
                pk_final = f"-----BEGIN PRIVATE KEY-----\n{pk_clean}\n-----END PRIVATE KEY-----\n"
                gcp_info_fix2 = gcp_info.copy()
                gcp_info_fix2["private_key"] = pk_final
                drive_service, msg = try_connect_drive(gcp_info_fix2)

            if drive_service:
                auth_status = "✅ Drive & AI: ΣΥΝΔΕΘΗΚΑΝ!"
                st.toast("Σύνδεση Επιτυχής!", icon="🚀")
            else:
                auth_status = f"❌ Τελική Αποτυχία: {msg}"
                st.error("Το κλειδί φαίνεται κατεστραμμένο. Δες την πλαϊνή μπάρα.")

        except json.JSONDecodeError:
            auth_status = "❌ Σφάλμα JSON: Ελέγξτε τα Secrets (λείπει κάπου κόμμα ή αγκύλη;)"
    else:
        auth_status = "⚠️ Λείπει το GCP_SERVICE_ACCOUNT"

except Exception as e:
    auth_status = f"💥 Crash: {str(e)}"

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Κατάσταση")
    if "✅" in auth_status:
        st.success(auth_status)
    else:
        st.error(auth_status)
        st.info("Αν αποτύχει ξανά: Διέγραψε το JSON στα Secrets και κάνε Copy-Paste ξανά, πολύ προσεκτικά.")
    
    st.divider()
    model_option = st.selectbox("Μοντέλο", ["gemini-2.0-flash", "gemini-1.5-pro"])

# --- HEADER ---
st.title("☁️ HVAC Drive Expert")

if not drive_service:
    st.warning("⚠️ Η εφαρμογή δεν μπορεί να διαβάσει το Drive. Ελέγξτε την κατάσταση αριστερά.")
    # Επιτρέπουμε να προχωρήσει μόνο το AI κομμάτι αν θέλει
    
# --- FUNCTIONS ---
def list_files():
    if not drive_service: return []
    try:
        q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id, name, mimeType)", pageSize=20).execute()
        return res.get('files', [])
    except Exception as e:
        return []

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

# Mode
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

st.caption(f"Ειδικότητα: **{st.session_state.mode}**")

# TABS
tab1, tab2 = st.tabs(["📸 Live", "☁️ Google Drive"])

with tab1:
    enable_cam = st.checkbox("Κάμερα")
    camera_img = st.camera_input("Λήψη") if enable_cam else None

with tab2:
    if drive_service:
        if st.button("🔄 Φόρτωση Λίστας"):
            with st.spinner("Σάρωση..."):
                files = list_files()
                if files:
                    st.session_state.drive_files = files
                    st.success(f"Βρέθηκαν {len(files)} αρχεία")
                else:
                    st.warning("Ο φάκελος είναι άδειος ή δεν έχει γίνει Share.")
        
        selected_file = None
        if "drive_files" in st.session_state and st.session_state.drive_files:
            opts = {f['name']: f['id'] for f in st.session_state.drive_files}
            sel = st.selectbox("Επίλεξε αρχείο:", ["--"] + list(opts.keys()))
            if sel != "--": selected_file = {"id": opts[sel], "name": sel}
    else:
        st.error("Δεν υπάρχει σύνδεση με Drive.")

# CHAT
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

prompt = st.chat_input("Ερώτηση...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    
    media = []
    if camera_img: media.append(Image.open(camera_img))
    
    if 'selected_file' in locals() and selected_file:
        with st.spinner(f"Μελέτη {selected_file['name']}..."):
            try:
                stream = download_file(selected_file['id'])
                suf = ".pdf" if "pdf" in selected_file['name'].lower() else ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
                    tmp.write(stream.getvalue())
                    path = tmp.name
                media.append(genai.upload_file(path))
            except Exception as e:
                st.error(f"Error reading file: {e}")

    with st.chat_message("assistant"):
        try:
            model = genai.GenerativeModel(model_option)
            res = model.generate_content([f"Είσαι {st.session_state.mode}. Ελληνικά.\n{prompt}", *media])
            st.markdown(res.text)
            st.session_state.messages.append({"role": "assistant", "content": res.text})
        except Exception as e:
            st.error(f"Error: {e}")
