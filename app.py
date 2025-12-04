
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
st.set_page_config(page_title="HVAC Auto-Expert", page_icon="🔧", layout="centered")
st.markdown("""<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display:none;}
    div[data-testid="stCameraInput"] button {background-color: #ef4444; color: white;}
    .stChatMessage { border-radius: 12px; background-color: #1e293b; color: #e2e8f0; }
    div.stToast { background-color: #22c55e; color: white; }
</style>""", unsafe_allow_html=True)

# --- ΣΥΝΔΕΣΗ ---
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
except Exception as e:
    st.error(f"Σφάλμα Σύνδεσης: {e}")

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Ρυθμίσεις")
    if drive_service: st.success("✅ Drive: Συνδεδεμένο")
    else: st.error("❌ Drive: Αποσυνδεδεμένο")
    
    st.divider()
    model_option = st.selectbox("Μοντέλο", ["gemini-1.5-flash", "gemini-1.5-pro"])
    if st.button("🗑️ Καθαρισμός"):
        st.session_state.messages = []
        st.rerun()

# --- HEADER ---
st.title("🔧 HVAC Auto-Select")

# --- FUNCTIONS ---
def list_drive_files():
    if not drive_service: return []
    try:
        # Φέρνουμε ΟΛΑ τα αρχεία (μέχρι 100) για να ψάξουμε
        q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        res = drive_service.files().list(q=q, fields="files(id, name, mimeType)", pageSize=100).execute()
        return res.get('files', [])
    except: return []

def find_best_match(query, files):
    """Βρίσκει το αρχείο που ταιριάζει περισσότερο στην ερώτηση"""
    query_words = query.lower().split()
    best_file = None
    max_matches = 0
    
    for f in files:
        fname = f['name'].lower()
        matches = sum(1 for word in query_words if word in fname and len(word) > 2) # Αγνοούμε μικρές λέξεις
        
        if matches > max_matches:
            max_matches = matches
            best_file = f
    
    return best_file

def download_drive_file(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

# --- CHAT ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- INPUT ---
prompt = st.chat_input("Περιέγραψε τη βλάβη (π.χ. Ariston 501)...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    media = []
    source_info = ""
    
    # 1. Αυτόματη Αναζήτηση στο Drive
    if drive_service:
        with st.spinner("🔎 Ψάχνω στα αρχεία σου..."):
            all_files = list_drive_files()
            matched_file = find_best_match(prompt, all_files)
            
            if matched_file:
                st.toast(f"📖 Βρήκα: {matched_file['name']}", icon="📂")
                source_info = f" [Ανάλυση βάσει αρχείου: {matched_file['name']}]"
                
                try:
                    stream = download_drive_file(matched_file['id'])
                    suffix = ".pdf" if "pdf" in matched_file['name'].lower() else ".jpg"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(stream.getvalue())
                        path = tmp.name
                    
                    gfile = genai.upload_file(path)
                    while gfile.state.name == "PROCESSING": time.sleep(1); gfile = genai.get_file(gfile.name)
                    media.append(gfile)
                except Exception as e:
                    st.error(f"Σφάλμα ανάγνωσης αρχείου: {e}")
            else:
                st.toast("Δεν βρέθηκε συγκεκριμένο αρχείο. Απαντώ γενικά.", icon="🧠")

    # 2. AI Reply
    with st.chat_message("assistant"):
        with st.spinner("🧠 Ανάλυση..."):
            try:
                model = genai.GenerativeModel(model_option)
                full_prompt = f"Είσαι έμπειρος τεχνικός. Απάντησε στα Ελληνικά.{source_info}\nΕρώτηση: {prompt}"
                
                response = model.generate_content([full_prompt, *media])
                
                # Προσθήκη της πηγής στο τέλος
                final_text = response.text
                if matched_file:
                    final_text += f"\n\n--- \n📂 **Πηγή:** {matched_file['name']}"
                else:
                    final_text += "\n\n--- \n🧠 **Πηγή:** Γενική Γνώση AI"

                st.markdown(final_text)
                st.session_state.messages.append({"role": "assistant", "content": final_text})
            except Exception as e:
                st.error(f"Σφάλμα AI: {str(e)}")
