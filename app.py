import streamlit as st
import google.generativeai as genai
from PIL import Image
import time

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Expert v4", page_icon="🔧", layout="centered")

# --- CSS STYLING ---
st.markdown("""
    <style>
        .stChatMessage { border-radius: 12px; }
        /* Κρύβουμε τα μενού για να μοιάζει με App */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* Μεγαλύτερα κουμπιά για εύκολο πάτημα */
        .stButton>button { height: 3em; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- ΤΙΤΛΟΣ ---
st.title("🔧 HVAC Expert")

# --- ΑΥΤΟΜΑΤΗ ΣΥΝΔΕΣΗ (SECRETS) ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
else:
    with st.expander("🔐 Ρυθμίσεις (Αν δεν έχεις βάλει Secrets)", expanded=True):
        api_key = st.text_input("API Key", type="password")
        if api_key:
            genai.configure(api_key=api_key)

if not api_key:
    st.warning("⚠️ Λείπει το κλειδί API.")
    st.stop()

# --- ΕΠΙΛΟΓΗ ΛΕΙΤΟΥΡΓΙΑΣ ---
if "current_mode" not in st.session_state:
    st.session_state.current_mode = "Τεχνικός HVAC"

c1, c2, c3 = st.columns(3)
if c1.button("❄️ AC", use_container_width=True): st.session_state.current_mode = "Τεχνικός Κλιματισμού"
if c2.button("🧊 Ψύξη", use_container_width=True): st.session_state.current_mode = "Ψυκτικός"
if c3.button("🔥 Αέριο", use_container_width=True): st.session_state.current_mode = "Τεχνικός Καυστήρων"

st.caption(f"Mode: **{st.session_state.current_mode}**")

# --- AI LOGIC (ΕΞΥΠΝΗ ΕΠΕΞΕΡΓΑΣΙΑ) ---
def process_request(prompt, media_files):
    # Χρησιμοποιούμε το Flash γιατί είναι το μόνο που βλέπει βίντεο γρήγορα
    model = genai.GenerativeModel("gemini-1.5-flash")
    content = [prompt]
    
    # Διαχείριση αρχείων
    for file in media_files:
        if file["type"] == "image":
            content.append(file["data"])
            
        elif file["type"] == "video":
            # 1. Ανέβασμα στην Google
            with st.spinner("📤 Ανεβάζω το βίντεο..."):
                video_file = genai.upload_file(path=file["path"], mime_type="video/mp4")
            
            # 2. Αναμονή για επεξεργασία (ΕΔΩ ΚΟΛΛΟΥΣΕ ΠΡΙΝ)
            with st.spinner("🔄 Η Google επεξεργάζεται το βίντεο..."):
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
        return f"❌ Σφάλμα AI: {str(e)}"

# --- CHAT HISTORY ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- INPUT AREA (ΤΑ ΝΕΑ TABS) ---
# Σειρά: Βίντεο -> Φώτο -> Αρχεία
tab_video, tab_photo, tab_files = st.tabs(["📹 Live Video", "📸 Live Φώτο", "📂 Αρχεία"])

media_to_send = []

# 1. LIVE VIDEO TAB
with tab_video:
    st.info("💡 Πάτα 'Browse files' και μετά επίλεξε **'Κάμερα/Camcorder'** για εγγραφή τώρα.")
    live_video = st.file_uploader("Εγγραφή Βίντεο", type=['mp4', 'mov', 'avi'], label_visibility="collapsed", key="vid_uploader")
    if live_video:
        # Αποθήκευση προσωρινού αρχείου για να το στείλουμε
        import tempfile
        tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") 
        tfile.write(live_video.read())
        media_to_send.append({"type": "video", "path": tfile.name})
        st.success("✅ Το βίντεο είναι έτοιμο για αποστολή!")

# 2. LIVE PHOTO TAB
with tab_photo:
    cam_img = st.camera_input("Λήψη Φωτογραφίας", label_visibility="collapsed")
    if cam_img:
        img = Image.open(cam_img)
        media_to_send.append({"type": "image", "data": img})
        st.success("✅ Η φωτογραφία λήφθηκε!")

# 3. GALLERY TAB
with tab_files:
    uploaded_docs = st.file_uploader("Επιλογή από Γκαλερί (Φώτο/PDF)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True, key="file_uploader")
    if uploaded_docs:
        for f in uploaded_docs:
            img = Image.open(f)
            media_to_send.append({"type": "image", "data": img})
        st.success(f"✅ Επιλέχθηκαν {len(uploaded_docs)} αρχεία.")

# --- INPUT TEXT & SEND ---
prompt = st.chat_input("Γράψε τι βλέπεις ή πάτα αποστολή...")

# Λογική: Αν υπάρχει κείμενο Ή αν υπάρχουν αρχεία και πατηθεί Enter (αν και το chat_input θέλει κείμενο συνήθως)
if prompt:
    # Προσθήκη μηνύματος χρήστη
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
        # Δείχνουμε τι στέλνουμε
        if media_to_send:
            st.caption(f"📎 Συνημμένα: {len(media_to_send)} αρχεία")

    # Ετοιμασία Prompt
    sys = f"Είσαι {st.session_state.current_mode}. Ανάλυσε προσεκτικά τα δεδομένα (εικόνα/βίντεο) και απάντησε τεχνικά."
    full_prompt = f"{sys}\nΕρώτηση: {prompt}"

    # Κλήση AI
    with st.chat_message("assistant"):
        # Αν έχουμε βίντεο, θα πάρει λίγο χρόνο
        loading_msg = "🧠 Ανάλυση..."
        if any(f["type"] == "video" for f in media_to_send):
            loading_msg = "⏳ Επεξεργασία βίντεο (μπορεί να πάρει 10-20 δευτ)..."
            
        with st.spinner(loading_msg):
            reply = process_request(full_prompt, media_to_send)
            st.markdown(reply)
            
    st.session_state.messages.append({"role": "assistant", "content": reply})
