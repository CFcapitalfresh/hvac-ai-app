import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os
import time

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Expert v3", page_icon="🔥", layout="centered")

# --- CSS STYLING ---
st.markdown("""
    <style>
        .stChatMessage { border-radius: 12px; }
        div[data-testid="stCameraInput"] { border-radius: 15px; overflow: hidden; }
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- ΤΙΤΛΟΣ ---
st.title("🔧 HVAC Expert (Video AI)")

# --- ΑΥΤΟΜΑΤΗ ΣΥΝΔΕΣΗ (SECRETS) ---
# Ψάχνουμε αν υπάρχει το κλειδί στα "Secrets" του Streamlit Cloud
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
    # Δεν δείχνουμε τίποτα, συνδέεται σιωπηλά και γρήγορα
else:
    # Αν δεν υπάρχει στα Secrets, ζητάμε από τον χρήστη (Fall back)
    with st.expander("🔐 Ρυθμίσεις (Αν δεν έχεις βάλει Secrets)", expanded=True):
        api_key = st.text_input("API Key", type="password")
        if api_key:
            genai.configure(api_key=api_key)

if not api_key:
    st.warning("⚠️ Δεν βρέθηκε κλειδί. Ρύθμισέ το στα Secrets ή βάλε το παραπάνω.")
    st.stop()

# --- ΕΠΙΛΟΓΗ ΛΕΙΤΟΥΡΓΙΑΣ ---
if "current_mode" not in st.session_state:
    st.session_state.current_mode = "Τεχνικός HVAC"

c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.current_mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.current_mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.current_mode = "Τεχνικός Καυστήρων"

st.caption(f"Mode: **{st.session_state.current_mode}**")

# --- CHAT HISTORY ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- AI LOGIC (PHOTO & VIDEO) ---
def process_ai_request(prompt, media_files):
    model = genai.GenerativeModel("gemini-1.5-flash") # Το Flash είναι το καλύτερο για βίντεο
    content = [prompt]
    
    for file in media_files:
        # Αν είναι εικόνα
        if file["type"] == "image":
            content.append(file["data"])
        # Αν είναι βίντεο (θέλει ειδική διαδικασία)
        elif file["type"] == "video":
            with st.spinner("📤 Ανεβάζω το βίντεο στο AI..."):
                video_file = genai.upload_file(path=file["path"])
                
            # Περιμένουμε να το επεξεργαστεί η Google
            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = genai.get_file(video_file.name)
            
            if video_file.state.name == "FAILED":
                return "❌ Το βίντεο απέτυχε να αναλυθεί."
                
            content.append(video_file)
            
    try:
        response = model.generate_content(content)
        return response.text
    except Exception as e:
        return f"❌ Error: {str(e)}"

# --- INPUT AREA (TABS) ---
tab_photo, tab_video, tab_files = st.tabs(["📸 Φώτο (Live)", "📹 Βίντεο", "📂 Αρχεία"])

media_to_send = []

with tab_photo:
    cam_img = st.camera_input("Λήψη", label_visibility="collapsed")
    if cam_img:
        img = Image.open(cam_img)
        media_to_send.append({"type": "image", "data": img})

with tab_video:
    # Το Streamlit δεν έχει "Live Cam Video" ακόμα, αλλά το uploader ανοίγει την κάμερα βίντεο στο κινητό!
    uploaded_video = st.file_uploader("Εγγραφή/Επιλογή Βίντεο", type=['mp4', 'mov', 'avi'])
    if uploaded_video:
        # Σώζουμε το βίντεο προσωρινά για να το στείλουμε
        tfile = tempfile.NamedTemporaryFile(delete=False) 
        tfile.write(uploaded_video.read())
        media_to_send.append({"type": "video", "path": tfile.name})
        st.video(uploaded_video) # Preview

with tab_files:
    uploaded_doc = st.file_uploader("PDF ή Εικόνες", type=['pdf', 'jpg', 'png'], accept_multiple_files=True)
    if uploaded_doc:
        for f in uploaded_doc:
            if f.type.startswith('image'):
                media_to_send.append({"type": "image", "data": Image.open(f)})
            # Σημείωση: Για PDF χρειάζεται extra κώδικας, εδώ εστιάζουμε σε Media

prompt = st.chat_input("Γράψε τη βλάβη...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    sys = f"Είσαι {st.session_state.current_mode}. Ανάλυσε τα δεδομένα (εικόνα/βίντεο) και απάντησε τεχνικά."
    full_prompt = f"{sys}\nΕρώτηση: {prompt}"

    with st.chat_message("assistant"):
        with st.spinner("🧠 Το AI μελετάει το βίντεο/φώτο..."):
            reply = process_ai_request(full_prompt, media_to_send)
            st.markdown(reply)
            
    st.session_state.messages.append({"role": "assistant", "content": reply})
