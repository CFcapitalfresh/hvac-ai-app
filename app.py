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
st.set_page_config(page_title="HVAC General v10", page_icon="🛠️", layout="centered")

# CSS για εμφάνιση
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; background-color: #1e293b; color: #e2e8f0; }
    .big-font { font-size:18px !important; font-weight: bold; }
</style>""", unsafe_allow_html=True)

# --- 2. ΑΥΤΟΜΑΤΗ ΣΥΝΔΕΣΗ (AUTO-REPAIR KEY) ---
auth_status = "⏳ Σύνδεση..."
drive_service = None

try:
    # Gemini Connection
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    # Drive Connection (με διόρθωση κλειδιού)
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        # Καθαρισμός από τυχόν εισαγωγικά στην αρχή/τέλος
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        
        info = json.loads(gcp_raw)
        
        # Διόρθωση των \n στο private_key
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
            
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Test Call για επιβεβαίωση
        drive_service.files().list(pageSize=1).execute()
        auth_status = "✅ Σύστημα Έτοιμο"
    else:
        auth_status = "⚠️ Λείπει το Drive Key"

except Exception as e:
    auth_status = f"⚠️ Σφάλμα Σύνδεσης: {str(e)}"

# --- 3. SIDEBAR ΡΥΘΜΙΣΕΙΣ ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    if "✅" in auth_status:
        st.success(auth_status)
    else:
        st.error(auth_status)
    
    st.divider()
    model_option = st.selectbox("Μοντέλο AI", ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"])
    
    if st.button("🗑️ Νέα Συζήτηση"):
        st.session_state.messages = []
        st.rerun()

# --- 4. ΚΥΡΙΩΣ ΟΘΟΝΗ & ΕΠΙΛΟΓΕΣ ---
st.title("🛠️ HVAC General")

# Α. ΕΠΙΛΟΓΗ ΕΙΔΙΚΟΤΗΤΑΣ (Mode)
st.write("🔧 **Επέλεξε Ειδικότητα:**")
c1, c2, c3, c4 = st.columns(4)
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού (Split/VRV)"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός (Βιομηχανική)"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Λεβήτων Αερίου"
if c4.button("♨️ Αντλίες", use_container_width=True): st.session_state.mode = "Τεχνικός Αντλιών Θερμότητας"

st.info(f"Ρόλος: **{st.session_state.mode}**")

# Β. ΠΗΓΗ ΑΝΑΖΗΤΗΣΗΣ (Scope)
search_scope = st.radio(
    "🔎 **Πού να ψάξω;**",
    ["🤖 Αυτόματο (Drive + Γνώση)", "📂 Μόνο Drive (Manuals)", "🧠 Μόνο Γνώση AI"],
    horizontal=True
)

# Γ. MEDIA CENTER (Video/Photo/Live)
with st.expander("📷 Προσθήκη Εικόνας / Βίντεο (Προαιρετικό)", expanded=False):
    tab1, tab2 = st.tabs(["📸 Live Κάμερα", "📁 Ανέβασμα Αρχείου"])
    
    media_items = []
    
    with tab1:
        use_cam = st.checkbox("Ενεργοποίηση Κάμερας")
        if use_cam:
            cam_img = st.camera_input("Λήψη")
            if cam_img: media_items.append(Image.open(cam_img))
            
    with tab2:
        uploaded_file = st.file_uploader("Επιλογή Βίντεο/Εικόνας", type=['jpg','png','mp4','mov','avi'])
        if uploaded_file:
            # Επεξεργασία Upload (Temp File)
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

# --- 5. FUNCTIONS ΓΙΑ DRIVE ---
def search_drive(query):
    """Ψάχνει αρχεία που ταιριάζουν στο όνομα, ΠΑΝΤΟΥ (Recursive από τη φύση του API)"""
    if not drive_service: return None
    try:
        # Ψάχνουμε λέξεις κλειδιά από την ερώτηση
        keywords = query.split()
        # Φτιάχνουμε φίλτρο: Το όνομα να περιέχει κάποια από τις λέξεις ΚΑΙ να μην είναι φάκελος
        # Ψάχνει σε όλο το Drive που έχει πρόσβαση το Service Account
        q_parts = [f"name contains '{word}'" for word in keywords if len(word) > 2]
        
        if not q_parts: return None # Αν δεν υπάρχουν λέξεις κλειδιά
        
        q_filter = "(" + " or ".join(q_parts) + ") and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        
        results = drive_service.files().list(
            q=q_filter, 
            fields="files(id, name, mimeType)",
            pageSize=3  # Φέρε τα 3 πιο σχετικά
        ).execute()
        
        files = results.get('files', [])
        return files[0] if files else None # Επιστρέφει το πρώτο (καλύτερο)
        
    except Exception as e:
        print(f"Error searching Drive: {e}")
        return None

def download_drive_file(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

# --- 6. CHAT LOGIC ---
if "messages" not in st.session_state: st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- 7. INPUT & PROCESSING ---
prompt = st.chat_input("Γράψε τη βλάβη ή τον κωδικό...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    # Λογική Επιλογής Πηγής
    found_file = None
    final_prompt_context = ""
    
    # Α. ΑΝΑΖΗΤΗΣΗ ΣΤΟ DRIVE (Αν δεν είναι αποκλεισμένο)
    if "Μόνο Γνώση" not in search_scope and drive_service:
        with st.spinner("🔎 Αναζήτηση στα manuals σου..."):
            found_file = search_drive(prompt)
            
            if found_file:
                st.toast(f"Βρέθηκε: {found_file['name']}", icon="📂")
                
                # Κατέβασμα και προετοιμασία
                try:
                    stream = download_drive_file(found_file['id'])
                    suf = ".pdf" if "pdf" in found_file['name'].lower() else ".jpg"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
                        tmp.write(stream.getvalue())
                        path = tmp.name
                    
                    # Upload στο Gemini για ανάλυση
                    gfile = genai.upload_file(path)
                    # Wait loop
                    while gfile.state.name == "PROCESSING":
                        time.sleep(1)
                        gfile = genai.get_file(gfile.name)
                    
                    media_items.append(gfile)
                    final_prompt_context += f"\n[ΟΔΗΓΙΑ: Χρησιμοποίησε το αρχείο '{found_file['name']}' για την απάντηση.]"
                
                except Exception as e:
                    st.error(f"Σφάλμα ανάγνωσης αρχείου: {e}")
            else:
                if "Μόνο Drive" in search_scope:
                    st.error("Δεν βρέθηκε σχετικό manual στο Drive.")
                    st.stop() # Σταματάμε εδώ αν θέλει ΜΟΝΟ drive

    # Β. ΕΛΕΓΧΟΣ ΓΙΑ ΜΟΝΟ DRIVE
    if "Μόνο Drive" in search_scope and not found_file:
        st.warning("Δεν βρέθηκε αρχείο και έχεις επιλέξει 'Μόνο Drive'.")
        st.stop()

    # Γ. ΚΛΗΣΗ ΣΤΟ AI
    with st.chat_message("assistant"):
        with st.spinner("🧠 Ανάλυση & Σύνταξη απάντησης..."):
            try:
                model = genai.GenerativeModel(model_option)
                
                system_instruction = f"""
                Είσαι {st.session_state.mode}. Μιλάς Ελληνικά.
                
                ΚΑΝΟΝΕΣ:
                1. Αν έχεις αρχείο/manual, βασίσου σε αυτό.
                2. Αν η απάντηση είναι από το αρχείο, γράψε στο τέλος: '📂 Πηγή: [Όνομα Αρχείου]'.
                3. Αν δεν υπάρχει αρχείο ή δεν έχει την απάντηση, απάντα από την εμπειρία σου και γράψε: '🧠 Πηγή: Γνώση AI'.
                4. Αν έχεις εικόνα/βίντεο από τον χρήστη, ανάλυσέ τα.
                """
                
                full_msg = [f"{system_instruction}\n{final_prompt_context}\nΕρώτηση: {prompt}", *media_items]
                
                # Streaming Response
                stream = model.generate_content(full_msg, stream=True)
                response_text = st.write_stream(stream)
                
                st.session_state.messages.append({"role": "assistant", "content": response_text})
                
            except Exception as e:
                st.error(f"Σφάλμα AI: {e}")
