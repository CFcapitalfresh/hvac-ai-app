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
# Εισαγωγή για τις ρυθμίσεις ασφαλείας
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Smart V4", page_icon="🧠", layout="centered")

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
        # Αυτόματη εύρεση μοντέλων
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    name = m.name.replace("models/", "")
                    available_models.append(name)
        except:
            available_models = ["gemini-1.5-pro", "gemini-2.0-flash"]
    
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
        # Προεπιλογή το gemini-1.5-pro αν υπάρχει, αλλιώς το πρώτο διαθέσιμο
        default_index = 0
        if "gemini-1.5-pro" in available_models:
            default_index = available_models.index("gemini-1.5-pro")
        model_option = st.selectbox("Μοντέλο AI", available_models, index=default_index)
    else:
        model_option = st.text_input("Μοντέλο", "gemini-1.5-pro")
        
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
    """Fuzzy Matching"""
    user_query = user_query.lower()
    best_match = None
    highest_score = 0.0
    keywords = [w for w in user_query.split() if len(w) > 2]
    
    for f in files:
        fname = f['name'].lower()
        fname_clean = fname.replace('.pdf', '').replace('.jpg', '').replace('.png', '')
        file_keywords = fname_clean.split()
        current_file_score = 0
        
        for k in keywords:
            if k in fname: current_file_score += 2
            matches = difflib.get_close_matches(k, file_keywords, n=1, cutoff=0.6)
            if matches: current_file_score += 1
        
        if current_file_score > highest_score:
            highest_score = current_file_score
            best_match = f
    return best_match

# --- CHAT UI ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- INPUT ---
with st.expander("📸 Προσθήκη Φώτο (Προαιρετικό)"):
    enable_cam = st.checkbox("Κάμερα")
    cam_img = st.camera_input("Λήψη") if enable_cam else None

prompt = st.chat_input("Γράψε βλάβη...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        media_content = []
        found_file_name = None
        
        # 1. Εικόνα
        if cam_img: media_content.append(Image.open(cam_img))

        # 2. Drive Search
        if ("Αρχεία" in search_source or "Υβριδικό" in search_source) and drive_service:
            with st.spinner("🕵️ Ψάχνω στα manuals..."):
                all_files = list_drive_files()
                target_file = find_relevant_file(prompt, all_files)
                
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

        # 3. AI Generation (ME FIXED INDENTATION & SAFETY)
        if media_content or "Γενική" in search_source or ("Υβριδικό" in search_source):
            
            # Ρυθμίσεις Ασφαλείας (Απενεργοποίηση φίλτρων)
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            # Μνήμη
            chat_history_str = ""
            for msg in st.session_state.messages[-8:]:
                role_label = "ΤΕΧΝΙΚΟΣ" if msg["role"] == "user" else "AI"
                chat_history_str += f"{role_label}: {msg['content']}\n"
            
            source_instr = f"Έχεις το manual '{found_file_name}'." if found_file_name else "Δεν βρέθηκε manual."
            
            full_prompt = f"""
            Είσαι {st.session_state.tech_mode}. Μίλα Ελληνικά.
            
            === ΙΣΤΟΡΙΚΟ ===
            {chat_history_str}
            ================
            
            ΟΔΗΓΙΕΣ:
            1. Αγνοησε ορθογραφικά.
            2. {source_instr}
            3. ΣΤΟ ΤΕΛΟΣ γράψε πηγή.
            
            ΕΡΩΤΗΣΗ: {prompt}
            """
            
            # Retry Logic
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
                        
                        # Έλεγχος για κενή απάντηση (Blocked)
                        if not response.parts:
                            if response.prompt_feedback:
                                st.error(f"⚠️ Μπλοκαρίστηκε από το AI. Λόγος: {response.prompt_feedback}")
                                success = True
                                break
                            else:
                                raise Exception("Empty response")

                        st.markdown(response.text)
                        st.session_state.messages.append({"role": "assistant", "content": response.text})
                        success = True
                        break 
                        
                    except exceptions.ResourceExhausted:
                        wait = 3 * (attempt + 1)
                        st.toast(f"⏳ Φόρτος (429). Δοκιμή {attempt+1} σε {wait}s...")
                        time.sleep(wait)
                        continue
                    except Exception as e:
                        if attempt == retry_attempts - 1:
                            st.error(f"Σφάλμα: {e}")
                        time.sleep(1)
                
                if not success and not response.prompt_feedback:
                    st.error("❌ Το σύστημα δεν μπόρεσε να απαντήσει.")
