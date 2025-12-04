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
st.set_page_config(page_title="HVAC Master AI", page_icon="🤖", layout="centered")

# CSS
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
    /* Κάνε τα μηνύματα πηγών διακριτικά */
    .source-tag { font-size: 0.8em; color: #fbbf24; font-weight: bold; }
</style>""", unsafe_allow_html=True)

# --- AUTH ---
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
    st.title("🎛️ Πίνακας Ελέγχου")
    if "✅" in auth_status: st.success(auth_status)
    else: st.warning(auth_status)
    
    st.divider()
    
    # 1. ΕΠΙΛΟΓΗ ΜΟΝΤΕΛΟΥ
    model_map = {
        "🚀 Flash 2.0 (Ταχύτητα)": "gemini-2.0-flash",
        "🧠 Pro 1.5 (Ακρίβεια)": "gemini-1.5-pro",
    }
    model_label = st.radio("Μοντέλο:", list(model_map.keys()))
    model_option = model_map[model_label]
    
    st.divider()
    
    # 2. ΕΠΙΛΟΓΗ ΠΗΓΗΣ ΕΡΕΥΝΑΣ (ΝΕΟ!)
    st.markdown("### 🔍 Πού να ψάξω;")
    search_mode = st.radio(
        "Επιλογή:",
        ["🌐 Internet (Google)", "📂 Αρχεία (Drive/Uploads)", "✨ Παντού (Smart)"],
        index=2
    )
    
    st.divider()
    if st.button("🗑️ Νέα Συζήτηση"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER ---
st.title("🤖 HVAC Master AI")
st.caption("Ο προσωπικός σου συνεργάτης πεδίου.")

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

# Ειδικότητα
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"
st.caption(f"Ρόλος: **{st.session_state.mode}**")

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

prompt = st.chat_input("Πες μου το πρόβλημα (ή γράψε κωδικό)...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    # 1. Ετοιμασία Αρχείων (Media)
    media = []
    
    # Αν έχουμε επιλέξει "Αρχεία" ή "Παντού", φορτώνουμε τα media
    use_files = search_mode in ["📂 Αρχεία (Drive/Uploads)", "✨ Παντού (Smart)"]
    
    if use_files:
        if cam_img: media.append(Image.open(cam_img))
        if sel_file:
            with st.spinner(f"📥 Μελέτη {sel_file['name']}..."):
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

    # 2. Ρύθμιση Εργαλείων (Tools - Google Search)
    tools = []
    # Αν έχουμε επιλέξει "Internet" ή "Παντού", ενεργοποιούμε το Google Search
    if search_mode in ["🌐 Internet (Google)", "✨ Παντού (Smart)"]:
        tools = 'google_search-retrieval' # Ενεργοποίηση Grounding

    # 3. Ο "Εγκέφαλος" (System Prompt)
    # Εδώ δίνουμε την προσωπικότητα και τις οδηγίες για τα λάθη
    system_instruction = f"""
    Είσαι ο {st.session_state.mode}, ένας έμπειρος, φιλικός και συνεργάσιμος συνάδελφος.
    
    ΟΔΗΓΙΕΣ ΣΥΜΠΕΡΙΦΟΡΑΣ:
    1. Να είσαι ευγενικός και κοινωνικός (π.χ. "Καλημέρα μάστορα", "Μην αγχώνεσαι, θα το βρούμε").
    2. Αν ο χρήστης κάνει λάθη στην ομιλία (π.χ. πει "βλάβη έξι" αντί για "Ε6", ή "αντλία θερμότητας" με λάθος λέξεις), ΠΡΟΣΠΑΘΗΣΕ ΝΑ ΚΑΤΑΛΑΒΕΙΣ τι εννοεί βάσει συμφραζόμενων. Μην κολλάς στην ορθογραφία.
    3. Αν δεν είσαι σίγουρος, ρώτα τον χρήστη ευγενικά.
    
    ΟΔΗΓΙΕΣ ΑΠΑΝΤΗΣΗΣ & ΠΗΓΩΝ:
    1. Πρέπει ΟΠΩΣΔΗΠΟΤΕ να αναφέρεις από πού βρήκες την πληροφορία.
    2. Αν τη βρήκες στο Google, γράψε στο τέλος: **[Πηγή: Διαδίκτυο 🌐]**
    3. Αν τη βρήκες στα αρχεία που σου δόθηκαν, γράψε: **[Πηγή: Αρχείο {sel_file['name'] if sel_file else 'Media'} 📂]**
    4. Αν είναι από τις γενικές σου γνώσεις, γράψε: **[Πηγή: Γνώσεις AI 🤖]**
    
    Απάντησε στα Ελληνικά, αναλυτικά και τεχνικά.
    """

    # 4. Απάντηση
    with st.chat_message("assistant"):
        with st.spinner(f"🧠 Έρευνα ({search_mode})..."):
            try:
                # Επιλογή σωστής κλήσης ανάλογα με τα εργαλεία
                model = genai.GenerativeModel(model_option)
                
                # Αν θέλουμε Google Search, το ενεργοποιούμε δυναμικά
                if search_mode in ["🌐 Internet (Google)", "✨ Παντού (Smart)"]:
                    # Σημείωση: Το grounding λειτουργεί καλύτερα χωρίς media στο ίδιο request σε κάποιες εκδόσεις,
                    # αλλά εδώ το δοκιμάζουμε συνδυαστικά.
                     response = model.generate_content(
                        [system_instruction + f"\nΕρώτηση: {prompt}", *media],
                        tools='google_search_retrieval' # Grounding
                    )
                else:
                    # Χωρίς Google Search (μόνο αρχεία/γνώση)
                    response = model.generate_content(
                        [system_instruction + f"\nΕρώτηση: {prompt}", *media]
                    )

                # Έλεγχος αν υπάρχει απάντηση
                if response.text:
                    st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                    
                    # Εμφάνιση πηγών grounding (αν υπάρχουν από το Google)
                    if response.candidates[0].grounding_metadata.search_entry_point:
                        st.caption("🔎 Βρέθηκε μέσω Google Search")

            except Exception as e:
                st.error("Κάτι πήγε στραβά. Δοκίμασε να αλλάξεις μοντέλο ή να απλοποιήσεις την ερώτηση.")
                st.caption(f"Error details: {e}")
