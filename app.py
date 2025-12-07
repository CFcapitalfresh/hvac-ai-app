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

# Προσπάθεια εισαγωγής PyPDF για ανάγνωση κειμένου (χωρίς AI για ταχύτητα)
try:
    import pypdf
except ImportError:
    pypdf = None

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Smart V7 Pro", page_icon="🧠", layout="centered")

# --- CSS ---
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    .source-box { background-color: #d1fae5; color: #065f46; padding: 10px; border-radius: 8px; border: 1px solid #34d399; margin-bottom: 10px;}
    .index-stat { font-size: 12px; color: #666; }
</style>""", unsafe_allow_html=True)

# --- GLOBAL VARS ---
INDEX_FILE_NAME = "hvac_smart_db.json"

# --- ΣΥΝΔΕΣΗ ---
auth_status = "⏳ ..."
drive_service = None
available_models = []

try:
    if "GEMINI_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name.replace("models/", ""))
        except: available_models = ["gemini-1.5-flash", "gemini-1.5-pro"]

    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        gcp_raw = st.secrets["GCP_SERVICE_ACCOUNT"].strip()
        if gcp_raw.startswith("'") and gcp_raw.endswith("'"): gcp_raw = gcp_raw[1:-1]
        info = json.loads(gcp_raw)
        if "private_key" in info: info["private_key"] = info["private_key"].replace("\\n", "\n")
        
        # --- ΠΡΟΣΟΧΗ: ΑΦΑΙΡΕΣΑΜΕ ΤΟ .readonly ΓΙΑ ΝΑ ΓΡΑΦΕΙ ΤΗ ΒΑΣΗ ---
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive'] 
        )
        drive_service = build('drive', 'v3', credentials=creds)
        auth_status = "✅ Συνδεδεμένο"
    else: auth_status = "⚠️ Χωρίς Drive"
except Exception as e: auth_status = f"⚠️ Error: {str(e)}"

# --- FUNCTIONS ---

def get_or_create_index():
    """Φορτώνει τη βάση δεδομένων από το Drive ή δημιουργεί κενή."""
    if not drive_service: return {}
    try:
        # Ψάχνουμε αν υπάρχει το αρχείο JSON
        q = f"name = '{INDEX_FILE_NAME}' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id, name)").execute()
        files = res.get('files', [])
        
        if files:
            file_id = files[0]['id']
            content = download_file_content(file_id)
            return json.loads(content.decode('utf-8')), file_id
        else:
            return {}, None
    except: return {}, None

def save_index_to_drive(index_data, file_id=None):
    """Αποθηκεύει τη βάση πίσω στο Drive."""
    if not drive_service: return
    
    json_str = json.dumps(index_data, ensure_ascii=False)
    fh = io.BytesIO(json_str.encode('utf-8'))
    media = MediaIoBaseUpload(fh, mimetype='application/json', resumable=True)
    
    if file_id:
        drive_service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {'name': INDEX_FILE_NAME, 'mimeType': 'application/json'}
        drive_service.files().create(body=file_metadata, media_body=media).execute()

def list_drive_files_all():
    """Φέρνει ΟΛΑ τα αρχεία (όχι μόνο 50) για το indexing."""
    if not drive_service: return []
    all_files = []
    page_token = None
    try:
        while True:
            q = "mimeType != 'application/vnd.google-apps.folder' and mimeType != 'application/json' and trashed = false"
            res = drive_service.files().list(q=q, fields="nextPageToken, files(id, name)", pageToken=page_token).execute()
            all_files.extend(res.get('files', []))
            page_token = res.get('nextPageToken', None)
            if page_token is None: break
        return all_files
    except: return []

def download_file_content(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    return fh.getvalue()

def extract_text_from_pdf_bytes(file_bytes):
    """Διαβάζει την 1η σελίδα του PDF για να βρει μοντέλα."""
    if not pypdf: return ""
    try:
        pdf_file = io.BytesIO(file_bytes)
        reader = pypdf.PdfReader(pdf_file)
        if len(reader.pages) > 0:
            return reader.pages[0].extract_text()
        return ""
    except: return ""

def smart_search(query, index_data, live_files):
    """Ψάχνει ΠΡΩΤΑ στο περιεχόμενο (index), ΜΕΤΑ στα ονόματα."""
    query = query.lower()
    keywords = [w for w in query.split() if len(w) > 2]
    best_match = None
    highest_score = 0
    
    # 1. Αναζήτηση στο Index (Περιεχόμενο)
    for file_id, data in index_data.items():
        score = 0
        content = (data.get('name', '') + " " + data.get('content', '')).lower()
        
        for k in keywords:
            if k in content: score += 3 # Μεγάλο βάρος αν βρεθεί στο περιεχόμενο
            
        if score > highest_score:
            highest_score = score
            best_match = {'id': file_id, 'name': data['name']}

    # 2. Αν δεν βρέθηκε καλό αποτέλεσμα στο Index, ψάξε στα ονόματα των Live Files (Fallback)
    if highest_score < 2: 
        for f in live_files:
            fname = f['name'].lower()
            score = 0
            for k in keywords:
                if k in fname: score += 2
                elif difflib.get_close_matches(k, fname.split(), cutoff=0.7): score += 1
            
            if score > highest_score:
                highest_score = score
                best_match = f
                
    return best_match

# --- SIDEBAR & INDEXING UI ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    st.info(auth_status)
    
    # ΕΠΙΛΟΓΗ ΜΟΝΤΕΛΟΥ
    if available_models:
        idx = 0
        if "gemini-1.5-flash" in available_models: idx = available_models.index("gemini-1.5-flash")
        model_option = st.selectbox("AI Model", available_models, index=idx)
    else: model_option = "gemini-1.5-flash"

    st.divider()
    
    # --- INDEX MANAGEMENT ---
    with st.expander("🗂️ Βάση Δεδομένων (Index)"):
        if drive_service:
            # Φόρτωση υπάρχουσας βάσης
            db, db_file_id = get_or_create_index()
            st.write(f"📁 Αρχεία στη βάση: **{len(db)}**")
            
            if st.button("🔄 Σάρωση Νέων Αρχείων (Batch)"):
                if not pypdf:
                    st.error("Λείπει η βιβλιοθήκη 'pypdf'.")
                else:
                    st.write("⏳ Σάρωση αρχείων στο Drive...")
                    all_files = list_drive_files_all()
                    
                    # Βρες ποια δεν έχουν σαρωθεί
                    files_to_scan = [f for f in all_files if f['id'] not in db and f['name'] != INDEX_FILE_NAME]
                    
                    if not files_to_scan:
                        st.success("✅ Όλα τα αρχεία είναι ενημερωμένα!")
                    else:
                        st.write(f"🔍 Βρέθηκαν {len(files_to_scan)} νέα αρχεία. Σαρώνω τα επόμενα 10...")
                        
                        progress_bar = st.progress(0)
                        
                        # Σαρώνουμε MONO 10 κάθε φορά για να μην κρασάρει
                        BATCH_SIZE = 10
                        count = 0
                        
                        for i, f in enumerate(files_to_scan[:BATCH_SIZE]):
                            try:
                                # Κατέβασμα & Ανάγνωση
                                b_data = download_file_content(f['id'])
                                extracted_text = ""
                                if f['name'].lower().endswith(".pdf"):
                                    extracted_text = extract_text_from_pdf_bytes(b_data)
                                
                                # Αποθήκευση στη μνήμη (μόνο τα πρώτα 500 γράμματα για οικονομία χώρου)
                                db[f['id']] = {
                                    'name': f['name'],
                                    'content': extracted_text[:1000] # Κρατάμε τα πρώτα 1000 γράμματα
                                }
                                count += 1
                                progress_bar.progress((i + 1) / BATCH_SIZE)
                            except Exception as e:
                                print(f"Error scanning {f['name']}: {e}")
                        
                        # Αποθήκευση στο Drive
                        st.write("💾 Αποθήκευση βάσης...")
                        save_index_to_drive(db, db_file_id)
                        st.success(f"✅ Προστέθηκαν {count} αρχεία! Ξαναπάτα το κουμπί για τα επόμενα.")
                        st.rerun()

    st.divider()
    if st.button("🗑️ Νέα Συζήτηση", type="primary"):
        st.session_state.messages = []
        st.rerun()

# --- MAIN APP ---
st.title("🧠 HVAC Smart Expert")
st.caption("v7.0 - Deep Content Search")

if "tech_mode" not in st.session_state: st.session_state.tech_mode = "Τεχνικός HVAC"
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC"): st.session_state.tech_mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη"): st.session_state.tech_mode = "Ψυκτικός"
if c3.button("🔥 Αέριο"): st.session_state.tech_mode = "Τεχνικός Καυστήρων"

prompt = st.chat_input("Γράψε βλάβη (π.χ. κωδικός 501)...")

# --- CHAT LOGIC ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        found_file = None
        media_content = []
        
        # 1. SMART SEARCH (Πρώτα στη βάση, μετά στο Drive)
        if drive_service:
            with st.spinner("🕵️ Αναζήτηση σε τίτλους ΚΑΙ περιεχόμενο..."):
                # Φόρτωσε τη βάση (γρήγορα, είναι ένα αρχείο)
                db_index, _ = get_or_create_index()
                
                # Αν η βάση είναι άδεια, φέρε λίστα αρχείων από Drive για απλή αναζήτηση
                live_files = []
                if not db_index:
                    live_files = list_drive_files_all() # Προσοχή: αυτό αργεί λίγο αν είναι 2000 αρχεία
                
                target = smart_search(prompt, db_index, live_files)
                
                if target:
                    st.markdown(f'<div class="source-box">📖 Βρέθηκε: {target["name"]}</div>', unsafe_allow_html=True)
                    try:
                        f_id = target['id']
                        file_data = download_file_content(f_id)
                        
                        suffix = ".pdf" if "pdf" in target['name'].lower() else ".jpg"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(file_data)
                            tmp_path = tmp.name
                        
                        gfile = genai.upload_file(tmp_path)
                        while gfile.state.name == "PROCESSING": time.sleep(1); gfile = genai.get_file(gfile.name)
                        media_content.append(gfile)
                        found_file = target['name']
                    except Exception as e:
                        st.error(f"Error: {e}")
                else:
                    st.warning("⚠️ Δεν βρέθηκε σχετικό manual.")

        # 2. AI GENERATION
        try:
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
            
            chat_history = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages[-6:]])
            src_instr = f"Έχεις το manual '{found_file}'." if found_file else "Δεν βρέθηκε manual."
            
            full_prompt = f"""
            Είσαι {st.session_state.tech_mode}.
            Ιστορικό: {chat_history}
            Οδηγία: {src_instr} Ανάλυσε το πρόβλημα. Αν υπάρχει manual, βρες τη λύση εκεί.
            Ερώτηση: {prompt}
            """
            
            model = genai.GenerativeModel(model_option)
            response = model.generate_content([full_prompt, *media_content], safety_settings=safety_settings)
            
            if response.candidates:
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            else:
                st.error("⚠️ Το AI δεν απάντησε (Block).")

        except Exception as e:
            st.error(f"Error: {e}")
