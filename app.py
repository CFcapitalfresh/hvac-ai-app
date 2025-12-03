import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os
import time

# --- ΡΥΘΜΙΣΕΙΣ ---
st.set_page_config(page_title="HVAC Pro", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

# --- CSS (Minimal) ---
st.markdown("""<style>
    #MainMenu, footer, .stDeployButton {visibility: hidden;}
    .stChatMessage { border-radius: 12px; }
    div[data-testid="stCameraInput"] button { background-color: #ef4444; color: white; border: none; }
</style>""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Setup")
    api_key = st.text_input("API Key", type="password")
    if api_key: genai.configure(api_key=api_key)
    st.divider()
    model_opt = st.selectbox("Model", ["gemini-2.0-flash", "gemini-1.5-flash"])
    if st.button("🗑️ Καθαρισμός Ιστορικού"): 
        st.session_state.messages = []
        st.rerun()

# --- HEADER ---
st.title("⚡ HVAC Pro")
if not api_key:
    st.warning("⬅️ Πάτα το βελάκι πάνω αριστερά για κωδικό!")
    st.stop()

# --- MODES ---
if "mode" not in st.session_state: st.session_state.mode = "HVAC Tech"
c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.mode = "Τεχνικός AC"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.mode = "Τεχνικός Καυστήρων"

# --- MEDIA ---
with st.expander("📸 Κάμερα & Αρχεία", expanded=False):
    tab1, tab2 = st.tabs(["Live", "Upload"])
    with tab1:
        enable_cam = st.checkbox("On/Off")
        cam_img = st.camera_input("Λήψη") if enable_cam else None
    with tab2:
        upl_file = st.file_uploader("Επιλογή", type=['jpg','png','pdf','mp4'])

# --- CHAT ---
if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

# --- PROCESS ---
def process_media(file):
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file.name.split('.')[-1]}") as tmp:
        tmp.write(file.getvalue())
        path = tmp.name
    
    if "video" in file.type or "pdf" in file.type:
        f = genai.upload_file(path, mime_type=file.type)
        while f.state.name == "PROCESSING": time.sleep(1); f = genai.get_file(f.name)
        return f
    return Image.open(path) # Images

# --- INPUT ---
prompt = st.chat_input("Ερώτηση...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    media = []
    if cam_img: media.append(Image.open(cam_img))
    if upl_file: media.append(process_media(upl_file))

    with st.chat_message("assistant"):
        # STREAMING RESPONSE (Γράφει λέξη-λέξη)
        model = genai.GenerativeModel(model_opt)
        try:
            stream = model.generate_content([f"Είσαι {st.session_state.mode}. Ελληνικά.\n{prompt}", *media], stream=True)
            response = st.write_stream(stream)
            st.session_state.messages.append({"role": "assistant", "content": response})
        except Exception as e:
            st.error("⚠️ Σφάλμα σύνδεσης. Δοκίμασε ξανά.")
