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

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Smart", page_icon="🧠", layout="centered")

# --- CSS ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
    /* Πλαίσιο Πηγής */
    .source-box { 
        background-color: #d1fae5; 
        color: #065f46; 
        padding: 10px; 
        border-radius: 8px; 
        font-size: 14px; 
        font-weight: bold; 
        margin-bottom: 10px;
        border: 1px solid #34d399;
    }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ (DRIVE & AI) ---
auth_status = "⏳ ..."
drive_service = None

try:
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
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
        auth_status = "✅ Drive Συνδεδεμένο"
    else:
        auth_status = "⚠️ Χωρίς Drive"
except Exception as e:
    auth_status = f"⚠️ Drive Error: {str(e)}"

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    st.info(auth_status)
    st.divider()
    model_option = st.selectbox("Μοντέλο AI", ["gemini-2.0-flash", "gemini-2.0-pro-exp-02-05"])
    st.divider()
    if st.button("🗑️ Νέα Συζήτηση", type="primary"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER & MODES ---
st.title("🧠 HVAC Smart Expert")

c1, c2, c3 = st.columns(3)
if "tech_mode" not in st.session_state: st.session_state.tech_mode = "Τεχνικός HVAC"

if c1.button("❄️ AC"): st.session_state.tech_mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη"): st.session_state.tech_mode = "Ψυκτικός"
if c3.button("🔥 Αέριο"): st.session_state.tech_mode = "Τεχνικός Καυστήρων"

st.caption(f"Ειδικότητα: **{st.session_state.tech_mode}**")

# --- SEARCH SOURCE ---
search_source = st.radio(
    "🔎 Λειτουργία Αναζήτησης:",
    ["🧠 Υβριδικό (Smart)", "📂 Μόνο Αρχεία", "🌐 Μόνο Γενική Γνώση"],
    horizontal=True
)

# --- FUNCTIONS ---
def list_drive_files():
    if not drive_service: return []
    try:
        q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id, name)", pageSize=50).execute()
        return res.get('files', [])
    except: return []

def download_file_content(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    return fh.getvalue()

def find_relevant_file(user_query, files):
    """Αναζήτηση αρχείου με ανοχή στα λάθη"""
    user_query = user_query.lower()
    best_match = None
    
    # 1. Ακριβής αναζήτηση λέξεων (πάνω από 3 γράμματα)
    keywords = [w for w in user_query.split() if len(w) > 2]
    
    for f in files:
        fname = f['name'].lower()
        # Αν βρει έστω και μία λέξη κλειδί (π.χ. 'ariston')
        if any(k in fname for k in keywords):
            return f
            
    return None

# --- CHAT UI ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- INPUT ---
with st.expander("📸 Προσθήκη Φώτο (Προαιρετικό)"):
    enable_cam = st.checkbox("Κάμερα")
    cam_img = st.camera_input("Λήψη") if enable_cam else None

prompt = st.chat_input("Γράψε βλάβη (π.χ. ariston 501)...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        media_content = []
        found_file_name = None
        used_source = "Γενική Γνώση"
        
        # 1. Εικόνα
        if cam_img:
            media_content.append(Image.open(cam_img))

        # 2. Drive Search
        if ("Αρχεία" in search_source or "Υβριδικό" in search_source) and drive_service:
            with st.spinner("🕵️ Ψάχνω στα manuals..."):
                all_files = list_drive_files()
                target_file = find_relevant_file(prompt, all_files)
                
                if target_file:
                    # ΕΜΦΑΝΙΣΗ ΠΡΑΣΙΝΟΥ ΜΗΝΥΜΑΤΟΣ ΟΤΙ ΒΡΕΘΗΚΕ
                    st.markdown(f'<div class="source-box">📖 Βρήκα το manual: {target_file["name"]}</div>', unsafe_allow_html=True)
                    found_file_name = target_file['name']
                    used_source = f"Manual: {found_file_name}"
                    
                    try:
                        file_data = download_file_content(target_file['id'])
                        suffix = ".pdf" if "pdf" in target_file['name'].lower() else ".jpg"
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(file_data)
                            tmp_path = tmp.name
                        
                        gfile = genai.upload_file(tmp_path)
                        while gfile.state.name == "PROCESSING": 
                            time.sleep(0.5)
                            gfile = genai.get_file(gfile.name)
                        media_content.append(gfile)
                    except Exception as e:
                        st.error(f"Error reading file: {e}")
                else:
                    if "Μόνο Αρχεία" in search_source:
                        st.warning("⚠️ Δεν βρέθηκε manual. Δοκίμασε να γράψεις τη μάρκα πιο καθαρά.")

        # 3. AI Generation
        if media_content or "Γενική" in search_source or ("Υβριδικό" in search_source):
            try:
                model = genai.GenerativeModel(model_option)
                
                source_instruction = ""
                if found_file_name:
                    source_instruction = f"Έχεις το manual '{found_file_name}'. Απάντησε ΒΑΣΕΙ ΑΥΤΟΥ."
                else:
                    source_instruction = "Δεν βρέθηκε manual. Χρησιμοποίησε τη γενική σου γνώση."
                
                # ΕΙΔΙΚΗ ΕΝΤΟΛΗ ΓΙΑ ΠΗΓΕΣ ΚΑΙ ΛΑΘΗ
                full_prompt = f"""
                Είσαι {st.session_state.tech_mode}. Μίλα Ελληνικά.
                
                ΟΔΗΓΙΕΣ:
                1. Ο χρήστης μπορεί να κάνει ορθογραφικά λάθη ή να χρησιμοποιεί φωνητική πληκτρολόγηση (π.χ. "μάνια" αντί για "manual", "αριστο" αντί για "ariston"). ΚΑΤΑΛΑΒΕ ΤΙ ΕΝΝΟΕΙ και αγνόησε τα λάθη.
                2. {source_instruction}
                3. ΣΤΟ ΤΕΛΟΣ ΤΗΣ ΑΠΑΝΤΗΣΗΣ, άσε μια κενή γραμμή και γράψε με έντονα γράμματα την πηγή:
                   - Αν χρησιμοποίησες αρχείο: "📚 **Πηγή:** Manual ({found_file_name if found_file_name else 'Άγνωστο'})"
                   - Αν όχι: "🌐 **Πηγή:** Γενική Γνώση (AI)"
                
                Ερώτηση: {prompt}
                """
                
                with st.spinner("🧠 Επεξεργασία..."):
                    # Καθαρή κλήση
                    response = model.generate_content([full_prompt, *media_content])
                    st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                 
            except Exception as e:
                st.error(f"Σφάλμα AI: {e}")
