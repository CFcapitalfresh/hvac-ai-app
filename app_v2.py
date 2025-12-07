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
from google.api_core import exceptions

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Smart V-Final (Safe Save)", page_icon="🤖", layout="wide")

# --- CSS STYLING ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    .source-box { background-color: #d1fae5; color: #065f46; padding: 10px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #34d399;}
    .status-box { padding: 10px; border-radius: 8px; margin-bottom: 10px; font-size: 14px; border: 1px solid #ddd; }
</style>""", unsafe_allow_html=True)

# --- GLOBAL CONSTANTS ---
INDEX_FILE_NAME = "hvac_master_index_v10.json"

# --- 1. ΣΥΝΔΕΣΗ & ΕΠΙΛΟΓΗ ΜΟΝΤΕΛΟΥ (AUTO) ---
auth_status = "⏳ ..."
drive_service = None
CURRENT_MODEL_NAME = "gemini-1.5-flash" # Default safe start

try:
    # A. Setup Google AI
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        
        # --- ΛΟΓΙΚΗ ΑΥΤΟΜΑΤΗΣ ΕΠΙΛΟΓΗΣ (AUTO-SELECT) ---
        try:
            # 1. Λήψη όλων των μοντέλων
            all_models = [m.name.replace("models/", "") for m in genai.list_models()]
            
            # 2. Λίστα προτίμησης (Από το καλύτερο στο χειρότερο)
            priority_list = [
                "gemini-2.0-flash-exp", # Experimental New
                "gemini-2.0-flash",     # Stable New (αν βγει)
                "gemini-1.5-pro",       # High Intelligence
                "gemini-1.5-flash"      # Fast & Cheap
            ]
            
            # 3. Επιλογή
            detected_model = None
            for wanted in priority_list:
                if wanted in all_models:
                    detected_model = wanted
                    break
            
            if detected_model:
                CURRENT_MODEL_NAME = detected_model
        except Exception as e:
            print(f"Auto-select failed, using default: {e}")

    # B. Setup Google Drive
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        info = json.loads(gcp_raw)
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Online"
except Exception as e:
    auth_status = f"⚠️ Error: {str(e)}"

# --- ΒΑΣΙΚΕΣ ΛΕΙΤΟΥΡΓΙΕΣ DRIVE ---

def load_index():
    """Φορτώνει το JSON Ευρετήριο από το Drive"""
    if not drive_service: return {}
    try:
        results = drive_service.files().list(q=f"name = '{INDEX_FILE_NAME}' and trashed = false", fields="files(id)").execute()
        files = results.get('files', [])
        if files:
            file_id = files[0]['id']
            request = drive_service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False: _, done = downloader.next_chunk()
            return json.loads(fh.getvalue().decode('utf-8'))
    except: pass
    return {} 

def save_index(data):
    """Αποθηκεύει το JSON Ευρετήριο πίσω στο Drive"""
    if not drive_service: return
    try:
        results = drive_service.files().list(q=f"name = '{INDEX_FILE_NAME}' and trashed = false").execute()
        files = results.get('files', [])
        file_metadata = {'name': INDEX_FILE_NAME, 'mimeType': 'application/json'}
        media = MediaIoBaseUpload(io.BytesIO(json.dumps(data).encode('utf-8')), mimetype='application/json')
        if files:
            drive_service.files().update(fileId=files[0]['id'], media_body=media).execute()
        else:
            drive_service.files().create(body=file_metadata, media_body=media).execute()
    except Exception as e:
        print(f"Save Error: {e}")

def get_all_drive_files_meta():
    """Φέρνει λίστα με ΟΛΑ τα αρχεία του Drive (για το Sync)"""
    if not drive_service: return []
    all_files = []
    page_token = None
    try:
        while True:
            response = drive_service.files().list(
                q="mimeType != 'application/vnd.google-apps.folder' and trashed = false",
                fields='nextPageToken, files(id, name)',
                pageSize=1000,
                pageToken=page_token
            ).execute()
            all_files.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None: break
        return all_files
    except: return []

def download_temp(file_id, file_name):
    """Κατεβάζει προσωρινά ένα αρχείο για ανάλυση"""
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    suffix = ".pdf" if ".pdf" in file_name.lower() else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(fh.getvalue())
        return tmp.name

def identify_model_with_ai(file_path):
    """AI Vision: Βλέπει την πρώτη σελίδα και βρίσκει το Μοντέλο"""
    try:
        # Χρήση του δυναμικού μοντέλου
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        gfile = genai.upload_file(file_path)
        while gfile.state.name == "PROCESSING": 
            time.sleep(0.5)
            gfile = genai.get_file(gfile.name)
        
        prompt = "Διάβασε την πρώτη σελίδα. Ποια είναι η Μάρκα και το Μοντέλο; Απάντησε ΜΟΝΟ με Μάρκα/Μοντέλο. Αν δεν φαίνεται, γράψε 'Άγνωστο'."
        response = model.generate_content([prompt, gfile])
        return response.text.strip()
    except:
        return "Manual (Auto-detect failed)"

# --- SIDEBAR: SYNC & STATUS ---
with st.sidebar:
    st.header("⚙️ Διαχείριση")
    st.caption(auth_status)
    
    # ΕΝΔΕΙΞΗ ΜΟΝΤΕΛΟΥ (Ζωντανή)
    st.divider()
    st.subheader("🧠 AI Brain Status")
    if "2.0" in CURRENT_MODEL_NAME:
        st.success(f"🚀 Running: **{CURRENT_MODEL_NAME}**")
        st.caption("Next-Gen Speed & Vision")
    elif "pro" in CURRENT_MODEL_NAME:
        st.info(f"💎 Running: **{CURRENT_MODEL_NAME}**")
        st.caption("High Reasoning")
    else:
        st.warning(f"⚡ Running: **{CURRENT_MODEL_NAME}**")
        st.caption("Standard Fast Model")
        
    st.divider()

    # Φόρτωση Index
    if "master_index" not in st.session_state:
        st.session_state.master_index = load_index()
        
    st.subheader("🔄 Συγχρονισμός (Sync)")
    enable_sync = st.toggle("Ενεργοποίηση Sync", value=False)
    
    if enable_sync:
        # Λογική Συγχρονισμού
        if "drive_snapshot" not in st.session_state:
            with st.spinner("⏳ Λήψη λίστας αρχείων από Drive..."):
                st.session_state.drive_snapshot = get_all_drive_files_meta()
        
        drive_files_map = {f['id']: f['name'] for f in st.session_state.drive_snapshot}
        indexed_ids = set(st.session_state.master_index.keys())
        drive_ids = set(drive_files_map.keys())
        
        new_files_ids = list(drive_ids - indexed_ids)
        deleted_files_ids = list(indexed_ids - drive_ids)
        
        total = len(drive_ids)
        indexed = len(indexed_ids) - len(deleted_files_ids)
        
        st.progress(min(indexed / total if total > 0 else 0, 1.0))
        st.write(f"📊 **Index:** {indexed} / {total}")
        
        if new_files_ids:
            st.info(f"🆕 Νέα: {len(new_files_ids)}")
            
            # --- ΣΗΜΑΝΤΙΚΗ ΑΛΛΑΓΗ ΕΔΩ: Processing Batch = 1 ---
            # Επεξεργασία 1 αρχείου τη φορά για άμεση αποθήκευση
            to_process = new_files_ids[:1] 
            
            status_placeholder = st.empty()
            
            for fid in to_process:
                fname = drive_files_map[fid]
                status_placeholder.markdown(f"🔍 AI Ανάλυση: `{fname}`...")
                try:
                    tmp_path = download_temp(fid, fname)
                    model_info = identify_model_with_ai(tmp_path)
                    st.session_state.master_index[fid] = {"name": fname, "model_info": model_info}
                except Exception as e:
                    print(f"Error {fname}: {e}")
            
            status_placeholder.text("💾 Saving Index...")
            save_index(st.session_state.master_index)
            st.rerun() # Επανεκκίνηση για το επόμενο
            
        elif deleted_files_ids:
            st.warning("🗑️ Καθαρισμός Διαγραμμένων...")
            for did in deleted_files_ids:
                del st.session_state.master_index[did]
            save_index(st.session_state.master_index)
            st.rerun()
        else:
            st.success("✅ System Up to Date")
            if "drive_snapshot" in st.session_state:
                del st.session_state.drive_snapshot

# --- MAIN APP ---
st.title("🤖 HVAC Smart Expert (Auto-AI)")

# Tabs
tab1, tab2 = st.tabs(["💬 Chat & Διάγνωση", "🗂️ Βάση Δεδομένων"])

with tab2:
    st.metric("Σύνολο Manuals", len(st.session_state.master_index))
    st.json(dict(list(st.session_state.master_index.items())[:10]))

with tab1:
    # Επιλογή Ρόλου
    c1, c2, c3 = st.columns(3)
    if "tech_mode" not in st.session_state: st.session_state.tech_mode = "Τεχνικός HVAC"
    if c1.button("❄️ AC"): st.session_state.tech_mode = "Τεχνικός Κλιματισμού"
    if c2.button("🧊 Ψύξη"): st.session_state.tech_mode = "Ψυκτικός"
    if c3.button("🔥 Αέριο"): st.session_state.tech_mode = "Τεχνικός Καυστήρων"

    # Search Function
    def search_index(query):
        query = query.lower()
        matches = []
        for fid, data in st.session_state.master_index.items():
            full_text = (data['name'] + " " + data['model_info']).lower()
            if query in full_text or any(k in full_text for k in query.split() if len(k)>2):
                matches.append((fid, data))
        return matches[:1] # Επιστροφή του πιο σχετικού

    # Chat History
    if "messages" not in st.session_state: st.session_state.messages = []
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    # User Input
    user_input = st.chat_input("Περιέγραψε τη βλάβη ή τον κωδικό...")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)
        
        with st.chat_message("assistant"):
            found_data = None
            media_items = []
            
            # 1. Αναζήτηση στο Index
            if st.session_state.master_index:
                hits = search_index(user_input)
                if hits:
                    fid, data = hits[0]
                    found_data = f"{data['model_info']} ({data['name']})"
                    st.markdown(f'<div class="source-box">📖 Βρέθηκε Manual: {found_data}</div>', unsafe_allow_html=True)
                    
                    # Κατέβασμα για το Chat Context
                    try:
                        with st.spinner("📥 Φόρτωση manual για ανάλυση..."):
                            path = download_temp(fid, data['name'])
                            gf = genai.upload_file(path)
                            while gf.state.name == "PROCESSING": 
                                time.sleep(0.5)
                                gf = genai.get_file(gf.name)
                            media_items.append(gf)
                    except: 
                        st.warning("⚠️ Δεν μπόρεσα να ανοίξω το αρχείο, συνεχίζω με γενική γνώση.")
            
            # 2. Απάντηση AI (Dynamic Model)
            try:
                model = genai.GenerativeModel(CURRENT_MODEL_NAME)
                
                # Context Prompting
                context_str = f"Έχεις το manual: {found_data}" if found_data else "Δεν βρέθηκε συγκεκριμένο manual, χρησιμοποίησε γενική γνώση."
                
                full_prompt = f"""
                Είσαι έμπειρος {st.session_state.tech_mode}.
                ΟΔΗΓΙΕΣ:
                1. {context_str}
                2. Απάντησε στα Ελληνικά, σύντομα και τεχνικά.
                3. Αν είναι κωδικός βλάβης, δώσε πιθανές αιτίες και λύσεις.
                
                ΕΡΩΤΗΣΗ ΤΕΧΝΙΚΟΥ: {user_input}
                """
                
                with st.spinner(f"🧠 Σκέφτομαι (με {CURRENT_MODEL_NAME})..."):
                    resp = model.generate_content([full_prompt, *media_items])
                    st.markdown(resp.text)
                    st.session_state.messages.append({"role": "assistant", "content": resp.text})
                    
            except Exception as e:
                st.error(f"Error: {e}")
