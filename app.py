import streamlit as st
import google.generativeai as genai
from PIL import Image

# --- 1. ΒΑΣΙΚΕΣ ΡΥΘΜΙΣΕΙΣ ---
st.set_page_config(
    page_title="HVAC Pro",
    page_icon="🔧",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- 2. SIDEBAR & ΡΥΘΜΙΣΕΙΣ ---
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    
    # Διακόπτης Θέματος (Light/Dark)
    theme_mode = st.radio("Θέμα Εμφάνισης:", ["☀️ Ημέρα (Light)", "🌙 Νύχτα (Dark)"])
    
    st.divider()
    
    # API Key
    api_key = st.text_input("🔑 API Key", type="password", placeholder="AIzaSy...")
    if api_key:
        genai.configure(api_key=api_key)
        st.caption("✅ Συνδέθηκε")
    
    st.divider()
    
    # Μοντέλο
    model_option = st.selectbox("🤖 Μοντέλο AI", ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"])

# --- 3. CUSTOM CSS (ΕΜΦΑΝΙΣΗ) ---
# Εδώ κρύβουμε τα "διαφημιστικά" και φτιάχνουμε τα χρώματα
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;} /* Κρύβει το μενού πάνω δεξιά */
            footer {visibility: hidden;}    /* Κρύβει το 'Made with Streamlit' */
            header {visibility: hidden;}    /* Κρύβει την πάνω μπάρα */
            .stDeployButton {display:none;} /* Κρύβει το κουμπί Deploy */
            
            /* Ρυθμίσεις για Κινητά */
            .stApp { margin-top: -80px; } /* Κερδίζουμε χώρο πάνω */
            
            /* Στυλ Μηνυμάτων */
            .stChatMessage {
                border-radius: 12px;
                padding: 1rem;
                font-size: 18px !important; /* Μεγαλύτερα γράμματα */
            }
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# Δυναμικό CSS ανάλογα με την επιλογή του χρήστη
if "Ημέρα" in theme_mode:
    st.markdown("""
    <style>
        .stApp { background-color: #ffffff; color: #000000; }
        .stChatMessage { background-color: #f3f4f6; border: 1px solid #e5e7eb; color: #000000; }
        div[data-testid="stChatMessageContent"] { color: #000000; font-weight: 500; }
        p { font-size: 18px; }
    </style>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <style>
        .stApp { background-color: #0f172a; color: #e2e8f0; }
        .stChatMessage { background-color: #1e293b; border: 1px solid #334155; }
    </style>
    """, unsafe_allow_html=True)

# --- 4. ΚΥΡΙΩΣ ΕΦΑΡΜΟΓΗ ---
st.title("🔧 HVAC Expert")

# Επιλογή Ειδικότητας (Με εικονίδια για ευκολία)
col1, col2, col3 = st.columns(3)
with col1:
    ac_mode = st.button("❄️ AC", use_container_width=True)
with col2:
    ref_mode = st.button("🧊 Ψύξη", use_container_width=True)
with col3:
    gas_mode = st.button("🔥 Αέριο", use_container_width=True)

# Διαχείριση κατάστασης (State)
if "current_mode" not in st.session_state: st.session_state.current_mode = "Κλιματισμός"
if ac_mode: st.session_state.current_mode = "Κλιματισμός"
if ref_mode: st.session_state.current_mode = "Ψύξη"
if gas_mode: st.session_state.current_mode = "Λέβητες Αερίου"

st.caption(f"Λειτουργία: **{st.session_state.current_mode}**")

# Ιστορικό
if "messages" not in st.session_state: st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- 5. LOGIC & INPUTS ---
def get_response(prompt, img=None):
    try:
        model = genai.GenerativeModel(model_option)
        content = [prompt]
        if img: content.append(img)
        return model.generate_content(content).text
    except Exception as e:
        return f"❌ Error: {str(e)}"

# Κουμπί Κάμερας (Μετονομασμένο & Καθαρό)
# Στα κινητά, αυτό το κουμπί ανοίγει επιλογή: "Camera" ή "Files"
uploaded_file = st.file_uploader("📷 Πάτα εδώ για Φώτο/Βίντεο ή PDF", type=['jpg','png','jpeg','pdf'], label_visibility="visible")

# Chat Input (Ενσωματωμένο μικρόφωνο πληκτρολογίου)
user_input = st.chat_input("Γράψε τη βλάβη...")

if user_input and api_key:
    # Εμφάνιση χρήστη
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Προετοιμασία Prompt
    sys_prompt = f"Είσαι τεχνικός {st.session_state.current_mode}. Απάντησε τεχνικά, σύντομα και στα Ελληνικά."
    final_prompt = f"{sys_prompt}\nΕρώτηση: {user_input}"

    # Εικόνα
    img_data = None
    if uploaded_file and uploaded_file.type.startswith('image'):
        img_data = Image.open(uploaded_file)
        st.toast("📎 Εικόνα επισυνάφθηκε!")

    # Απάντηση AI
    with st.chat_message("assistant"):
        with st.spinner("🔍 Ανάλυση..."):
            reply = get_response(final_prompt, img_data)
            st.markdown(reply)
    
    st.session_state.messages.append({"role": "assistant", "content": reply})

elif user_input and not api_key:
    st.error("⚠️ Πήγαινε στις Ρυθμίσεις (πάνω αριστερά >) και βάλε το API Key.")
