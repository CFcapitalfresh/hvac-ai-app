# --- FUNCTIONS (ΒΕΛΤΙΩΜΕΝΕΣ ΓΙΑ ΥΠΟΦΑΚΕΛΟΥΣ) ---

def search_drive_by_name(query_text):
    """Αναζητά αρχεία απευθείας στο Drive (Server-side) με βάση λέξεις-κλειδιά"""
    if not drive_service: return []
    
    # Σπάμε την ερώτηση σε λέξεις (π.χ. "Ariston 501" -> "Ariston", "501")
    keywords = [w for w in query_text.split() if len(w) > 2]
    if not keywords: return []

    # Φτιάχνουμε φίλτρο για το Drive: name contains 'word1' AND name contains 'word2'
    # Αυτό ψάχνει ΠΑΝΤΟΥ (φακέλους & υποφακέλους)
    filters = [f"name contains '{k}'" for k in keywords]
    name_query = " and ".join(filters)
    
    try:
        # Αναζήτηση για PDF ή Εικόνες που δεν είναι στα σκουπίδια
        q = f"mimeType != 'application/vnd.google-apps.folder' and trashed = false and ({name_query})"
        
        # Ζητάμε μέχρι 10 αποτελέσματα που ταιριάζουν ακριβώς
        res = drive_service.files().list(q=q, fields="files(id, name)", pageSize=10).execute()
        return res.get('files', [])
    except: 
        return []

def download_file_content(file_id):
    req = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while done is False: _, done = downloader.next_chunk()
    return fh.getvalue()

def find_relevant_file(user_query, files):
    # Αυτή η συνάρτηση πλέον καλεί την από πάνω για πιο έξυπνη αναζήτηση
    # Αν έχουμε ήδη λίστα αρχείων (από την παλιά μέθοδο), την αγνοούμε και ψάχνουμε δυναμικά
    
    found_files = search_drive_by_name(user_query)
    
    if found_files:
        # Επιστρέφουμε το πρώτο (πιο σχετικό) αποτέλεσμα
        return found_files[0]
        
    return None
