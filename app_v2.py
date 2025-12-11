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
CURRENT_MODEL_NAME = "gemini-pro" 

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
    """Αποθηκεύει ΕΝΑ αρχείο"""
    try:
        name = uploaded_file.name if hasattr(uploaded_file, 'name') else "camera_capture.jpg"
        suffix = os.path.splitext(name)[1]
        if not suffix: suffix = ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            return tmp.name
    except Exception as e:
        st.error(f"Error saving file: {e}")
        return None

def analyze_media_and_chat(prompt, file_paths_list, history, tech_type):
    """Η καρδιά του AI: Δέχεται ΛΙΣΤΑ αρχείων"""
    try:
        model = genai.GenerativeModel(CURRENT_MODEL_NAME)
        content_parts = []
        
        # --- SYSTEM PROMPT ---
        system_msg = f"""
        Είσαι έμπειρος Τεχνικός {tech_type} και αναλυτής.
        
        ΣΤΟΧΟΣ: Να δώσεις την καλύτερη δυνατή τεχνική λύση, συνδυάζοντας τα Manuals/Φωτογραφίες με την Εμπειρία σου.
        
        ΚΑΝΟΝΕΣ:
        1. **ΕΛΕΓΧΟΣ ΑΡΧΕΙΩΝ (Anti-Confusion):**
           - Αν υπάρχουν πολλαπλά αρχεία, συνδύασε τις πληροφορίες.
           - ΠΡΟΣΟΧΗ: Μην μπερδεύεις Κωδικούς Βλάβης (Error Codes) με Κωδικούς Ανταλλακτικών (Part Numbers). Διάβασε τον τίτλο του πίνακα!
           
        2. **ΓΕΝΙΚΗ ΓΝΩΣΗ (Υποχρεωτική):**
           - Ακόμα κι αν βρεις τη λύση στο manual, ΠΡΟΣΘΕΣΕ τη δική σου εμπειρία.
           - Αν τα αρχεία δεν έχουν την απάντηση, ΑΠΑΝΤΗΣΕ ΚΑΝΟΝΙΚΑ βάσει της γενικής σου γνώσης.
           
        3. **ΔΟΜΗ ΑΠΑΝΤΗΣΗΣ:**
           - Ξεκίνα με: "Σύμφωνα με τα αρχεία..." (αν βρήκες κάτι).
           - Συνέχισε με: "Βάσει της εμπειρίας μου..." ή "Γενικά σε τέτοιες περιπτώσεις...".
           - Απάντησε Ελληνικά, σύντομα και πρακτικά.
        """
        content_parts.append(system_msg)
        
        # Upload ALL Files
        if file_paths_list:
            for fpath in file_paths_list:
                gfile = genai.upload_file(fpath)
                # Περίμενε να επεξεργαστεί το κάθε αρχείο
                while gfile.state.name == "PROCESSING":
                    time.sleep(0.5)
                    gfile = genai.get_file(gfile.name)
                content_parts.append(gfile)
            
            content_parts.append("Ανάλυσε τα επισυναπτόμενα αρχεία.")

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
        
        # --- CAMERA & MULTI-FILE INPUT ---
        st.subheader("📸 Κάμερα & Αρχεία")
        input_method = st.radio("Πηγή:", ["📂 Πολλαπλά Αρχεία", "📷 Κάμερα"], horizontal=True, label_visibility="collapsed")
        
        # Λίστα για να μαζέψουμε όλα τα paths
        final_file_paths = []
        
        if input_method == "📂 Πολλαπλά Αρχεία":
            # ΕΔΩ Η ΑΛΛΑΓΗ: accept_multiple_files=True
            uploaded_files = st.file_uploader("Επιλογή Αρχείων (PDF, JPG, PNG)", type=["pdf", "jpg", "png", "mp4", "mov"], accept_multiple_files=True)
            
            if uploaded_files:
                for uf in uploaded_files:
                    path = save_uploaded_file(uf)
                    if path: final_file_paths.append(path)
                
                st.success(f"✅ {len(final_file_paths)} αρχεία έτοιμα")
                
        else:
            camera_file = st.camera_input("Λήψη Φωτογραφίας")
            if camera_file:
                path = save_uploaded_file(camera_file)
                if path: final_file_paths.append(path)
                st.success("✅ Φωτογραφία έτοιμη")

        # Preview (δείχνουμε μόνο εικόνες για να μην γεμίσει η οθόνη)
        if final_file_paths:
            with st.expander("👁️ Προεπισκόπηση Αρχείων", expanded=False):
                for p in final_file_paths:
                    if p.endswith((".jpg", ".png", ".jpeg")):
                        st.image(p, width=150)
                    else:
                        st.write(f"📄 {os.path.basename(p)}")
        
        st.divider()
        if st.button("🔄 Νέα Συσκευή (RESET)", type="primary"):
            st.session_state.messages = []
            # Δεν χρειάζεται να καθαρίσουμε paths εδώ, καθαρίζουν στο rerun
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
            with st.spinner("🧠 Ανάλυση (Πολλαπλές Πηγές + Γνώση)..."):
                response_text = analyze_media_and_chat(
                    prompt, 
                    final_file_paths, # Στέλνουμε ΤΗ ΛΙΣΤΑ των αρχείων
                    st.session_state.messages[:-1],
                    tech_type
                )
                st.markdown(response_text)
                
        st.session_state.messages.append({"role": "assistant", "content": response_text})

if st.session_state.user:
    main_app()
else:
    login_screen()
