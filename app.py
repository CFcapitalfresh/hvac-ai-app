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
st.set_page_config(page_title="HVAC Smart V10 (Pro Sync)", page_icon="🔄", layout="wide")

# --- CSS ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    .source-box { background-color: #d1fae5; color: #065f46; padding: 10px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #34d399;}
    .status-box { padding: 10px; border-radius: 8px; margin-bottom: 10px; font-size: 14px; border: 1px solid #ddd; }
    .status-sync { background-color: #dbeafe; color: #1e40af; border-color: #93c5fd; }
    .status-ok { background-color: #dcfce7; color: #166534; border-color: #86efac; }
</style>""", unsafe_allow_html=True)

# --- GLOBAL CONSTANTS ---
INDEX_FILE_NAME = "hvac_master_index_v10.json"

# --- ΣΥΝΔΕΣΗ ---
auth_status = "⏳ ..."
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
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Online"
except Exception as e:
    auth_status = f"⚠️ Error: {str(e)}"

# --- ΒΑΣΙΚΕΣ ΛΕΙΤΟΥΡΓΙΕΣ ---

def load_index():
    """Φορτώνει το Ευρετήριο από το Drive"""
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
    """Αποθηκεύει το Ευρετήριο"""
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
    """Φέρνει ΜΟΝΟ IDs και Names από ΟΛΑ τα αρχεία του Drive"""
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
    """AI Vision για αναγνώριση μοντέλου"""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        gfile = genai.upload_file(file_path)
        while gfile.state.name == "PROCESSING": time.sleep(0.5); gfile = genai.get_file(gfile.name)
        
        prompt = "Διάβασε την πρώτη σελίδα. Ποια είναι η Μάρκα και το Μοντέλο; Απάντησε ΜΟΝΟ με Μάρκα/Μοντέλο. Αν δεν φαίνεται, γράψε 'Άγνωστο'."
        response = model.generate_content([prompt, gfile])
        return response.text.strip()
    except:
        return "Manual"

# --- SIDEBAR: CONTROLS & STATUS ---
with st.sidebar:
    st.header("⚙️ Διαχείριση")
    st.caption(auth_status)
    
    # Φόρτωση Index στη μνήμη (αν δεν υπάρχει)
    if "master_index" not in st.session_state:
        st.session_state.master_index = load_index()
        
    st.divider()
    st.subheader("🔄 Συγχρονισμός (Sync)")
    
    enable_sync = st.toggle("Ενεργοποίηση Sync", value=False)
    
    if enable_sync:
        # 1. ΒΗΜΑ: Λήψη πραγματικής κατάστασης Drive
        if "drive_snapshot" not in st.session_state:
            with st.spinner("⏳ Λήψη λίστας αρχείων από Drive..."):
                st.session_state.drive_snapshot = get_all_drive_files_meta()
        
        # 2. ΒΗΜΑ: Υπολογισμός Διαφορών (The Delta Logic)
        drive_files_map = {f['id']: f['name'] for f in st.session_state.drive_snapshot}
        indexed_ids = set(st.session_state.master_index.keys())
        drive_ids = set(drive_files_map.keys())
        
        # Ποια είναι καινούργια (Υπάρχουν στο Drive αλλά όχι στο Index)
        new_files_ids = list(drive_ids - indexed_ids)
        
        # Ποια διαγράφηκαν (Υπάρχουν στο Index αλλά όχι στο Drive)
        deleted_files_ids = list(indexed_ids - drive_ids)
        
        total_files = len(drive_ids)
        indexed_count = len(indexed_ids) - len(deleted_files_ids) # Πραγματικά indexed
        
        # 3. ΒΗΜΑ: Εμφάνιση Στατιστικών
        st.progress(min(indexed_count / total_files if total_files > 0 else 0, 1.0))
        st.write(f"📊 **Πρόοδος:** {indexed_count} / {total_files}")
        
        if new_files_ids:
            st.info(f"🆕 Προς Σάρωση: {len(new_files_ids)} αρχεία")
        else:
            st.success("✅ Όλα τα νέα αρχεία έχουν σαρωθεί.")
            
        if deleted_files_ids:
            st.warning(f"🗑️ Προς Διαγραφή: {len(deleted_files_ids)} αρχεία")

        # 4. ΒΗΜΑ: ΕΚΤΕΛΕΣΗ (Batch Processing)
        # Προτεραιότητα 1: Καθαρισμός (είναι γρήγορος)
        if deleted_files_ids:
            for did in deleted_files_ids:
                del st.session_state.master_index[did]
            save_index(st.session_state.master_index)
            st.rerun() # Επανεκκίνηση για ενημέρωση
            
        # Προτεραιότητα 2: Σάρωση Νέων (3 τη φορά)
        elif new_files_ids:
            batch_size = 3
            to_process = new_files_ids[:batch_size]
            
            status_placeholder = st.empty()
            
            for fid in to_process:
                fname = drive_files_map[fid]
                status_placeholder.markdown(f"🔍 **Ανάλυση:** `{fname}`...")
                
                # Deep Scan Logic
                try:
                    tmp_path = download_temp(fid, fname)
                    model_info = identify_model_with_ai(tmp_path)
                    
                    # Ενημέρωση
                    st.session_state.master_index[fid] = {
                        "name": fname,
                        "model_info": model_info
                    }
                except Exception as e:
                    print(f"Error {fname}: {e}")
            
            # Save & Loop
            status_placeholder.text("💾 Αποθήκευση...")
            save_index(st.session_state.master_index)
            st.rerun()
            
        else:
            st.caption("Το σύστημα είναι πλήρως ενημερωμένο.")
            # Καθαρισμός snapshot για επόμενη φορά
            if "drive_snapshot" in st.session_state:
                del st.session_state.drive_snapshot

# --- MAIN APP ---
st.title("🤖 HVAC Smart Expert")

# Tabs για λειτουργίες
tab1, tab2 = st.tabs(["💬 Συνομιλία", "🗂️ Κατάσταση Βάσης"])

with tab2:
    idx_len = len(st.session_state.master_index)
    st.metric("Συνολικά Manuals στη Βάση", idx_len)
    st.caption("Η βάση περιέχει τα μοντέλα όπως αναγνωρίστηκαν από το AI.")
    with st.expander("Προβολή Δείγματος Βάσης"):
        st.json(dict(list(st.session_state.master_index.items())[:5]))

with tab1:
    c1, c2, c3 = st.columns(3)
    if "tech_mode" not in st.session_state: st.session_state.tech_mode = "Τεχνικός HVAC"
    if c1.button("❄️ AC"): st.session_state.tech_mode = "Τεχνικός Κλιματισμού"
    if c2.button("🧊 Ψύξη"): st.session_state.tech_mode = "Ψυκτικός"
    if c3.button("🔥 Αέριο"): st.session_state.tech_mode = "Τεχνικός Καυστήρων"

    # Search Logic
    def search_index(query):
        query = query.lower()
        matches = []
        for fid, data in st.session_state.master_index.items():
            full_text = (data['name'] + " " + data['model_info']).lower()
            if query in full_text or any(k in full_text for k in query.split() if len(k)>2):
                matches.append((fid, data))
        return matches[:1] # Επιστροφή του καλύτερου

    if "messages" not in st.session_state: st.session_state.messages = []
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    user_input = st.chat_input("Ερώτηση για βλάβη...")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)
        
        with st.chat_message("assistant"):
            # 1. Ψάξιμο
            found_data = None
            media_items = []
            
            if st.session_state.master_index:
                hits = search_index(user_input)
                if hits:
                    fid, data = hits[0]
                    found_data = f"{data['model_info']} ({data['name']})"
                    st.markdown(f'<div class="source-box">📖 Βρέθηκε: {found_data}</div>', unsafe_allow_html=True)
                    try:
                        path = download_temp(fid, data['name'])
                        gf = genai.upload_file(path)
                        while gf.state.name == "PROCESSING": time.sleep(0.5); gf = genai.get_file(gf.name)
                        media_items.append(gf)
                    except: pass
            
            # 2. Απάντηση
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = f"Είσαι {st.session_state.tech_mode}. Manual: {found_data or 'Όχι'}. Ερώτηση: {user_input}"
                resp = model.generate_content([prompt, *media_items])
                st.markdown(resp.text)
                st.session_state.messages.append({"role": "assistant", "content": resp.text})
            except Exception as e:
                st.error(f"Error: {e}")
