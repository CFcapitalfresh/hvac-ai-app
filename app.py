import streamlit as st
import google.generativeai as genai
from PIL import Image

# Ρυθμίσεις Σελίδας
st.set_page_config(page_title="AI HVAC Expert", page_icon="🔧", layout="centered")

# CSS Styling
st.markdown("""
<style>
    .stApp { background-color: #0f172a; color: #e2e8f0; }
    .stChatMessage { border-radius: 15px; padding: 10px; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #3b82f6; color: white; }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("⚙️ Ρυθμίσεις")
    api_key = st.text_input("Gemini API Key", type="password", placeholder="AIzaSy...")
    if api_key:
        genai.configure(api_key=api_key)
        st.success("✅ Συνδέθηκε!")
    else:
        st.warning("⚠️ Βάλε το κλειδί σου")
    
    st.divider()
    model_option = st.selectbox("Μοντέλο AI", ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"])
    st.divider()
    uploaded_files = st.file_uploader("📂 Ανέβασε Manuals/Φώτο", accept_multiple_files=True, type=['pdf', 'jpg', 'png'])

# Main App
st.title("🔧 AI HVAC Technician")
st.caption("Cloud Edition • Python Power")

mode = st.radio("Ειδικότητα:", ["AC / Κλιματισμός", "❄️ Ψύξη", "🔥 Λέβητες"], horizontal=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

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

prompt = st.chat_input("Γράψε τη βλάβη...")

if prompt and api_key:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    sys_instruction = "Είσαι τεχνικός HVAC. Απάντησε τεχνικά στα Ελληνικά."
    if "AC" in mode: sys_instruction = "Είσαι τεχνικός Κλιματισμού."
    elif "Ψύξη" in mode: sys_instruction = "Είσαι ψυκτικός."
    
    full_prompt = f"{sys_instruction} Ερώτηση: {prompt}"

    image_parts = []
    if uploaded_files:
        for uploaded_file in uploaded_files:
            if uploaded_file.type.startswith('image'):
                image = Image.open(uploaded_file)
                image_parts.append(image)

    with st.chat_message("assistant"):
        with st.spinner("Σκέφτεται..."):
            response = get_gemini_response(full_prompt, image_parts)
            st.markdown(response)
            
    st.session_state.messages.append({"role": "assistant", "content": response})
elif prompt and not api_key:
    st.error("⛔ Βάλε το API Key στις Ρυθμίσεις.")
