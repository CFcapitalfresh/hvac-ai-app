import streamlit as st
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
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
st.set_page_config(page_title="HVAC Smart V9 (DB)", page_icon="🧠", layout="centered")

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
    .db-status {
        font-size: 12px; color: #666; margin-bottom: 10px;
    }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ (DRIVE & AI) ---
auth_status = "⏳ ..."
drive_service = None
available_models = []
DB_FILENAME = "hvac_manuals_index_v1.json" # Το όνομα της βάσης δεδομένων στο Drive

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
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Drive & AI Συνδεδεμένα"
    else:
        auth_status = "⚠️ Χωρίς Drive"
except Exception as e:
    auth_status = f"⚠️ Error: {str(e)}"

# --- DATABASE FUNCTIONS ---

def save_db_to_drive(data_dict):
    """Αποθηκεύει το JSON ευρετήριο στο Google Drive"""
    if not drive_service: return False
    try:
        # 1. Έλεγχος αν υπάρχει ήδη για να το διαγράψουμε (overwrite)
        q = f"name = '{DB_FILENAME}' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id)").execute()
        for f in res.get('files', []):
            drive_service.files().delete(fileId=f['id']).execute()
        
        # 2. Δημιουργία νέου αρχείου
        file_metadata = {'name': DB_FILENAME, 'mimeType': 'application/json'}
        
        # Μετατροπή dict σε JSON string
        json_str = json.dumps(data_dict, ensure_ascii=False)
        fh = io.BytesIO(json_str.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype='application/json')
        
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return True
    except Exception as e:
        print(f"Save DB Error: {e}")
        return False

def load_db_from_drive():
    """Φορτώνει το JSON ευρετήριο από το Drive"""
    if not drive_service: return None
    try:
        q = f"name = '{DB_FILENAME}' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id)").execute()
        files = res.get('files', [])
        
        if not files: return None # Δεν βρέθηκε βάση
        
        # Κατέβασμα
        file_id = files[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False: _, done = downloader.next_chunk()
        
        # Parsing JSON
        json_str = fh.getvalue().decode('utf-8')
        return json.loads(json_str)
    except:
        return None

def create_full_index():
    """Σαρώνει ΟΛΟ το Drive και φτιάχνει τη λίστα"""
    if not drive_service: return []
    all_files = []
    page_token = None
    
    try:
        while True:
            # Ψάχνουμε PDF και Εικόνες (όχι φακέλους)
            q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
            res = drive_service.files().list(
                q=q, 
                fields="nextPageToken, files(id, name)", 
                pageSize=1000, 
                pageToken=page_token
            ).execute()
            
            items = res.get('files', [])
            all_files.extend(items)
            
            page_token = res.get('nextPageToken', None)
            if page_token is None:
                break
        return all_files
    except Exception as e:
        st.error(f"Scan Error: {e}")
        return []

def search_local_db(query, db_files):
    """Αναζητά τοπικά στη μνήμη (πολύ γρήγορα)"""
    if not db_files: return None
    
    keywords = [w.lower() for w in query.split() if len(w) > 2]
    if not keywords: return None
    
    best_match = None
    highest_score = 0
    
    for f in db_files:
        fname = f['name'].lower()
        fname_clean = fname.replace('.pdf', '').replace('.jpg', '').replace('_', ' ')
        
        score = 0
        for k in keywords:
            if k in fname_clean: score += 1
            
        if score > highest_score:
            highest_score = score
            best_match = f
            
    return best_match

def download_file_content(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    return fh.getvalue()

# --- INIT SESSION ---
if "db_files" not in st.session_state:
    st.session_state.db_files = None # Η λίστα των αρχείων στη μνήμη

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    st.info(auth_status)
    st.divider()
    
    # ΕΠΙΛΟΓΗ ΜΟΝΤΕΛΟΥ
    if available_models:
        def_idx = 0
        if "gemini-1.5-flash" in available_models: def_idx = available_models.index("gemini-1.5-flash")
        elif "gemini-1.5-pro" in available_models: def_idx = available_models.index("gemini-1.5-pro")
        model_option = st.selectbox("Μοντέλο AI", available_models, index=def_idx)
    else:
        model_option = st.text_input("Μοντέλο", "gemini-1.5-flash")

    st.divider()
    
    # --- DB MANAGEMENT ---
    st.markdown("### 🗂️ Βάση Δεδομένων Manuals")
    
    # 1. Προσπάθεια φόρτωσης κατά την εκκίνηση
    if st.session_state.db_files is None and drive_service:
        with st.spinner("Φόρτωση ευρετηρίου..."):
            loaded_db = load_db_from_drive()
            if loaded_db:
                st.session_state.db_files = loaded_db
                st.success(f"Φορτώθηκαν {len(loaded_db)} αρχεία!")
            else:
                st.warning("Δεν βρέθηκε ευρετήριο.")

    # 2. Κουμπί δημιουργίας/ανανέωσης
    if st.button("🔄 Δημιουργία / Ανανέωση Ευρετηρίου", type="secondary"):
        if drive_service:
            with st.status("🔍 Σάρωση Google Drive...", expanded=True) as status:
                st.write("Συλλογή αρχείων από όλους τους φακέλους...")
                files = create_full_index()
                st.write(f"Βρέθηκαν {len(files)} αρχεία.")
                
                st.write("Αποθήκευση βάσης δεδομένων στο Drive...")
                if save_db_to_drive(files):
                    st.session_state.db_files = files
                    status.update(label="✅ Η Βάση Δεδομένων δημιουργήθηκε!", state="complete", expanded=False)
                    st.rerun()
                else:
                    status.update(label="❌ Σφάλμα αποθήκευσης", state="error")
    
    if st.session_state.db_files:
        st.caption(f"📚 Ευρετήριο: {len(st.session_state.db_files)} αρχεία")

    st.divider()
    if st.button("🗑️ Νέα Συζήτηση", type="primary"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER & MODES ---
st.title("🧠 HVAC Smart Expert (DB Edition)")

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

# --- CHAT UI ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- INPUT ---
with st.expander("📸 Προσθήκη Φώτο (Προαιρετικό)"):
    enable_cam = st.checkbox("Κάμερα")
    cam_img = st.camera_input("Λήψη") if enable_cam else None

prompt = st.chat_input("Γράψε βλάβη (π.χ. Ariston 501)...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        media_content = []
        found_file_name = None
        
        if cam_img: media_content.append(Image.open(cam_img))

        # --- SEARCH LOGIC (DB BASED) ---
        if ("Αρχεία" in search_source or "Υβριδικό" in search_source):
            if not st.session_state.db_files:
                st.warning("⚠️ Δεν έχει φορτωθεί η Βάση Δεδομένων. Πατήστε 'Ανανέωση Ευρετηρίου' στο μενού.")
            else:
                target_file = search_local_db(prompt, st.session_state.db_files)
                
                if target_file:
                    st.markdown(f'<div class="source-box">📖 Βρέθηκε στο Ευρετήριο: {target_file["name"]}</div>', unsafe_allow_html=True)
                    found_file_name = target_file['name']
                    
                    # Κατέβασμα και ανέβασμα στο Gemini
                    try:
                        with st.spinner("📥 Λήψη & Ανάγνωση αρχείου..."):
                            file_data = download_file_content(target_file['id'])
                            suffix = ".pdf" if "pdf" in target_file['name'].lower() else ".jpg"
                            
                            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                                tmp.write(file_data)
                                tmp_path = tmp.name
                            
                            gfile = genai.upload_file(tmp_path)
                            # Περιμένουμε να γίνει process
                            while gfile.state.name == "PROCESSING":
                                time.sleep(1)
                                gfile = genai.get_file(gfile.name)
                            media_content.append(gfile)
                    except Exception as e:
                        st.error(f"Error file processing: {e}")
                else:
                    if "Μόνο Αρχεία" in search_source:
                        st.warning("⚠️ Δεν βρέθηκε σχετικό manual στη βάση.")

        # --- AI GENERATION ---
        if media_content or "Γενική" in search_source or ("Υβριδικό" in search_source):
            
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            chat_history_str = ""
            for msg in st.session_state.messages[-8:]:
                role_label = "ΤΕΧΝΙΚΟΣ" if msg["role"] == "user" else "AI"
                chat_history_str += f"{role_label}: {msg['content']}\n"
            
            source_instr = f"Έχεις το manual '{found_file_name}'." if found_file_name else "Δεν βρέθηκε manual."
            
            full_prompt = f"""
            Είσαι {st.session_state.tech_mode}. Μίλα Ελληνικά.
            Πλαίσιο: Τεχνική υποστήριξη.
            
            === ΙΣΤΟΡΙΚΟ ===
            {chat_history_str}
            ================
            
            ΟΔΗΓΙΕΣ:
            1. {source_instr} Απάντησε ΑΠΟΚΛΕΙΣΤΙΚΑ βάσει αυτού αν υπάρχει.
            2. Αν υπάρχουν εικόνες/σχέδια στο PDF που βοηθάνε, ΠΕΡΙΓΡΑΨΕ ΤΑ: "Δες το Σχήμα Χ στη σελίδα Υ...".
            3. ΣΤΟ ΤΕΛΟΣ γράψε: "📚 **Πηγή:** [Όνομα Αρχείου]".
            
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
                        
                        # Fallback
                        if not response.candidates:
                            st.warning("⚠️ Το αρχείο μπλοκαρίστηκε. Συνεχίζω με Γενική Γνώση.")
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
                        st.toast(f"⏳ Φόρτος (429). Δοκιμή {attempt+1}...", icon="⏳")
                        time.sleep(wait)
                        continue
                    except Exception as e:
                        if attempt == retry_attempts - 1: st.error(f"Σφάλμα: {e}")
                        time.sleep(1)
                
                if not success: st.error("❌ Το σύστημα δεν μπόρεσε να απαντήσει.")
