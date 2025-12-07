def search_drive_smart(user_query):
    """Πιο επιθετική αναζήτηση στο Drive για να βρίσκει τα πάντα"""
    if not drive_service: return None
    
    # 1. Καθαρισμός: Κρατάμε λέξεις > 2 χαρακτήρες
    keywords = [w.lower() for w in user_query.split() if len(w) > 2]
    if not keywords: return None

    # 2. Στρατηγική: Ψάχνουμε με την ΠΡΩΤΗ λέξη (συνήθως η μάρκα)
    # και φέρνουμε ΠΟΛΛΑ αποτελέσματα (μέχρι 50) για να τα φιλτράρουμε εμείς.
    # Αυτό λύνει το πρόβλημα που το API δεν βρίσκει συνδυασμούς.
    main_keyword = keywords[0] 
    
    try:
        # Ζητάμε αρχεία που το όνομα περιέχει την πρώτη λέξη (π.χ. "Ariston")
        # Ψάχνουμε ΠΑΝΤΟΥ (subfolders)
        q = f"mimeType != 'application/vnd.google-apps.folder' and trashed = false and name contains '{main_keyword}'"
        
        # Φέρνουμε 50 αρχεία για να είμαστε σίγουροι
        res = drive_service.files().list(q=q, fields="files(id, name)", pageSize=50).execute()
        files = res.get('files', [])
        
        if not files:
            # Αν δεν βρει τίποτα με την πρώτη λέξη, δοκιμάζουμε με τη δεύτερη (αν υπάρχει)
            if len(keywords) > 1:
                second_keyword = keywords[1]
                q = f"mimeType != 'application/vnd.google-apps.folder' and trashed = false and name contains '{second_keyword}'"
                res = drive_service.files().list(q=q, fields="files(id, name)", pageSize=50).execute()
                files = res.get('files', [])

        # 3. Εξυπνο Φιλτράρισμα (Python Side)
        # Τώρα που έχουμε τα αρχεία, βαθμολογούμε ποιο ταιριάζει καλύτερα
        best_match = None
        highest_score = 0
        
        for f in files:
            fname = f['name'].lower()
            # Αφαιρούμε καταλήξεις
            fname_clean = fname.replace('.pdf', '').replace('.jpg', '')
            
            score = 0
            # Έλεγχος: Πόσες από τις λέξεις του χρήστη υπάρχουν στο όνομα;
            for k in keywords:
                if k in fname_clean:
                    score += 1
            
            # Αν βρέθηκε λέξη, δίνουμε πόντους. Αν είναι ακριβές ταίριασμα, ακόμα καλύτερα.
            if score > highest_score:
                highest_score = score
                best_match = f
                
            # Αν βρει όλες τις λέξεις, σταματάμε και το επιστρέφουμε
            if score == len(keywords):
                return f

        return best_match

    except Exception as e:
        st.error(f"Search Error: {e}")
        return None
