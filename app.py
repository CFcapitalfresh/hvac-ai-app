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
import datetime

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(
    page_title="CF HVAC SMART", 
    page_icon="logo.png", 
    layout="wide"
)

# --- CSS STYLING (Εμφάνιση) ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    .source-box { background-color: #d1fae5; color: #065f46; padding: 10px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #34d399;}
    
    /* Στυλ για το Footer με τα Στοιχεία Επικοινωνίας */
    .sidebar-footer {
        font-size: 13px;
        color: #444;
        text-align: center;
        padding-top: 15px;
        border-top: 1px solid #ddd;
        margin-top: 30px;
        background-color: #f9f9f9; /* Ελαφρύ γκρι φόντο για να ξεχωρίζει */
        border-radius: 10px;
        padding-bottom: 10px;
    }
    .sidebar-footer a {
        color: #0066cc;
        text-decoration: none;
    }
</style>""", unsafe_allow_html=True)

# --- GLOBAL CONSTANTS ---
INDEX_FILE_NAME = "hvac_master_index_v10.json"
CURRENT_YEAR = datetime.datetime.now().year

# --- 1. ΣΥΝΔΕΣΗ & ΕΠΙΛΟΓΗ ΜΟΝΤΕΛΟΥ ---
auth_status = "⏳ ..."
drive_service = None
CURRENT_MODEL_NAME = "gemini-1.5-flash"

try:
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        try:
            # Έλεγχος για το καλύτερο μοντέλο
            all_models = [m.name.replace("models/", "") for m in genai.list_models()]
            priority_list = ["gemini-2.0-flash-exp", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]
            for wanted in priority_list:
                if wanted in all_models:
                    CURRENT_MODEL_NAME = wanted
                    break
        except: pass

    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        info = json.loads(gcp_raw)
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/drive'])
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Online"
except Exception as e:
    auth_status = f"⚠️ Error: {str(e)}"

# --- ΒΑΣΙΚΕΣ ΛΕΙΤΟΥΡΓΙΕΣ DRIVE ---
def load_index():
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
    if not drive_service: return
    try:
        results = drive_service.files().list(q=f"name = '{INDEX_FILE_NAME}' and trashed = false").execute()
        files = results.get('files', [])
        media = MediaIoBaseUpload(io.BytesIO(json.dumps(data).encode('utf-8')), mimetype='application/json')
        if files:
            drive_service.files().update(fileId=files[0]['id'], media_body=media).execute()
        else:
            drive_service.files().create(body={'name': INDEX_FILE_NAME, 'mimeType': 'application/json'}, media_body=media).execute()
    except Exception as e:
        print(f"Save Error: {e}")

def get_all_drive_files_meta():
    if not drive_service: return []
    all_files = []
    page_token = None
    try:
        while True:
            response = drive_service.files().list(q="mimeType != 'application/vnd.google-apps.folder' and trashed = false", fields='nextPageToken, files(id, name)', pageSize=1000, pageToken=page_token).execute()
            all_files.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None: break
        return all_files
    except: return []

def download_temp(file_id, file_name):
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
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        gfile = genai.upload_file(file_path)
        while gfile.state.name == "PROCESSING": time.sleep(0.5); gfile = genai.get_file(gfile.name)
        prompt = "Διάβασε την πρώτη σελίδα. Ποια είναι η Μάρκα και το Μοντέλο; Απάντησε ΜΟΝΟ με Μάρκα/Μοντέλο."
        response = model.generate_content([prompt, gfile])
        return response.text.strip()
    except: return "Manual (Auto-detect failed)"

# --- SIDEBAR (ΜΕΝΟΥ) ---
with st.sidebar:
    # 1. ΛΟΓΟΤΥΠΟ
    try:
        st.image("logo.png", use_column_width=True)
    except:
        st.warning("⚠️ Προσθέστε το αρχείο logo.png")
    
    st.divider()

    # 2. ΡΥΘΜΙΣΕΙΣ
    st.header("⚙️ Control Panel")
    
    # Ένδειξη Μοντέλου
    if "2.0" in CURRENT_MODEL_NAME: st.success(f"🚀 AI: {CURRENT_MODEL_NAME}")
    else: st.info(f"⚡ AI: {CURRENT_MODEL_NAME}")
        
    if "master_index" not in st.session_state: st.session_state.master_index = load_index()
        
    st.subheader("🔄 Database Sync")
    enable_sync = st.toggle("Ενεργοποίηση Sync", value=False)
    
    if enable_sync:
        if "drive_snapshot" not in st.session_state:
            with st.spinner("⏳ Σάρωση Drive..."): st.session_state.drive_snapshot = get_all_drive_files_meta()
        
        drive_files_map = {f['id']: f['name'] for f in st.session_state.drive_snapshot}
        indexed_ids = set(st.session_state.master_index.keys())
        drive_ids = set(drive_files_map.keys())
        new_files_ids = list(drive_ids - indexed_ids)
        
        st.caption(f"📚 Σύνολο Manuals: {len(indexed_ids)}")
        
        if new_files_ids:
            st.info(f"🆕 Νέα Αρχεία: {len(new_files_ids)}")
            to_process = new_files_ids[:1] # Safe Save (1-1 αρχείο)
            
            for fid in to_process:
                fname = drive_files_map[fid]
                st.write(f"🔍 Ανάλυση: `{fname}`...")
                try:
                    tmp_path = download_temp(fid, fname)
                    model_info = identify_model_with_ai(tmp_path)
                    st.session_state.master_index[fid] = {"name": fname, "model_info": model_info}
                except Exception as e: print(f"Error {fname}: {e}")
            
            save_index(st.session_state.master_index)
            st.rerun()
        else:
            st.success("✅ Η Βάση είναι Ενημερωμένη")
    
    # 3. FOOTER (COPYRIGHT & ΣΤΟΙΧΕΙΑ) - ΕΔΩ ΠΡΟΣΤΕΘΗΚΑΝ ΤΑ ΣΤΟΙΧΕΙΑ
    st.markdown("---") # Διαχωριστική γραμμή
    st.markdown(f"""
    <div class="sidebar-footer">
        <b>© {CURRENT_YEAR} CF Capital Fresh</b><br>
        All Rights Reserved<br>
        <br>
        📍 <b>Διεύθυνση:</b><br>
        16 Mias Milias Street<br>
        Lakatamia, Nicosia, P.C. 2323<br>
        <br>
        📞 <b>Τηλέφωνο:</b><br>
        <a href="tel:0035796573878">+357 96573878</a><br>
        <br>
        📧 <b>Email:</b><br>
        <a href="mailto:capitalfresh@cytanet.com.cy">capitalfresh@cytanet.com.cy</a><br>
        <br>
        🌐 <b>Website:</b><br>
        <a href="https://cfcapitalfresh.github.io/CFcapitalfreshen.io./" target="_blank">Επίσκεψη Ιστοσελίδας</a>
    </div>
    """, unsafe_allow_html=True)

# --- MAIN APP (ΚΥΡΙΑ ΟΘΟΝΗ) ---

# ΤΙΤΛΟΣ ΜΕ ΚΕΦΑΛΑΙΑ
st.title("CF HVAC SMART EXPERT (AUTO-AI)")

tab1, tab2 = st.tabs(["💬 Chat & Διάγνωση", "🗂️ Λίστα Manuals"])

with tab2:
    st.caption("Περιεχόμενα της Βάσης Δεδομένων:")
    st.json(dict(list(st.session_state.master_index.items())[:10]))

with tab1:
    c1, c2, c3 = st.columns(3)
    if "tech_mode" not in st.session_state: st.session_state.tech_mode = "Τεχνικός HVAC"
    
    # Κουμπιά επιλογής
    if c1.button("❄️ AC Unit"): st.session_state.tech_mode = "Τεχνικός Κλιματισμού"
    if c2.button("🧊 Refrigeration"): st.session_state.tech_mode = "Ψυκτικός"
    if c3.button("🔥 Gas Burner"): st.session_state.tech_mode = "Τεχνικός Καυστήρων"
    
    st.caption(f"🔧 Mode: **{st.session_state.tech_mode}**")

    # Ιστορικό Chat
    if "messages" not in st.session_state: st.session_state.messages = []
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    # Είσοδος Χρήστη
    user_input = st.chat_input("Γράψε κωδικό βλάβης ή σύμπτωμα...")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)
        
        with st.chat_message("assistant"):
            found_data, media_items = None, []
            
            # Αναζήτηση
            matches = []
            for fid, data in st.session_state.master_index.items():
                full_text = (data['name'] + " " + data['model_info']).lower()
                # Έξυπνη αναζήτηση
                if user_input.lower() in full_text or any(k in full_text for k in user_input.split() if len(k)>3): 
                    matches.append((fid, data))
            
            if matches:
                fid, data = matches[0]
                found_data = f"{data['model_info']} ({data['name']})"
                st.markdown(f'<div class="source-box">📖 Εντοπίστηκε Manual: <b>{found_data}</b></div>', unsafe_allow_html=True)
                try:
                    path = download_temp(fid, data['name'])
                    gf = genai.upload_file(path)
                    while gf.state.name == "PROCESSING": time.sleep(0.5); gf = genai.get_file(gf.name)
                    media_items.append(gf)
                except: pass
            
            # Απάντηση AI
            try:
                model = genai.GenerativeModel(CURRENT_MODEL_NAME)
                context = f"Έχεις το Manual: {found_data}" if found_data else "Δεν βρέθηκε συγκεκριμένο Manual, χρησιμοποίησε γενική εμπειρία."
                
                full_prompt = f"""
                Είσαι έμπειρος {st.session_state.tech_mode} της εταιρείας CF Capital Fresh.
                
                ΟΔΗΓΙΕΣ:
                1. {context}
                2. Απάντησε στα Ελληνικά, επαγγελματικά και σύντομα.
                3. Αν είναι κωδικός βλάβης, δώσε: Πιθανή Αιτία -> Λύση.
                
                ΕΡΩΤΗΣΗ: {user_input}
                """
                
                with st.spinner("🧠 Ανάλυση..."):
                    resp = model.generate_content([full_prompt, *media_items])
                    st.markdown(resp.text)
                    st.session_state.messages.append({"role": "assistant", "content": resp.text})
            except Exception as e: st.error(f"Error: {e}")
