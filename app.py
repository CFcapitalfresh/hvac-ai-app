import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os
import time

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(
    page_title="HVAC Expert",
    page_icon="🔧",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CSS (Απόκρυψη περιττών στοιχείων) ---
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stDeployButton {display:none;}
        .stChatMessage { border-radius: 12px; }
        div[data-testid="stCameraInput"] button {
            background-color: #ef4444; color: white; border: none;
        }
        /* Κρύβουμε το κενό που άφηνε το μήνυμα της κάμερας */
        div.stAlert { display: none; }
    </style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Ρυθμίσεις")
    api_key = st.text_input("🔑 API Key", type="password", placeholder="Κωδικός...")
    if api_key:
        genai.configure(api_key=api_key)
        st.success("Συνδέθηκε!")
    
    st.divider()
    # Προεπιλογή το Flash για ταχύτητα
    model_option = st.selectbox("Μοντέλο", ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"])

# --- HEADER ---
st.title("🔧 HVAC Expert")

if not api_key:
    st.warning("⬅️ **Πάτα το βελάκι πάνω αριστερά (>)** για να βάλεις κωδικό!")
    st.stop()

# --- ΕΙΔΙΚΟΤΗΤΑ ---
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
with col2:
    if st.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
with col3:
    if st.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"

st.caption(f"Ειδικότητα: **{st.session_state.mode}**")

# --- MEDIA AREA ---
with st.container():
    tab1, tab2 = st.tabs(["📸 Live Φώτο", "📂 Αρχεία"])
    
    with tab1:
        # Checkbox για κάμερα - ΧΩΡΙΣ μήνυμα όταν είναι κλειστό
        enable_cam = st.checkbox("Ενεργοποίηση Κάμερας")
        camera_img = None
        if enable_cam:
            camera_img = st.camera_input("Λήψη")
    
    with tab2:
        uploaded_files = st.file_uploader(
            "Επιλογή αρχείων", 
            accept_multiple_files=True, 
            type=['jpg', 'png', 'jpeg', 'pdf', 'mp4', 'mov']
        )

# --- ΙΣΤΟΡΙΚΟ ---
if "messages" not in st.session_state: st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- ΕΠΕΞΕΡΓΑΣΙΑ ΑΡΧΕΙΩΝ ---
def process_file(uploaded_file):
    try:
        suffix = f".{uploaded_file.name.split('.')[-1]}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        mime_type = uploaded_file.type
        
        # Βίντεο ή PDF
        if "video" in mime_type or "pdf" in mime_type:
            with st.spinner(f"📤 Ανεβάζω {uploaded_file.name}..."):
                myfile = genai.upload_file(tmp_path, mime_type=mime_type)
            
            if "video" in mime_type:
                with st.spinner("⏳ Επεξεργασία βίντεο..."):
                    # Wait loop με όριο 60 δευτερόλεπτα
                    elapsed = 0
                    while myfile.state.name == "PROCESSING":
                        time.sleep(2)
                        elapsed += 2
                        myfile = genai.get_file(myfile.name)
                        if elapsed > 60:
                            raise TimeoutError("Το βίντεο αργεί πολύ.")
                    if myfile.state.name == "FAILED":
                        raise ValueError("Η επεξεργασία απέτυχε.")
            return myfile

        # Εικόνα
        elif "image" in mime_type:
            return Image.open(tmp_path)

    except Exception as e:
        st.error(f"Σφάλμα αρχείου: {e}")
        return None
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)

# --- CHAT INPUT ---
prompt = st.chat_input("Γράψε εδώ...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    media_items = []
    
    # 1. Από Κάμερα
    if enable_cam and camera_img:
        media_items.append(Image.open(camera_img))
        
    # 2. Από Uploads
    if uploaded_files:
        for f in uploaded_files:
            processed = process_file(f)
            if processed:
                media_items.append(processed)

    # 3. Απάντηση AI
    with st.chat_message("assistant"):
        with st.spinner("⚡ Γρήγορη ανάλυση..."):
            try:
                # Χρησιμοποιούμε το επιλεγμένο μοντέλο
                model = genai.GenerativeModel(st.session_state.get('model_option', 'gemini-2.0-flash'))
                
                msg_content = [f"Είσαι {st.session_state.mode}. Απάντησε σύντομα και τεχνικά στα Ελληνικά.\nΕρώτηση: {prompt}"]
                msg_content.extend(media_items)
                
                # Timeout safety (αν και το Streamlit δεν έχει native timeout, το Gemini συνήθως απαντάει γρήγορα)
                response = model.generate_content(msg_content)
                
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            
            except Exception as e:
                st.error("⚠️ Υπήρξε καθυστέρηση ή σφάλμα σύνδεσης. Πάτα ξανά αποστολή.")
                # Δεν τυπώνουμε όλο το κατεβατό λάθους για να μην τρομάζει ο χρήστης, εκτός αν θες debugging.
