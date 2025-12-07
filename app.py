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
import difflib
from google.api_core import exceptions
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Smart V7", page_icon="🧠", layout="centered")

# --- CSS ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; }
    .source-box { 
        background-color: #d1fae5; color: #065f46; padding: 10px; 
        border-radius: 8px; font-size: 14px; font-weight: bold; 
        margin-bottom: 10px; border: 1px solid #34d399;
    }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ (DRIVE & AI) ---
auth_status = "⏳ ..."
drive_service = None
available_models = []

try:
    # 1. Σύνδεση AI
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    name = m.name.replace("models/", "")
                    available_models.append(name)
        except:
            available_models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]
    
    # 2. Σύνδεση Drive
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
        auth_status = "✅ Drive & AI Συνδεδεμένα"
    else:
        auth_status = "⚠️ Χωρίς Drive"
except Exception as e:
    auth_status = f"⚠️ Error: {str(e)}"

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    st.info(auth_status)
    st.divider()
    
    if available_models:
        default_idx = 0
        if "gemini-1.5-flash" in available_models:
            default_idx = available_models.index("gemini-1.5-flash")
        elif "gemini-1.5-pro" in available_models:
            default_idx = available_models.index("gemini-1.5-pro")
        model_option = st.selectbox("Μοντέλο AI", available_models, index=default_idx)
    else:
        model_option = st.text_input("Μοντέλο", "gemini-1.5-flash")
        
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

# --- FUNCTIONS (UPDATED FOR SUBFOLDERS) ---
def search_drive_smart(user_query):
    """Ψάχνει σε ΟΛΟ το Drive (Server-side) για λέξεις κλειδιά"""
    if not drive_service: return None
    
    # 1. Βρες λέξεις κλειδιά (πάνω από 2 γράμματα)
    keywords = [w for w in user_query.split() if len(w) > 2]
    if not keywords: return None

    # 2. Φτιάξε φίλτρο: (name contains 'A' and name contains 'B'...)
    # Αυτό ψάχνει παντού, σε φακέλους και υποφακέλους
    name_filters = [f"name contains '{k}'" for k in keywords]
    name_query = " and ".join(name_filters)
    
    try:
        # Ψάχνουμε αρχεία (όχι φακέλους) που δεν είναι διεγραμμένα
        q = f"mimeType != 'application/vnd.google-apps.folder' and trashed = false and ({name_query})"
        
        # Ζητάμε τα 5 πιο σχετικά
        res = drive_service.files().list(q=q, fields="files(id, name)", pageSize=5).execute()
        files = res.get('files', [])
        
        if files:
            return files[0] # Επιστρέφουμε το πρώτο που βρέθηκε
    except Exception as e:
        print(f"Search Error: {e}")
        return None
    return None

def download_file_content(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    return fh.getvalue()

# --- CHAT UI ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- INPUT ---
with st.expander("📸 Προσθήκη Φώτο (Προαιρετικό)"):
    enable_cam = st.checkbox("Κάμερα")
    cam_img = st.camera_input("Λήψη") if enable_cam else None

prompt = st.chat_input("Γράψε βλάβη (π.χ. ariston error)...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        media_content = []
        found_file_name = None
        
        # 1. Εικόνα
        if cam_img: media_content.append(Image.open(cam_img))

        # 2. Drive Search (SMART & RECURSIVE)
        if ("Αρχεία" in search_source or "Υβριδικό" in search_source) and drive_service:
            with st.spinner("🕵️ Ψάχνω στα manuals (Subfolders)..."):
                target_file = search_drive_smart(prompt)
                
                if target_file:
                    st.markdown(f'<div class="source-box">📖 Βρήκα: {target_file["name"]}</div>', unsafe_allow_html=True)
                    found_file_name = target_file['name']
                    try:
                        file_data = download_file_content(target_file['id'])
                        suffix = ".pdf" if "pdf" in target_file['name'].lower() else ".jpg"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(file_data)
                            tmp_path = tmp.name
                        
                        gfile = genai.upload_file(tmp_path)
                        while gfile.state.name == "PROCESSING": 
                            time.sleep(1)
                            gfile = genai.get_file(gfile.name)
                        media_content.append(gfile)
                    except Exception as e:
                        st.error(f"Error reading file: {e}")
                else:
                    if "Μόνο Αρχεία" in search_source:
                        st.warning("⚠️ Δεν βρέθηκε manual.")

        # 3. AI Generation (ROBUST V7)
        if media_content or "Γενική" in search_source or ("Υβριδικό" in search_source):
            
            # Απενεργοποίηση Φίλτρων (Για να περνάνε τα manuals)
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            # Μνήμη (Context)
            chat_history_str = ""
            for msg in st.session_state.messages[-8:]:
                role_label = "ΤΕΧΝΙΚΟΣ" if msg["role"] == "user" else "AI"
                chat_history_str += f"{role_label}: {msg['content']}\n"
            
            source_instr = f"Έχεις το manual '{found_file_name}'." if found_file_name else "Δεν βρέθηκε manual."
            
            full_prompt = f"""
            Είσαι {st.session_state.tech_mode}. Μίλα Ελληνικά.
            Πλαίσιο: Τεχνική υποστήριξη για εξουσιοδοτημένους τεχνικούς.
            
            === ΙΣΤΟΡΙΚΟ ===
            {chat_history_str}
            ================
            
            ΟΔΗΓΙΕΣ:
            1. {source_instr}
            2. Αν το manual δεν βοηθάει, χρησιμοποίησε γενική γνώση.
            3. ΣΤΟ ΤΕΛΟΣ γράψε πηγή.
            
            ΕΡΩΤΗΣΗ: {prompt}
            """
            
            retry_attempts = 3
            success = False
            
            with st.spinner("🧠 Επεξεργασία..."):
                for attempt in range(retry_attempts):
                    try:
                        model = genai.GenerativeModel(model_option)
                        response = model.generate_content(
                            [full_prompt, *media_content],
                            safety_settings=safety_settings
                        )
                        
                        # Fallback Logic: Αν μπλοκαριστεί το αρχείο, δοκιμάζουμε χωρίς αυτό
                        if not response.candidates:
                            st.warning("⚠️ Το manual μπλοκαρίστηκε (Safety). Δοκιμάζω με Γενική Γνώση...")
                            fallback_content = [full_prompt]
                            if cam_img and len(media_content) > 1: fallback_content.append(media_content[0])
                            
                            response = model.generate_content(fallback_content, safety_settings=safety_settings)
                            if not response.candidates: raise Exception("Blocked completely")

                        ans_text = response.text 
                        st.markdown(ans_text)
                        st.session_state.messages.append({"role": "assistant", "content": ans_text})
                        success = True
                        break 
                        
                    except exceptions.ResourceExhausted:
                        wait = 3 * (attempt + 1)
                        st.toast(f"⏳ Φόρτος (429). Δοκιμή {attempt+1} σε {wait}s...")
                        time.sleep(wait)
                        continue
                    except Exception as e:
                        if attempt == retry_attempts - 1: st.error(f"Σφάλμα: {e}")
                        time.sleep(1)
                
                if not success: st.error("❌ Το σύστημα δεν μπόρεσε να απαντήσει.")
