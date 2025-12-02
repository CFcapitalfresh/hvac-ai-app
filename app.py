import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os
import time

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ (MOBILE OPTIMIZED) ---
st.set_page_config(
    page_title="HVAC AI",
    page_icon="🔧",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CSS (ΓΙΑ ΝΑ ΚΡΥΨΟΥΜΕ ΤΑ LOGO & ΝΑ ΟΜΟΡΦΥΝΟΥΜΕ ΤΟ MOBILE) ---
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stDeployButton {display:none;}
        
        /* Στρογγυλεμένα κουμπιά */
        .stButton>button {
            border-radius: 12px;
            height: 3em;
            font-weight: bold;
        }
        /* Κουτί Chat */
        .stChatMessage { 
            border-radius: 15px; 
            padding: 10px; 
            background-color: #1e293b; 
        }
    </style>
""", unsafe_allow_html=True)

# --- ΤΙΤΛΟΣ ---
st.title("🔧 HVAC Expert")

# --- ΔΙΑΧΕΙΡΙΣΗ ΚΛΕΙΔΙΟΥ (ΣΤΗΝ ΚΕΝΤΡΙΚΗ ΟΘΟΝΗ) ---
if "api_key" not in st.session_state:
    st.session_state.api_key = ""

# Αν δεν υπάρχει κλειδί, εμφάνισε το κουτί εισαγωγής ΕΔΩ (όχι στο sidebar)
if not st.session_state.api_key:
    with st.container():
        st.warning("🔒 Το σύστημα είναι κλειδωμένο.")
        input_key = st.text_input("Βάλε το Gemini API Key για να ξεκινήσεις:", type="password")
        if input_key:
            st.session_state.api_key = input_key
            st.rerun() # Επανεκκίνηση για να κρύψει το κουτί
        st.stop() # Σταματάει εδώ μέχρι να μπει κλειδί

# Ρύθμιση Google AI
genai.configure(api_key=st.session_state.api_key)

# --- ΕΠΙΛΟΓΗ ΛΕΙΤΟΥΡΓΙΑΣ (ΜΕΓΑΛΑ ΚΟΥΜΠΙΑ) ---
if "mode" not in st.session_state: st.session_state.mode = "Τεχνικός HVAC"

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός Κλιματισμού"
with col2:
    if st.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
with col3:
    if st.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"

st.info(f"Λειτουργία: **{st.session_state.mode}**")

# --- MEDIA AREA (ΚΑΜΕΡΑ & UPLOAD) ---
with st.expander("📸 Προσθήκη Εικόνας/Βίντεο (Πάτα εδώ)", expanded=False):
    tab1, tab2 = st.tabs(["🔴 Live Κάμερα", "📂 Ανέβασμα"])
    
    with tab1:
        camera_img = st.camera_input("Βγάλε φώτο τώρα")
    
    with tab2:
        uploaded_files = st.file_uploader(
            "Επέλεξε αρχεία από το κινητό", 
            accept_multiple_files=True, 
            type=['jpg', 'png', 'jpeg', 'pdf', 'mp4', 'mov']
        )

# --- ΙΣΤΟΡΙΚΟ CHAT ---
if "messages" not in st.session_state: st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- ΕΠΕΞΕΡΓΑΣΙΑ ΑΡΧΕΙΩΝ ---
def process_media(files, cam_img):
    media_items = []
    
    # 1. Από Κάμερα
    if cam_img:
        media_items.append(Image.open(cam_img))
    
    # 2. Από Uploads
    if files:
        for f in files:
            # Σώσιμο προσωρινά
            suffix = f".{f.name.split('.')[-1]}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(f.getvalue())
                tmp_path = tmp.name
            
            mime_type = f.type
            
            # Αν είναι Βίντεο ή PDF (θέλει upload στο cloud της Google)
            if "video" in mime_type or "pdf" in mime_type:
                with st.spinner(f"Ανεβάζω {f.name}..."):
                    myfile = genai.upload_file(tmp_path, mime_type=mime_type)
                    
                    # Αναμονή για βίντεο
                    if "video" in mime_type:
                        while myfile.state.name == "PROCESSING":
                            time.sleep(1)
                            myfile = genai.get_file(myfile.name)
                media_items.append(myfile)
            
            # Αν είναι Εικόνα (το ανοίγουμε απευθείας)
            elif "image" in mime_type:
                media_items.append(Image.open(tmp_path))
                
            # Καθαρισμός
            if os.path.exists(tmp_path): os.remove(tmp_path)
            
    return media_items

# --- INPUT ΧΡΗΣΤΗ ---
prompt = st.chat_input("Γράψε τη βλάβη εδώ...")

if prompt:
    # Εμφάνιση ερώτησης
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Επεξεργασία Πολυμέσων
    media_content = process_media(uploaded_files, camera_img)
    
    if media_content:
        st.toast(f"📎 Επισυνάφθηκαν {len(media_content)} αρχεία")

    # Κλήση στο AI
    with st.chat_message("assistant"):
        with st.spinner("🧠 Σκέφτεται..."):
            try:
                # Δοκιμή μοντέλων αυτόματα (Auto-Fallback)
                model_name = "gemini-2.0-flash" 
                model = genai.GenerativeModel(model_name)
                
                # Δημιουργία μηνύματος
                content_parts = [f"Είσαι {st.session_state.mode}. Απάντησε τεχνικά στα Ελληνικά.\nΕρώτηση: {prompt}"]
                content_parts.extend(media_content)
                
                response = model.generate_content(content_parts)
                st.markdown(response.text)
                
                st.session_state.messages.append({"role": "assistant", "content": response.text})
                
            except Exception as e:
                st.error(f"❌ Σφάλμα: {str(e)}")
                st.info("Δοκίμασε να ανεβάσεις μικρότερο αρχείο ή έλεγξε το κλειδί σου.")
