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
ACTIVE_MODEL_NAME = None # Θα το βρει ο κώδικας

# --- 1. SETUP GEMINI AI (TRUE AUTO-DISCOVERY) ---
if "GEMINI_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    
    # Απενεργοποίηση φίλτρων για να μην κόβει manuals
    SAFETY_SETTINGS = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    try:
        # ΒΗΜΑ 1: Ζητάμε από την Google ΟΛΑ τα μοντέλα που βλέπει το κλειδί σου
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # ΒΗΜΑ 2: Έξυπνη Επιλογή από τα ΥΠΑΡΚΤΑ και μόνο
        if not available_models:
            st.error("❌ Κρίσιμο Σφάλμα: Το API Key είναι ενεργό αλλά δεν έχει πρόσβαση σε κανένα μοντέλο!")
            st.stop()
            
        # Λίστα προτίμησης
        preferred_order = [
            "models/gemini-1.5-pro",
            "models/gemini-1.5-flash",
            "models/gemini-1.0-pro",
            "models/gemini-pro"
        ]
        
        selected = None
        for p in preferred_order:
            if p in available_models:
                selected = p
                break
        
        if not selected: selected = available_models[0]
        ACTIVE_MODEL_NAME = selected
        
    except Exception as e:
        st.error(f"⚠️ Σφάλμα Αναζήτησης Μοντέλων: {e}")
        st.stop()
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
    """Η καρδιά του AI: Αυστηρός Διαχωρισμός Πηγών"""
    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        content_parts = []
        
        # --- SYSTEM PROMPT ΜΕ ΑΥΣΤΗΡΗ ΔΟΜΗ ---
        system_msg = f"""
        Είσαι έμπειρος Τεχνικός {tech_type}.
        
        ΕΝΤΟΛΗ: Πρέπει να απαντήσεις ΧΩΡΙΖΟΝΤΑΣ ΤΗΝ ΠΛΗΡΟΦΟΡΙΑ σε δύο μέρη.
        
        ΑΚΟΛΟΥΘΗΣΕ ΑΥΤΗ ΤΗ ΔΟΜΗ ΑΠΑΝΤΗΣΗΣ ΑΚΡΙΒΩΣ:
        
        ---
        ### 📘 ΑΠΟ ΤΑ MANUALS / ΑΡΧΕΙΑ
        *(Γράψε ΕΔΩ μόνο ό,τι βρήκες ΡΗΤΑ μέσα στα αρχεία που ανέβασε ο χρήστης. Ανάφερε σελίδα ή πίνακα αν μπορείς. Αν τα αρχεία δεν λένε τίποτα σχετικό, γράψε: "Δεν βρέθηκαν συγκεκριμένες πληροφορίες στα αρχεία.")*
        
        ---
        ### 🧠 ΑΠΟ ΓΕΝΙΚΗ ΓΝΩΣΗ & ΕΜΠΕΙΡΙΑ
        *(Γράψε ΕΔΩ τη δική σου τεχνική άποψη, πιθανές αιτίες και λύσεις που ξέρεις ως ειδικός, ανεξάρτητα από τα αρχεία. Συμπλήρωσε τα κενά του manual.)*
        ---
        
        ΚΑΝΟΝΑΣ ΑΣΦΑΛΕΙΑΣ ΔΕΔΟΜΕΝΩΝ:
        - Μην μπερδεύεις Κωδικούς Βλάβης (Error Codes) με Κωδικούς Ανταλλακτικών (Part Numbers).
        - Απάντησε στα Ελληνικά.
        """
        content_parts.append(system_msg)
        
        # Upload Files
        if file_paths_list:
            for fpath in file_paths_list:
                try:
                    gfile = genai.upload_file(fpath)
                    while gfile.state.name == "PROCESSING":
                        time.sleep(0.5)
                        gfile = genai.get_file(gfile.name)
                    content_parts.append(gfile)
                except: pass 
            content_parts.append("Ανάλυσε τα δεδομένα με βάση την ΑΥΣΤΗΡΗ ΔΟΜΗ.")

        # History
        for msg in history:
            role_label = "User: " if msg["role"] == "user" else "Expert: "
            content_parts.append(f"{role_label} {msg['content']}")

        # Current Prompt
        content_parts.append(f"User Question: {prompt}")

        # Κλήση
        response = model.generate_content(
            content_parts,
            safety_settings=SAFETY_SETTINGS
        )
        
        if response.candidates:
            return response.text
        else:
            return f"⚠️ Μπλοκαρίστηκε από το μοντέλο ({ACTIVE_MODEL_NAME}). Δοκίμασε να ρωτήσεις διαφορετικά."
        
    except Exception as e:
        return f"⚠️ Σφάλμα ({ACTIVE_MODEL_NAME}): {str(e)}"

# --- 4. LOGIN ---
if "user" not in st.session_state: st.session_state.user = None

def login_screen():
    st.title("🔐 HVAC Expert Login")
    users = load_users()
    
    t1, t2 = st.tabs(["Είσοδος", "Εγγραφή"])
    with t1:
        email = st.text_input("Email").lower().strip()
        passw = st.text_input("Password", type="password")
        if st.button("Login"):
            if email=="admin" and passw=="admin":
                st.session_state.user={"email":"admin","role":"admin","name":"Master"}; st.rerun()
            if email in users and users[email]["password"]==hash_pass(passw):
                st.session_state.user=users[email]; st.rerun()
            else: st.error("Λάθος στοιχεία")
    with t2:
        new_e = st.text_input("New Email").lower().strip()
        new_n = st.text_input("Ονοματεπώνυμο")
        new_p = st.text_input("New Password", type="password")
        if st.button("Δημιουργία"):
            if new_e in users: st.error("Υπάρχει ήδη")
            else:
                users[new_e]={"email":new_e,"name":new_n,"password":hash_pass(new_p),"role":"user","joined":str(datetime.now())}
                save_users(users); st.success("ΟΚ! Κάντε είσοδο.")

# --- 5. MAIN APP ---
def main_app():
    with st.sidebar:
        st.header(f"👤 {st.session_state.user['name']}")
        
        if ACTIVE_MODEL_NAME:
            clean_name = ACTIVE_MODEL_NAME.replace('models/', '')
            st.success(f"✅ Συνδέθηκε: **{clean_name}**")
        else:
            st.error("❌ Disconnected")
        
        if st.button("🚪 Logout"): st.session_state.user=None; st.rerun()
        st.divider()
        tech_type = st.radio("🔧 Ειδικότητα:", ["Κλιματισμός (AC)", "Ψύξη", "Θέρμανση"])
        st.divider()
        
        # Inputs
        st.subheader("📸 Είσοδος")
        inp_mode = st.radio("Πηγή:", ["📂 Αρχεία", "📷 Κάμερα"], horizontal=True, label_visibility="collapsed")
        
        final_paths = []
        if inp_mode == "📂 Αρχεία":
            files = st.file_uploader("Επιλογή (PDF/Εικόνες)", type=["pdf","jpg","png","mp4"], accept_multiple_files=True)
            if files:
                for f in files:
                    p = save_uploaded_file(f)
                    if p: final_paths.append(p)
                st.success(f"✅ {len(final_paths)} αρχεία")
        else:
            cam = st.camera_input("Λήψη")
            if cam:
                p = save_uploaded_file(cam)
                if p: final_paths.append(p)
                st.success("✅ Φωτογραφία ελήφθη")

        if final_paths:
            with st.expander("👁️ Προβολή"):
                for p in final_paths:
                    if p.endswith((".jpg",".png")): st.image(p, width=150)
                    else: st.write(f"📄 {os.path.basename(p)}")
        
        st.divider()
        if st.button("🔄 Νέα Συσκευή (RESET)", type="primary"):
            st.session_state.messages = []
            st.rerun()

        if st.session_state.user.get("role") == "admin":
            st.divider(); 
            with st.expander("👥 Χρήστες"): st.json(load_users())

    st.title("⚡ HVAC Expert Pro")

    if "messages" not in st.session_state: st.session_state.messages = []
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("Περιγράψτε το πρόβλημα..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("🧠 Ανάλυση..."):
                resp = analyze_media_and_chat(
                    prompt, final_paths, st.session_state.messages[:-1], tech_type
                )
                st.markdown(resp)
        st.session_state.messages.append({"role": "assistant", "content": resp})

if st.session_state.user: main_app()
else: login_screen()
