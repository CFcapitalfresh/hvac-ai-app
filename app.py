import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os
import time

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(
    page_title="HVAC Expert Pro",
    page_icon="🔧",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CSS (Καθαρή Εμφάνιση) ---
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stDeployButton {display:none;}
        .stChatMessage { border-radius: 12px; }
        /* Κουμπί Κάμερας */
        div[data-testid="stCameraInput"] button {
            background-color: #ef4444; color: white; border: none;
        }
    </style>
""", unsafe_allow_html=True)

# --- SIDEBAR (Ρυθμίσεις) ---
with st.sidebar:
    st.title("⚙️ Ρυθμίσεις")
    api_key = st.text_input("🔑 API Key", type="password", placeholder="Κωδικός εδώ...")
    if api_key:
        genai.configure(api_key=api_key)
        st.success("Συνδέθηκε!")
    
    st.divider()
    model_option = st.selectbox("Μοντέλο AI", ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"])
    st.caption("v3.0 Media Edition")

# --- MAIN HEADER ---
st.title("🔧 HVAC Expert")

if not api_key:
    st.warning("⬅️ **Πάτα το βελάκι πάνω αριστερά (>)** για να βάλεις κωδικό!")
    st.stop()

# --- ΕΠΙΛΟΓΗ ΕΙΔΙΚΟΤΗΤΑΣ ---
col1, col2, col3 = st.columns(3)
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

with col1:
    if st.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
with col2:
    if st.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
with col3:
    if st.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"

st.caption(f"Ειδικότητα: **{st.session_state.mode}**")

# --- ΠΕΡΙΟΧΗ ΠΟΛΥΜΕΣΩΝ (CAMERA & UPLOAD) ---
with st.container():
    # Tab 1: Live Photo
    # Tab 2: Upload (Video/Photo/PDF)
    tab1, tab2 = st.tabs(["📸 Live Φώτο", "📂 Ανέβασμα (Video/Files)"])
    
    with tab1:
        camera_img = st.camera_input("Τράβα φωτογραφία τώρα")
    
    with tab2:
        uploaded_files = st.file_uploader(
            "Επέλεξε από το κινητό (Βίντεο, Εικόνες, PDF)", 
            accept_multiple_files=True, 
            type=['jpg', 'png', 'jpeg', 'pdf', 'mp4', 'mov', 'avi']
        )

# --- ΙΣΤΟΡΙΚΟ CHAT ---
if "messages" not in st.session_state: st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- ΛΕΙΤΟΥΡΓΙΑ ΕΠΕΞΕΡΓΑΣΙΑΣ ΑΡΧΕΙΩΝ (Heavy Lifting) ---
def process_file_for_gemini(uploaded_file):
    """Ετοιμάζει το αρχείο (Βίντεο/PDF/Εικόνα) για το Gemini"""
    try:
        # 1. Σώσιμο προσωρινού αρχείου στον δίσκο (απαραίτητο για βίντεο)
        suffix = f".{uploaded_file.name.split('.')[-1]}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        # 2. ΑΝ ΕΙΝΑΙ ΒΙΝΤΕΟ Ή PDF (Θέλει Upload API)
        mime_type = uploaded_file.type
        if "video" in mime_type or "pdf" in mime_type:
            with st.spinner(f"📤 Ανεβάζω {uploaded_file.name}..."):
                myfile = genai.upload_file(tmp_path, mime_type=mime_type)
            
            # Αν είναι βίντεο, περιμένουμε να γίνει process
            if "video" in mime_type:
                with st.spinner("⏳ Επεξεργασία βίντεο από Google..."):
                    while myfile.state.name == "PROCESSING":
                        time.sleep(2)
                        myfile = genai.get_file(myfile.name)
                    if myfile.state.name == "FAILED":
                        raise ValueError("Η επεξεργασία απέτυχε.")
            return myfile

        # 3. ΑΝ ΕΙΝΑΙ ΕΙΚΟΝΑ (Απευθείας άνοιγμα)
        elif "image" in mime_type:
            return Image.open(tmp_path)

    except Exception as e:
        st.error(f"Σφάλμα αρχείου: {e}")
        return None
    finally:
        # Σβήσιμο προσωρινού αρχείου για να μην γεμίζει ο δίσκος
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)

# --- INPUT & RESPONSE ---
prompt = st.chat_input("Περιέγραψε το πρόβλημα...")

if prompt:
    # 1. Εμφάνιση ερώτησης
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Συλλογή Δεδομένων (Media)
    media_items = []
    
    # Από Κάμερα
    if camera_img:
        media_items.append(Image.open(camera_img))
        st.toast("📎 Προστέθηκε Live Φωτογραφία")

    # Από Uploads (Βίντεο/PDF/Gallery)
    if uploaded_files:
        for f in uploaded_files:
            processed = process_file_for_gemini(f)
            if processed:
                media_items.append(processed)
                st.toast(f"📎 Προστέθηκε: {f.name}")

    # 3. Κλήση στο AI
    with st.chat_message("assistant"):
        with st.spinner("🧠 Ο Τεχνικός σκέφτεται..."):
            try:
                model = genai.GenerativeModel(st.session_state.get('model_option', 'gemini-2.0-flash'))
                
                # Φτιάχνουμε το μήνυμα
                msg_content = [f"Είσαι {st.session_state.mode}. Απάντησε τεχνικά στα Ελληνικά.\nΕρώτηση: {prompt}"]
                msg_content.extend(media_items) # Προσθέτουμε τα αρχεία
                
                response = model.generate_content(msg_content)
                st.markdown(response.text)
                
                # Αποθήκευση απάντησης
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            
            except Exception as e:
                st.error(f"❌ Σφάλμα: {str(e)}")
