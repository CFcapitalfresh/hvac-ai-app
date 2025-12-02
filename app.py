import streamlit as st
import google.generativeai as genai
from PIL import Image

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(
    page_title="HVAC Expert",
    page_icon="🔥",
    layout="centered"
)

# --- CSS (Καθαρό στυλ) ---
st.markdown("""
    <style>
        .stChatMessage { border-radius: 12px; }
        /* Κάνε το κουμπί της κάμερας πιο ωραίο */
        div[data-testid="stCameraInput"] { border-radius: 15px; overflow: hidden; }
        /* Κρύψε το footer */
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- ΤΙΤΛΟΣ ---
st.title("🔧 HVAC Expert")

# --- ΡΥΘΜΙΣΕΙΣ (ΤΩΡΑ ΣΤΗΝ ΚΕΝΤΡΙΚΗ ΟΘΟΝΗ) ---
# Αντί για Sidebar, το βάζουμε εδώ για να το βρίσκεις εύκολα
with st.expander("🔐 Ρυθμίσεις & API Key (Πάτα εδώ)", expanded=False):
    st.caption("Ρύθμισε τη σύνδεση με το AI")
    
    # API Key Input
    # Χρησιμοποιούμε session_state για να μην χάνεται το κλειδί όταν πατάς άλλα κουμπιά
    if "api_key" not in st.session_state:
        st.session_state.api_key = ""
        
    user_key = st.text_input("🔑 Google API Key", value=st.session_state.api_key, type="password", placeholder="AIzaSy...")
    
    if user_key:
        st.session_state.api_key = user_key
        genai.configure(api_key=user_key)
        st.success("✅ Το σύστημα συνδέθηκε!")
    
    st.divider()
    model_option = st.selectbox("Επιλογή Μοντέλου", ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"])

# --- ΕΛΕΓΧΟΣ ΑΝ ΛΕΙΠΕΙ ΤΟ ΚΛΕΙΔΙ ---
if not st.session_state.api_key:
    st.warning("☝️ Για να ξεκινήσεις, πάτα το κουμπί **'🔐 Ρυθμίσεις'** από πάνω και βάλε τον κωδικό σου.")
    st.stop() # Σταματάει εδώ μέχρι να μπει το κλειδί

# --- ΕΠΙΛΟΓΗ ΛΕΙΤΟΥΡΓΙΑΣ ---
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("❄️ AC", use_container_width=True): st.session_state.current_mode = "Τεχνικός Κλιματισμού (Split/VRV)"
with col2:
    if st.button("🧊 Ψύξη", use_container_width=True): st.session_state.current_mode = "Ψυκτικός (Βιομηχανική Ψύξη)"
with col3:
    if st.button("🔥 Αέριο", use_container_width=True): st.session_state.current_mode = "Τεχνικός Καυστήρων Αερίου"

# Default Mode
if "current_mode" not in st.session_state:
    st.session_state.current_mode = "Τεχνικός HVAC"

st.caption(f"Λειτουργία: **{st.session_state.current_mode}**")

# --- CHAT HISTORY ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Εμφάνιση μηνυμάτων
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- AI LOGIC ---
def get_gemini_response(prompt, images=None):
    try:
        model = genai.GenerativeModel(model_option)
        content = [prompt]
        if images:
            for img in images:
                content.append(img)
        response = model.generate_content(content)
        return response.text
    except Exception as e:
        return f"❌ Σφάλμα: {str(e)}"

# --- INPUT TOOLS (CAMERA & TEXT) ---

# Tabs για Κάμερα/Αρχεία
tab_cam, tab_file = st.tabs(["📸 Κάμερα", "📂 Αρχεία"])

with tab_cam:
    camera_img = st.camera_input("Λήψη φωτογραφίας", label_visibility="collapsed")

with tab_file:
    uploaded_files = st.file_uploader("Επιλογή αρχείων", accept_multiple_files=True, type=['pdf', 'jpg', 'png'], label_visibility="collapsed")

# Text Input
prompt = st.chat_input("Γράψε τη βλάβη...")

# --- PROCESSING ---
if prompt:
    # 1. User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Context
    full_prompt = f"Είσαι {st.session_state.current_mode}. Απάντησε τεχνικά και σύντομα στα Ελληνικά.\nΕρώτηση: {prompt}"

    # 3. Handle Images
    image_parts = []
    
    # Από Κάμερα
    if camera_img:
        img = Image.open(camera_img)
        image_parts.append(img)
        
    # Από Αρχεία
    if uploaded_files:
        for uploaded_file in uploaded_files:
            if uploaded_file.type.startswith('image'):
                image = Image.open(uploaded_file)
                image_parts.append(image)

    # 4. Generate Response
    with st.chat_message("assistant"):
        with st.spinner("🔍 Ανάλυση..."):
            response = get_gemini_response(full_prompt, image_parts)
            st.markdown(response)
            
    st.session_state.messages.append({"role": "assistant", "content": response})
