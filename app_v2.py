import streamlit as st
import google.generativeai as genai
import json
import time
import tempfile
import os
import hashlib
from datetime import datetime
from PIL import Image

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC On-Site Expert", page_icon="⚡", layout="wide")

# --- CSS STYLING ---
st.markdown("""<style>
    .user-box { background-color: #f0f2f6; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .bot-box { background-color: #e0f7fa; padding: 10px; border-radius: 10px; margin-bottom: 5px; border-left: 5px solid #00acc1; }
    .reset-btn { width: 100%; margin-top: 20px; }
</style>""", unsafe_allow_html=True)

# --- GLOBAL SETTINGS ---
USERS_DB_FILE = "local_users_db.json" 
CURRENT_MODEL_NAME = "gemini-pro" # Fallback default

# --- 1. SETUP GEMINI AI (AUTO-DISCOVERY) ---
if "GEMINI_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    try:
        all_models = list(genai.list_models())
        valid_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        priority_list = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-1.0-pro", "models/gemini-pro"]
        
        found_model = None
        for p in priority_list:
            if p in valid_models:
                found_model = p
                break
        
        if not found_model and valid_models: found_model = valid_models[0]
            
        if found_model:
            CURRENT_MODEL_NAME = found_model
            st.toast(f"✅ AI Connected: {found_model.replace('models/', '')}", icon="🤖")
        else:
            st.error("❌ Δεν βρέθηκαν συμβατά μοντέλα.")
            
    except Exception as e:
        st.error(f"⚠️ Σφάλμα σύνδεσης AI: {e}")
else:
    st.error("⚠️ Λείπει το GEMINI_KEY από τα secrets.")
    st.stop()

# --- 2. LOCAL USER MANAGEMENT ---

def load_users():
    if not os.path.exists(USERS_DB_FILE): return {}
    try:
        with open(USERS_DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_users(users):
    with open(USERS_DB_FILE, "w", encoding="utf-8") as f: json.dump(users, f, indent=4)

def hash_pass(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- 3. HELPER FUNCTIONS ---

def save_uploaded_file(uploaded_file):
    try:
        # Αν είναι φωτογραφία από κάμερα (δεν έχει όνομα), δώσε default
        name = uploaded_file.name if hasattr(uploaded_file, 'name') else "camera_capture.jpg"
        suffix = os.path.splitext(name)[1]
        if not suffix: suffix = ".jpg" # Fallback για camera input
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            return tmp.name
    except Exception as e:
        st.error(f"Error saving file: {e}")
        return None

def analyze_media_and_chat(prompt, file_path, history, tech_type):
    """Η καρδιά του AI: Με Ενισχυμένη Λογική Διαχωρισμού (Anti-Confusion Logic)"""
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        content_parts = []
        
        # --- SYSTEM PROMPT (ANTI-CONFUSION) ---
        system_msg = f"""
        Είσαι έμπειρος Τεχνικός {tech_type} και αναλυτής τεχνικών εγχειριδίων.
        
        ΚΡΙΣΙΜΟΣ ΚΑΝΟΝΑΣ ΔΙΑΧΩΡΙΣΜΟΥ (ANTI-CONFUSION PROTOCOL):
        Πρέπει να ξεχωρίζεις αυστηρά τους ΚΩΔΙΚΟΥΣ ΒΛΑΒΗΣ (Error Codes) από τους ΚΩΔΙΚΟΥΣ ΑΝΤΑΛΛΑΚΤΙΚΩΝ (Part Numbers).
        
        1. ΕΛΕΓΧΟΣ ΣΥΜΦΡΑΖΟΜΕΝΩΝ:
           - Αν ο χρήστης μιλάει για "Σφάλμα", "Βλάβη", "Error": Ψάξε ΜΟΝΟ στους πίνακες "Troubleshooting" ή "Fault Codes".
           - Αν ο χρήστης ζητάει "Ανταλλακτικό", "Κωδικό": Ψάξε ΜΟΝΟ στους πίνακες "Spare Parts".
           
        2. ΔΙΑΣΤΑΥΡΩΣΗ:
           - Ο ίδιος αριθμός (π.χ. 501) μπορεί να είναι Βλάβη σε μια σελίδα και Εξάρτημα σε άλλη. ΜΗΝ ΤΑ ΜΠΕΡΔΕΥΕΙΣ.
           
        3. ΔΟΜΗ ΑΠΑΝΤΗΣΗΣ:
           - Ξεκίνα με: "Σύμφωνα με το manual..."
           - Απάντησε Ελληνικά, σύντομα και στοχευμένα.
        """
        content_parts.append(system_msg)
        
        # Uploaded File
        if file_path:
            gfile = genai.upload_file(file_path)
            while gfile.state.name == "PROCESSING":
                time.sleep(1)
                gfile = genai.get_file(gfile.name)
            content_parts.append(gfile)
            content_parts.append("Ανάλυσε το αρχείο με βάση το πρωτόκολλο.")

        # History
        for msg in history:
            role_label = "User: " if msg["role"] == "user" else "Expert: "
            content_parts.append(f"{role_label} {msg['content']}")

        # Current Prompt
        content_parts.append(f"User Question: {prompt}")

        response = model.generate_content(content_parts)
        return response.text
        
    except Exception as e:
        return f"⚠️ Σφάλμα AI ({CURRENT_MODEL_NAME}): {str(e)}"

# --- 4. AUTHENTICATION SCREENS ---

if "user" not in st.session_state: st.session_state.user = None

def login_screen():
    st.title("🔐 HVAC Expert Login")
    users = load_users()
    if not users: st.warning("⚠️ Η βάση είναι άδεια. Μπες με admin/admin.")
    
    tab1, tab2 = st.tabs(["Είσοδος", "Εγγραφή"])
    
    with tab1:
        email = st.text_input("Email").lower().strip()
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if email == "admin" and password == "admin":
                st.session_state.user = {"email": "admin", "role": "admin", "name": "Master Admin"}
                st.rerun()
            
            if email in users and users[email]["password"] == hash_pass(password):
                st.session_state.user = users[email]
                st.rerun()
            else: st.error("Λάθος στοιχεία.")

    with tab2:
        new_email = st.text_input("New Email").lower().strip()
        new_name = st.text_input("Ονοματεπώνυμο")
        new_pass = st.text_input("New Password", type="password")
        if st.button("Δημιουργία Λογαριασμού"):
            if new_email in users: st.error("Το email υπάρχει ήδη.")
            else:
                users[new_email] = {"email": new_email, "name": new_name, "password": hash_pass(new_pass), "role": "user", "joined": str(datetime.now())}
                save_users(users)
                st.success("Επιτυχία! Κάντε είσοδο.")

# --- 5. MAIN APPLICATION ---

def main_app():
    with st.sidebar:
        st.header(f"👤 {st.session_state.user['name']}")
        st.caption(f"🤖 Brain: {CURRENT_MODEL_NAME.replace('models/', '')}")
        
        if st.button("🚪 Logout"):
            st.session_state.user = None; st.rerun()
            
        st.divider()
        tech_type = st.radio("🔧 Ειδικότητα:", ["Κλιματισμός (AC)", "Ψύξη (Ψυγεία)", "Θέρμανση (Λέβητες)"])
        st.divider()
        
        # --- NEW: CAMERA INPUT ---
        st.subheader("📸 Κάμερα & Αρχεία")
        
        # Επιλογή πηγής (για να μην ανοίγει η κάμερα συνέχεια)
        input_method = st.radio("Επιλογή Πηγής:", ["📂 Ανέβασμα Αρχείου", "📷 Λήψη Φωτογραφίας"], horizontal=True)
        
        uploaded_file = None
        camera_file = None
        final_file = None
        
        if input_method == "📂 Ανέβασμα Αρχείου":
            uploaded_file = st.file_uploader("Manual/Φωτό/Video", type=["pdf", "jpg", "png", "mp4", "mov"])
            if uploaded_file: final_file = uploaded_file
            
        elif input_method == "📷 Λήψη Φωτογραφίας":
            camera_file = st.camera_input("Τράβηξε φωτογραφία")
            if camera_file: final_file = camera_file

        current_file_path = None
        if final_file:
            current_file_path = save_uploaded_file(final_file)
            st.success("✅ Αρχείο έτοιμο για ανάλυση")
            # Αν είναι εικόνα (είτε upload είτε camera), δείξε preview
            if hasattr(final_file, 'type') and final_file.type.startswith("image") or input_method == "📷 Λήψη Φωτογραφίας":
                st.image(final_file, caption="Προς Ανάλυση", use_container_width=True)
        
        st.divider()
        if st.button("🔄 Νέα Συσκευή (RESET)", type="primary"):
            st.session_state.messages = []
            st.session_state.uploaded_file_path = None 
            st.rerun()

        if st.session_state.user.get("role") == "admin":
            st.divider(); 
            with st.expander("👥 Συνδρομητές"): st.json(load_users())

    st.title("⚡ HVAC Quick Expert")

    if "messages" not in st.session_state: st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]): st.markdown(message["content"])

    if prompt := st.chat_input("Περιγράψτε το πρόβλημα..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("🧠 Ανάλυση..."):
                response_text = analyze_media_and_chat(
                    prompt, 
                    current_file_path,
                    st.session_state.messages[:-1],
                    tech_type
                )
                st.markdown(response_text)
                
        st.session_state.messages.append({"role": "assistant", "content": response_text})

if st.session_state.user:
    main_app()
else:
    login_screen()
