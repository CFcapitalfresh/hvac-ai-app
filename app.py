import streamlit as st
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from PIL import Image
import io
import json
import tempfile
import time
import difflib
from google.api_core import exceptions
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Smart V8 (Index)", page_icon="🗂️", layout="centered")

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
    .index-status {
        padding: 8px; border-radius: 5px; margin-bottom: 10px; font-size: 12px;
    }
    .index-ok { background-color: #dcfce7; color: #166534; border: 1px solid #86efac; }
    .index-warn { background-color: #fef9c3; color: #854d0e; border: 1px solid #fde047; }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ ---
auth_status = "⏳ ..."
drive_service = None
available_models = []

try:
    # 1. AI
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name.replace("models/", ""))
        except:
            available_models = ["gemini-1.5-flash", "gemini-1.5-pro"]
    
    # 2. Drive (ΜΕ ΔΙΚΑΙΩΜΑ ΕΓΓΡΑΦΗΣ ΓΙΑ ΤΟ ΕΥΡΕΤΗΡΙΟ)
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        
        info = json.loads(gcp_raw)
        if "private_key" in info: 
            info["private_key"] = info["private_key"].replace("\\n", "\n")
            
        # ΠΡΟΣΟΧΗ: Εδώ αφαίρεσα το .readonly για να μπορεί να γράψει το index file
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Συνδέθηκε"
    else:
        auth_status = "⚠️ Χωρίς Drive"
except Exception as e:
    auth_status = f"⚠️ Error: {str(e)}"

# --- SIDEBAR & INDEX LOGIC ---
with st.sidebar:
    st.header("🗂️ Ευρετήριο")
    
    # Λογική Ευρετηρίου
    index_file_name = "hvac_index_v1.json"
    index_data = []
    
    def load_index_from_drive():
        """Προσπαθεί να βρει το αρχείο hvac_index_v1.json στο Drive"""
        if not drive_service: return None
        try:
            results = drive_service.files().list(
                q=f"name = '{index_file_name}' and trashed = false",
                fields="files(id, name)"
            ).execute()
            files = results.get('files', [])
            if files:
                # Κατέβασμα περιεχομένου
                file_id = files[0]['id']
                request = drive_service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False: _, done = downloader.next_chunk()
                return json.loads(fh.getvalue().decode('utf-8'))
        except Exception as e:
            st.error(f"Index Read Error: {e}")
        return None

    def save_index_to_drive(data):
        """Αποθηκεύει το ευρετήριο στο Drive (αν έχει δικαιώματα)"""
        if not drive_service: return
        try:
            # 1. Έλεγχος αν υπάρχει ήδη για να το κάνουμε update ή create
            results = drive_service.files().list(q=f"name = '{index_file_name}' and trashed = false").execute()
            files = results.get('files', [])
            
            file_metadata = {'name': index_file_name, 'mimeType': 'application/json'}
            media = MediaIoBaseUpload(io.BytesIO(json.dumps(data).encode('utf-8')), mimetype='application/json')
            
            if files:
                # Update
                drive_service.files().update(fileId=files[0]['id'], media_body=media).execute()
                st.toast("✅ Το ευρετήριο ενημερώθηκε στο Drive!")
            else:
                # Create
                drive_service.files().create(body=file_metadata, media_body=media).execute()
                st.toast("✅ Το ευρετήριο δημιουργήθηκε στο Drive!")
                
        except Exception as e:
            st.warning(f"⚠️ Δεν αποθηκεύτηκε στο Drive (Λείπει δικαίωμα Editor?): {e}")
            st.caption("Το σύστημα θα δουλέψει με το ευρετήριο στη μνήμη.")

    def build_new_index():
        """Σαρώνει όλα τα αρχεία και φτιάχνει λίστα"""
        if not drive_service: return []
        all_files = []
        page_token = None
        status_text = st.empty()
        try:
            while True:
                status_text.text(f"⏳ Σάρωση... ({len(all_files)} βρέθηκαν)")
                response = drive_service.files().list(
                    q="mimeType != 'application/vnd.google-apps.folder' and trashed = false",
                    fields='nextPageToken, files(id, name)',
                    pageSize=1000,
                    pageToken=page_token
                ).execute()
                all_files.extend(response.get('files', []))
                page_token = response.get('nextPageToken', None)
                if page_token is None: break
            
            status_text.empty()
            return all_files
        except Exception as e:
            st.error(f"Scan Error: {e}")
            return []

    # --- MAIN INDEX FLOW ---
    if "hvac_index" not in st.session_state:
        # 1. Προσπάθεια φόρτωσης από Drive
        loaded = load_index_from_drive()
        if loaded:
            st.session_state.hvac_index = loaded
            st.markdown(f'<div class="index-status index-ok">✅ Ευρετήριο Φορτώθηκε ({len(loaded)} αρχεία)</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="index-status index-warn">⚠️ Δεν βρέθηκε ευρετήριο.</div>', unsafe_allow_html=True)
            if st.button("🔄 Δημιουργία Ευρετηρίου Τώρα"):
                with st.spinner("Γίνεται σάρωση 1700+ αρχείων..."):
                    new_data = build_new_index()
                    if new_data:
                        st.session_state.hvac_index = new_data
                        save_index_to_drive(new_data) # Προσπάθεια αποθήκευσης
                        st.rerun()

    else:
        st.markdown(f'<div class="index-status index-ok">📂 Βάση: {len(st.session_state.hvac_index)} αρχεία</div>', unsafe_allow_html=True)
        if st.button("🔄 Ανανέωση"):
             with st.spinner("Επαναδημιουργία..."):
                new_data = build_new_index()
                st.session_state.hvac_index = new_data
                save_index_to_drive(new_data)
                st.rerun()

    st.divider()
    # Επιλογή Μοντέλου
    if available_models:
        idx = 0
        if "gemini-1.5-flash" in available_models: idx = available_models.index("gemini-1.5-flash")
        model_option = st.selectbox("Μοντέλο", available_models, index=idx)
    else:
        model_option = st.text_input("Μοντέλο", "gemini-1.5-flash")
    
    if st.button("🗑️ Καθαρισμός Chat"):
        st.session_state.messages = []
        st.rerun()

# --- MAIN APP ---
st.title("🗂️ HVAC Smart Expert")
c1, c2, c3 = st.columns(3)
if "tech_mode" not in st.session_state: st.session_state.tech_mode = "Τεχνικός HVAC"
if c1.button("❄️ AC"): st.session_state.tech_mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη"): st.session_state.tech_mode = "Ψυκτικός"
if c3.button("🔥 Αέριο"): st.session_state.tech_mode = "Τεχνικός Καυστήρων"
st.caption(f"Mode: **{st.session_state.tech_mode}**")

# --- CHAT ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

def find_file_in_index(query, index_data):
    if not index_data: return None
    query = query.lower()
    keywords = [w for w in query.split() if len(w) > 2]
    best_file = None
    max_score = 0
    
    for f in index_data:
        fname = f['name'].lower()
        score = 0
        for k in keywords:
            if k in fname: score += 3
        
        if score == 0:
            fname_clean = fname.replace('.pdf','').replace('.manual','')
            matches = difflib.get_close_matches(query, [fname_clean], n=1, cutoff=0.5)
            if matches: score += 1
            
        if score > max_score:
            max_score = score
            best_file = f
    return best_file

def download_file(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    return fh.getvalue()

with st.expander("📸 Φωτογραφία"):
    cam_img = st.camera_input("Λήψη")

user_input = st.chat_input("Ερώτηση...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"): st.markdown(user_input)
    
    with st.chat_message("assistant"):
        media_items = []
        manual_name = None
        
        if cam_img: media_items.append(Image.open(cam_img))
        
        # 1. Αναζήτηση στο Index (Μνήμη)
        if "hvac_index" in st.session_state and st.session_state.hvac_index:
            target = find_file_in_index(user_input, st.session_state.hvac_index)
            if target:
                st.markdown(f'<div class="source-box">📖 Βρήκα στο Ευρετήριο: {target["name"]}</div>', unsafe_allow_html=True)
                manual_name = target['name']
                try:
                    # Download File Content
                    with st.spinner("📥 Λήψη manual..."):
                        data = download_file(target['id'])
                        suffix = ".pdf" if ".pdf" in manual_name.lower() else ".jpg"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(data)
                            tmp_path = tmp.name
                        
                        gfile = genai.upload_file(tmp_path)
                        while gfile.state.name == "PROCESSING":
                            time.sleep(0.5)
                            gfile = genai.get_file(gfile.name)
                        media_items.append(gfile)
                except Exception as e:
                    st.error(f"File Error: {e}")
            else:
                st.caption("ℹ️ Δεν βρέθηκε σχετικό manual στο ευρετήριο.")
        
        # 2. AI Answer
        try:
            safe = {
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE
            }
            
            hist = ""
            for m in st.session_state.messages[-6:]: hist += f"{m['role']}: {m['content']}\n"
            
            prompt = f"""
            Είσαι {st.session_state.tech_mode}.
            Ιστορικό: {hist}
            Manual: {manual_name if manual_name else 'Κανένα (Χρήση Γενικής Γνώσης)'}
            Ερώτηση: {user_input}
            """
            
            with st.spinner("🧠 Σκέφτομαι..."):
                model = genai.GenerativeModel(model_option)
                resp = model.generate_content([prompt, *media_items], safety_settings=safe)
                if resp.text:
                    st.markdown(resp.text)
                    st.session_state.messages.append({"role": "assistant", "content": resp.text})
        except Exception as e:
            st.error(f"AI Error: {e}")
