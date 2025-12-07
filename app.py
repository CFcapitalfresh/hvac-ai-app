# 3. AI Generation (ME SAFETY FIX & RETRY LOGIC)
        if media_content or "Γενική" in search_source or ("Υβριδικό" in search_source):
            
            # --- ΡΥΘΜΙΣΕΙΣ ΑΣΦΑΛΕΙΑΣ (ΑΠΕΝΕΡΓΟΠΟΙΗΣΗ ΦΙΛΤΡΩΝ) ---
            # Αυτό λύνει το "block_reason: OTHER" στα manuals
            from google.generativeai.types import HarmCategory, HarmBlockThreshold
            
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
            # ----------------------------------------------------

            # Μνήμη (Context)
            chat_history_str = ""
            for msg in st.session_state.messages[-8:]:
                role_label = "ΤΕΧΝΙΚΟΣ" if msg["role"] == "user" else "AI"
                chat_history_str += f"{role_label}: {msg['content']}\n"
            
            source_instr = f"Έχεις το manual '{found_file_name}'." if found_file_name else "Δεν βρέθηκε manual."
            
            full_prompt = f"""
            Είσαι {st.session_state.tech_mode}. Μίλα Ελληνικά.
            
            === ΙΣΤΟΡΙΚΟ ===
            {chat_history_str}
            ================
            
            ΟΔΗΓΙΕΣ:
            1. Αγνοησε ορθογραφικά.
            2. {source_instr}
            3. ΣΤΟ ΤΕΛΟΣ γράψε πηγή (Manual ή Γενική Γνώση).
            
            ΕΡΩΤΗΣΗ: {prompt}
            """
            
            # --- RETRY LOGIC ---
            retry_attempts = 3
            success = False
            
            with st.spinner("🧠 Επεξεργασία..."):
                for attempt in range(retry_attempts):
                    try:
                        model = genai.GenerativeModel(model_option)
                        
                        # ΠΡΟΣΘΗΚΗ safety_settings ΣΤΗΝ ΚΛΗΣΗ
                        response = model.generate_content(
                            [full_prompt, *media_content],
                            safety_settings=safety_settings
                        )
                        
                        # ΕΛΕΓΧΟΣ ΑΝ ΤΟ AI ΜΠΛΟΚΑΡΕ ΤΗΝ ΑΠΑΝΤΗΣΗ
                        if not response.parts:
                            # Αν δεν έδωσε απάντηση, πιθανόν μπλοκαρίστηκε ή απέτυχε
                            if response.prompt_feedback:
                                error_msg = f"⚠️ Το AI μπλόκαρε την απάντηση. Λόγος: {response.prompt_feedback}"
                                st.error(error_msg)
                                success = True # Σταματάμε το loop για να μην ξαναπροσπαθήσει άσκοπα
                                break
                            else:
                                raise Exception("Empty response without feedback")

                        st.markdown(response.text)
                        st.session_state.messages.append({"role": "assistant", "content": response.text})
                        success = True
                        break 
                        
                    except exceptions.ResourceExhausted:
                        wait = 3 * (attempt + 1)
                        st.toast(f"⏳ Φόρτος δικτύου... Δοκιμή {attempt+1}/{retry_attempts} σε {wait}s")
                        time.sleep(wait)
                        continue
                    except Exception as e:
                        # Αν είναι το τελευταίο attempt, εμφάνισε το λάθος
                        if attempt == retry_attempts - 1:
                            st.error(f"Σφάλμα: {e}")
                        time.sleep(1) # Μικρή καθυστέρηση πριν την επόμενη προσπάθεια
                
                if not success and not response.prompt_feedback:
                    st.error("❌ Το σύστημα δεν μπόρεσε να απαντήσει.")
