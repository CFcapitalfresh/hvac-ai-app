import streamlit as st
import google.generativeai as genai
import json
import time
import tempfile
import os
import hashlib
import pandas as pd # Χρειαζόμαστε pandas για τους πίνακες
from datetime import datetime
from PIL import Image

# --- ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ ---
st.set_page_config(page_title="HVAC Expert Manager", page_icon="🛡️", layout="wide")

# --- CSS STYLING ---
st.markdown("""<style>
    .user-box { background-color: #f0f2f6; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .bot-box { background-color: #e0f7fa; padding: 10px; border-radius: 10px; margin-bottom: 5px; border-left: 5px solid #00acc1; }
    .admin-panel { border: 2px solid #ef4444; padding: 15px; border-radius: 10px; background-color: #fef2f2; }
</style>""", unsafe_allow_html=True)

# --- GLOBAL SETTINGS ---
USERS_DB_FILE = "local_users_db.json" 
LOGS_DB_FILE = "chat_logs.json" # ΝΕΟ ΑΡΧΕΙΟ ΚΑΤΑΓΡΑΦΗΣ
ACTIVE_MODEL_NAME = None 

# --- 1. SETUP GEMINI AI ---
if "GEMINI_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    # Απενεργοποίηση φίλτρων
    SAFETY_SETTINGS = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        preferred_order = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]
        selected = next((p for p in preferred_order if p in available_models), available_models[0] if available_models else None)
        
        if selected:
            ACTIVE_MODEL_NAME = selected
        else:
            st.error("❌ Κρίσιμο Σφάλμα: Δεν βρέθηκαν μοντέλα.")
            st.stop()
    except Exception as e:
        st.error(f"⚠️ Σφάλμα AI: {e}"); st.stop()
else:
    st.error("⚠️ Λείπει το GEMINI_KEY."); st.stop()

# --- 2. DATA MANAGEMENT (USERS & LOGS) ---

def load_data(filename):
    if not os.path.exists(filename): return {} if "users" in filename else []
    try:
        with open(filename, "r", encoding="utf-8") as f: return json.load(f)
    except: return {} if "users" in filename else []

def save_data(filename, data):
    with open(filename, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, default=str)

def hash_pass(password):
    return hashlib.sha256(password.encode()).hexdigest()

def log_interaction(user_email, question, answer, tech_type):
    """Καταγράφει την ερώτηση και την απάντηση κρυφά"""
    logs = load_data(LOGS_DB_FILE)
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user_email,
        "type": tech_type,
        "question": question,
        "answer": answer[:100] + "..." # Αποθηκεύουμε την αρχή για οικονομία χώρου ή όλη αν θες
    }
    logs.append(entry)
    save_data(LOGS_DB_FILE, logs)

# --- 3. HELPER FUNCTIONS ---
def save_uploaded_file(uploaded_file):
    try:
        name = uploaded_file.name if hasattr(uploaded_file, 'name') else "camera_capture.jpg"
        suffix = os.path.splitext(name)[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            return tmp.name
    except: return None

def analyze_media_and_chat(prompt, file_paths_list, history, tech_type):
    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        content_parts = []
        
        system_msg = f"""
        Είσαι έμπειρος Τεχνικός {tech_type}.
        ΔΟΜΗ ΑΠΑΝΤΗΣΗΣ:
        1. 📘 ΑΠΟ ΤΑ MANUALS (Αν υπάρχουν).
        2. 🧠 ΑΠΟ ΕΜΠΕΙΡΙΑ.
        Μην μπερδεύεις Error Codes με Part Numbers.
        """
        content_parts.append(system_msg)
        
        if file_paths_list:
            for fpath in file_paths_list:
                try:
                    gfile = genai.upload_file(fpath)
                    while gfile.state.name == "PROCESSING": time.sleep(0.5); gfile = genai.get_file(gfile.name)
                    content_parts.append(gfile)
                except: pass
            content_parts.append("Ανάλυσε τα αρχεία.")

        for msg in history: content_parts.append(f"{'User' if msg['role']=='user' else 'Expert'}: {msg['content']}")
        content_parts.append(f"User Question: {prompt}")

        response = model.generate_content(content_parts, safety_settings=SAFETY_SETTINGS)
        return response.text if response.candidates else "⚠️ Μπλοκαρίστηκε από το AI."
    except Exception as e: return f"⚠️ Σφάλμα: {str(e)}"

# --- 4. AUTHENTICATION & ADMIN LOGIC ---

if "user" not in st.session_state: st.session_state.user = None

def login_screen():
    st.title("🔐 HVAC Expert Portal")
    users = load_data(USERS_DB_FILE)
    
    t1, t2 = st.tabs(["Είσοδος", "Εγγραφή"])
    
    with t1:
        email = st.text_input("Email", key="login_email").lower().strip()
        passw = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            # Master Backdoor
            if email=="admin" and passw=="admin":
                st.session_state.user={"email":"admin","role":"admin","name":"Master Admin", "status":"approved"}
                st.rerun()
            
            if email in users and users[email]["password"]==hash_pass(passw):
                # ΕΛΕΓΧΟΣ ΕΓΚΡΙΣΗΣ
                if users[email].get("status") == "approved":
                    st.session_state.user = users[email]
                    st.rerun()
                elif users[email].get("status") == "blocked":
                    st.error("⛔ Ο λογαριασμός σας έχει αποκλειστεί.")
                else:
                    st.warning("⏳ Ο λογαριασμός σας είναι υπό έγκριση από τον Διαχειριστή.")
            else: st.error("Λάθος στοιχεία.")

    with t2:
        new_e = st.text_input("Email Εγγραφής").lower().strip()
        new_n = st.text_input("Ονοματεπώνυμο")
        new_p = st.text_input("Κωδικός", type="password")
        if st.button("Αίτημα Εγγραφής"):
            if new_e in users: st.error("Το email υπάρχει ήδη.")
            else:
                # Νέοι χρήστες είναι PENDING από προεπιλογή
                users[new_e] = {
                    "email": new_e, 
                    "name": new_n, 
                    "password": hash_pass(new_p), 
                    "role": "user", 
                    "status": "pending", # <--- SOS: Αναμονή έγκρισης
                    "joined": str(datetime.now())
                }
                save_data(USERS_DB_FILE, users)
                st.success("✅ Το αίτημα εστάλη! Περιμένετε έγκριση από τον διαχειριστή.")

# --- 5. MAIN APP ---
def main_app():
    user_role = st.session_state.user.get("role")
    
    # --- SIDEBAR ---
    with st.sidebar:
        st.header(f"👤 {st.session_state.user['name']}")
        st.caption("Κατάσταση: Online")
        if st.button("🚪 Logout"): st.session_state.user=None; st.rerun()
        st.divider()
        
        # --- ADMIN PANEL (ΕΜΦΑΝΙΖΕΤΑΙ ΜΟΝΟ ΣΤΟΥΣ ADMIN) ---
        if user_role == "admin":
            st.markdown("### 🛡️ Διαχείριση (Admin)")
            admin_tab = st.radio("Εργαλεία:", ["Εφαρμογή (Chat)", "👥 Χρήστες & Εγκρίσεις", "📊 Καταγραφή (Logs)"])
        else:
            admin_tab = "Εφαρμογή (Chat)"
            
    # --- LOGIC ΒΑΣΕΙ ΕΠΙΛΟΓΗΣ ---
    
    # 1. ΕΦΑΡΜΟΓΗ (Για όλους)
    if admin_tab == "Εφαρμογή (Chat)":
        st.title("⚡ HVAC Quick Expert")
        
        # Επιλογή Ειδικότητας
        col1, col2 = st.columns([1,2])
        with col1:
            tech_type = st.radio("Ειδικότητα:", ["Κλιματισμός (AC)", "Ψύξη", "Θέρμανση"])
        
        # Uploads
        final_paths = []
        with st.expander("📸 Προσθήκη Φωτογραφίας/Manual", expanded=False):
            inp_mode = st.radio("Πηγή:", ["📂 Αρχεία", "📷 Κάμερα"], horizontal=True)
            if inp_mode == "📂 Αρχεία":
                files = st.file_uploader("Επιλογή", type=["pdf","jpg","png"], accept_multiple_files=True)
                if files:
                    for f in files:
                        p = save_uploaded_file(f)
                        if p: final_paths.append(p)
            else:
                cam = st.camera_input("Λήψη")
                if cam:
                    p = save_uploaded_file(cam)
                    if p: final_paths.append(p)

        if "messages" not in st.session_state: st.session_state.messages = []
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

        if prompt := st.chat_input("Περιγραφή προβλήματος..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("🧠 Ανάλυση..."):
                    resp = analyze_media_and_chat(prompt, final_paths, st.session_state.messages[:-1], tech_type)
                    st.markdown(resp)
            
            st.session_state.messages.append({"role": "assistant", "content": resp})
            
            # --- ΚΡΥΦΗ ΚΑΤΑΓΡΑΦΗ (LOGGING) ---
            log_interaction(st.session_state.user['email'], prompt, resp, tech_type)

        if st.button("🔄 Νέα Ερώτηση"): st.session_state.messages = []; st.rerun()

    # 2. ΔΙΑΧΕΙΡΙΣΗ ΧΡΗΣΤΩΝ (Μόνο Admin)
    elif admin_tab == "👥 Χρήστες & Εγκρίσεις":
        st.title("👥 Διαχείριση Προσωπικού")
        users = load_data(USERS_DB_FILE)
        
        # Λίστα για επεξεργασία
        st.write("---")
        for email, u_data in users.items():
            if email == "admin": continue # Μην πειράζουμε τον admin
            
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            with c1:
                st.write(f"**{u_data['name']}** ({email})")
                st.caption(f"Εγγραφή: {u_data['joined']}")
            with c2:
                # Ένδειξη Status
                status = u_data.get('status', 'pending')
                if status == 'pending': st.warning("⏳ Αναμονή")
                elif status == 'approved': st.success("✅ Ενεργός")
                else: st.error("⛔ Blocked")
            with c3:
                # Κουμπιά Ενεργειών
                if status != 'approved':
                    if st.button("✅ Έγκριση", key=f"app_{email}"):
                        users[email]['status'] = 'approved'
                        save_data(USERS_DB_FILE, users)
                        st.rerun()
            with c4:
                if status != 'blocked':
                    if st.button("⛔ Block", key=f"blk_{email}"):
                        users[email]['status'] = 'blocked'
                        save_data(USERS_DB_FILE, users)
                        st.rerun()
                if st.button("🗑️ Διαγραφή", key=f"del_{email}"):
                    del users[email]
                    save_data(USERS_DB_FILE, users)
                    st.rerun()
            st.divider()

    # 3. STATS & LOGS (Μόνο Admin)
    elif admin_tab == "📊 Καταγραφή (Logs)":
        st.title("📊 Ιστορικό Ερωτήσεων & Στατιστικά")
        logs = load_data(LOGS_DB_FILE)
        
        if not logs:
            st.info("Δεν υπάρχουν καταγεγραμμένες συνομιλίες ακόμα.")
        else:
            df = pd.DataFrame(logs)
            
            # Στατιστικά
            st.subheader("Σύνοψη")
            colA, colB = st.columns(2)
            with colA:
                st.metric("Σύνολο Ερωτήσεων", len(df))
            with colB:
                st.write("Ερωτήσεις ανά Ειδικότητα:")
                st.bar_chart(df['type'].value_counts())

            # Αναλυτικός Πίνακας
            st.subheader("🕵️ Αναλυτικό Ιστορικό (Spy View)")
            
            # Φίλτρα
            selected_user = st.selectbox("Φίλτρο ανά Χρήστη", ["Όλοι"] + list(df['user'].unique()))
            if selected_user != "Όλοι":
                df = df[df['user'] == selected_user]

            # Εμφάνιση πίνακα
            st.dataframe(
                df[['timestamp', 'user', 'type', 'question', 'answer']], 
                use_container_width=True,
                height=400
            )

if st.session_state.user: main_app()
else: login_screen()
