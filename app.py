import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from huggingface_hub import HfApi
from datetime import datetime
import io

# --- CONFIGURATION ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_google_creds():
    """Handles authentication for both Local and Cloud environments."""
    if "gcp_service_account" in st.secrets:
        return ServiceAccountCredentials.from_json_keyfile_dict(
            dict(st.secrets["gcp_service_account"]), SCOPES
        )
    else:
        # Local fallback if you have the file
        return ServiceAccountCredentials.from_json_keyfile_name("secrets.json", SCOPES)

# --- BACKEND LOGIC ---

def get_next_sentence(region):
    """
    Priority Logic:
    1. Look for available 'test' sentences first.
    2. If all 'test' are done, look for 'train' sentences.
    """
    creds = get_google_creds()
    client = gspread.authorize(creds)
    sheet = client.open("Dialect_Database").sheet1
    
    # Fetch all data
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

    # Filter 1: Match the Region
    region_mask = (df['region'] == region)
    
    # Filter 2: Only rows that need recording (count < target)
    pending_mask = (df['recording_count'] < df['target_count'])
    
    # --- PRIORITY 1: CHECK TEST SPLIT ---
    test_mask = (df['split'] == 'test')
    available_test = df[region_mask & pending_mask & test_mask]
    
    if not available_test.empty:
        # Pick a random Test sentence
        selected = available_test.sample(1).iloc[0]
        return selected
        
    # --- PRIORITY 2: CHECK TRAIN SPLIT ---
    # We only reach here if available_test is empty
    train_mask = (df['split'] == 'train')
    available_train = df[region_mask & pending_mask & train_mask]
    
    if not available_train.empty:
        # Pick a random Train sentence
        selected = available_train.sample(1).iloc[0]
        return selected
        
    return None # Region is 100% complete

def get_user_stats(user_id):
    """Fetches user's total count from Sheet 2."""
    try:
        creds = get_google_creds()
        client = gspread.authorize(creds)
        sheet = client.open("Dialect_Database").worksheet("User_Stats")
        
        try:
            cell = sheet.find(user_id)
            # Count is in column 2 (B)
            return int(sheet.cell(cell.row, 2).value)
        except:
            return 0 # New user
    except:
        return 0

def update_global_and_user_stats(global_id, user_id):
    """Updates the main sheet count and the user's personal stats."""
    creds = get_google_creds()
    client = gspread.authorize(creds)
    spreadsheet = client.open("Dialect_Database")
    
    # 1. Update Global Sheet (Sheet1)
    sheet_data = spreadsheet.sheet1
    cell_s = sheet_data.find(str(global_id))
    # 'recording_count' is column F (6)
    current_s_val = int(sheet_data.cell(cell_s.row, 6).value)
    sheet_data.update_cell(cell_s.row, 6, current_s_val + 1)
    
    # 2. Update User Sheet (User_Stats)
    sheet_users = spreadsheet.worksheet("User_Stats")
    try:
        cell_u = sheet_users.find(user_id)
        current_u_val = int(sheet_users.cell(cell_u.row, 2).value)
        sheet_users.update_cell(cell_u.row, 2, current_u_val + 1)
        sheet_users.update_cell(cell_u.row, 3, str(datetime.now())) # Timestamp
    except:
        # New user: Add row [user_id, 1, timestamp]
        sheet_users.append_row([user_id, 1, str(datetime.now())])

def upload_to_hf(audio_bytes, filename, dataset_source, split, region):
    """
    Uploads file to specific folder: split/dataset_source/region/filename
    """
    try:
        api = HfApi(token=st.secrets["HF_TOKEN"])
        repo_id = st.secrets["HF_REPO"]
        
        # Create Repo if missing (One-time safety)
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
        
        # Construct the folder path structure you requested
        # e.g. "test/Vashantor/Barisal/file.wav"
        folder_path = f"{split}/{dataset_source}/{region}/{filename}"
        
        api.upload_file(
            path_or_fileobj=io.BytesIO(audio_bytes),
            path_in_repo=folder_path,
            repo_id=repo_id,
            repo_type="dataset"
        )
        return True
    except Exception as e:
        st.error(f"Upload failed: {e}")
        return False

# --- FRONTEND (UI) ---

st.set_page_config(page_title="Dialect Recorder", layout="centered")

# 1. URL Parameter Handling
params = st.query_params
region = params.get("region", None)
user_id = params.get("user", "guest")

# 2. Landing Page (If no link used)
if not region:
    st.title("🇧🇩 Dialect Collection Project")
    st.write("Please use the specific link assigned to you.")
    st.info("Example: .../?region=barisal&user=yourname")
    st.stop()

# 3. Session State Initialization
if 'current_data' not in st.session_state:
    # We store the whole row series so we can access split/dataset/id later
    row = get_next_sentence(region)
    st.session_state.current_data = row # Store the whole row object or None

# 4. User Stats Initialization (Run once)
if 'user_db_count' not in st.session_state:
    st.session_state.user_db_count = get_user_stats(user_id)
    st.session_state.session_adds = 0 

# Calculate Score
total_user_score = st.session_state.user_db_count + st.session_state.session_adds

# 5. Main Interface Loop
if st.session_state.current_data is None:
    st.balloons()
    st.success("🎉 All sentences for this region are finished! Great job!")
else:
    # Extract data for easy reading
    row = st.session_state.current_data
    current_text = row['sentence_text']
    current_id = str(row['global_id'])
    current_split = row['split']
    current_dataset = row['dataset_source']

    # --- PROGRESS BAR ---
    next_milestone = 100 * ((total_user_score // 100) + 1)
    progress_percent = min(1.0, (total_user_score % 100) / 100)
    if total_user_score > 0 and total_user_score % 100 == 0:
        progress_percent = 1.0

    st.markdown(f"**Volunteer:** `{user_id}`")
    st.progress(progress_percent, text=f"Your Total Contribution: {total_user_score} / {next_milestone}")
    
    # --- PROMPT AREA ---
    st.markdown(f"### Read this in **{region.capitalize()}** dialect:")
    
    # Debug info (Optional: Helps you verify Test vs Train priority)
    # st.caption(f"Debug: {current_dataset} | {current_split} | {current_id}")
    
    st.info(f"### 🗣️ {current_text}")
    st.warning("⚠️ Please keep your screen ON while recording.")

    # --- RECORDER ---
    # Key is dynamic to force reset on new sentence
    audio_value = st.audio_input("Record", key=f"rec_{current_id}")

    if audio_value:
        if audio_value.getbuffer().nbytes < 5000: 
            st.warning("Audio too short.")
        else:
            if st.button("Submit Recording"):
                with st.spinner("Saving..."):
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    # Filename: Vashantor_Barisal_train_id123_rakib_time.wav
                    fname = f"{current_dataset}_{region}_{current_split}_{current_id}_{user_id}_{timestamp}.wav"
                    
                    # Upload using the NEW folder structure logic
                    success = upload_to_hf(
                        audio_value.read(), 
                        fname, 
                        current_dataset, 
                        current_split, 
                        region
                    )
                    
                    if success:
                        # Update Database
                        update_global_and_user_stats(current_id, user_id)
                        
                        # Update Local Session
                        st.session_state.session_adds += 1
                        st.toast("Saved! Loading next...", icon="✅")
                        
                        # Fetch NEXT sentence (Will prioritize Test again if available)
                        new_row = get_next_sentence(region)
                        st.session_state.current_data = new_row
                        
                        st.rerun()
