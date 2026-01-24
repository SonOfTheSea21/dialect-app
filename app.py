import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from huggingface_hub import HfApi
from datetime import datetime
import io
import random

# --- CONFIGURATION ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_google_creds():
    if "gcp_service_account" in st.secrets:
        return ServiceAccountCredentials.from_json_keyfile_dict(
            dict(st.secrets["gcp_service_account"]), SCOPES
        )
    else:
        return ServiceAccountCredentials.from_json_keyfile_name("secrets.json", SCOPES)

# --- BACKEND LOGIC ---

def get_next_sentence(region):
    creds = get_google_creds()
    client = gspread.authorize(creds)
    sheet = client.open("Dialect_Database").sheet1
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

    mask = (df['region'] == region) & (df['recording_count'] < df['target_count'])
    available_sentences = df[mask]

    if available_sentences.empty:
        return None, None
    
    selected = available_sentences.sample(1).iloc[0]
    return selected['sentence_text'], selected['id']

def get_user_stats(user_id):
    """Checks the User_Stats sheet for the user's total count."""
    try:
        creds = get_google_creds()
        client = gspread.authorize(creds)
        # Open the SECOND tab called 'User_Stats'
        sheet = client.open("Dialect_Database").worksheet("User_Stats")
        
        try:
            cell = sheet.find(user_id)
            # Count is in column 2 (B)
            return int(sheet.cell(cell.row, 2).value)
        except:
            # If user not found, they are new. Return 0.
            return 0
    except Exception as e:
        # Fallback if sheet is busy/error
        return 0

def update_global_and_user_stats(sentence_id, user_id):
    """Updates BOTH the sentence count and the user's personal count."""
    creds = get_google_creds()
    client = gspread.authorize(creds)
    spreadsheet = client.open("Dialect_Database")
    
    # 1. Update Global Sentence Count (Sheet 1)
    sheet_sentences = spreadsheet.sheet1
    cell_s = sheet_sentences.find(str(sentence_id))
    current_s_val = int(sheet_sentences.cell(cell_s.row, 4).value)
    sheet_sentences.update_cell(cell_s.row, 4, current_s_val + 1)
    
    # 2. Update Personal User Count (Sheet 2)
    sheet_users = spreadsheet.worksheet("User_Stats")
    
    try:
        # Try to find existing user
        cell_u = sheet_users.find(user_id)
        current_u_val = int(sheet_users.cell(cell_u.row, 2).value)
        sheet_users.update_cell(cell_u.row, 2, current_u_val + 1)
        # Update timestamp in col 3
        sheet_users.update_cell(cell_u.row, 3, str(datetime.now()))
        
    except:
        # New user! Add a new row.
        sheet_users.append_row([user_id, 1, str(datetime.now())])

def upload_to_hf(audio_bytes, filename):
    try:
        api = HfApi(token=st.secrets["HF_TOKEN"])
        repo_id = st.secrets["HF_REPO"]
        
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
        
        api.upload_file(
            path_or_fileobj=io.BytesIO(audio_bytes),
            path_in_repo=f"audio/{filename}",
            repo_id=repo_id,
            repo_type="dataset"
        )
        return True
    except Exception as e:
        st.error(f"Upload failed: {e}")
        return False

# --- FRONTEND (UI) ---

st.set_page_config(page_title="Dialect Recorder", layout="centered")

# 1. Get Params from URL
params = st.query_params
region = params.get("region", None)
user_id = params.get("user", "guest") # Default to 'guest' if no link used

if not region:
    st.error("Missing Region! Use the full link.")
    st.stop()

# 2. Initialize Session
if 'current_text' not in st.session_state:
    text, s_id = get_next_sentence(region)
    st.session_state.current_text = text
    st.session_state.current_id = s_id

# 3. Fetch Persistent User Score (Only once on load)
if 'user_db_count' not in st.session_state:
    st.session_state.user_db_count = get_user_stats(user_id)
    # We also keep a session counter to update UI instantly without re-fetching DB every time
    st.session_state.session_adds = 0 

# Total Score = DB Score + Session Score
total_user_score = st.session_state.user_db_count + st.session_state.session_adds

# 4. Interface
if st.session_state.current_text is None:
    st.balloons()
    st.success("🎉 All sentences for this region are finished! Thank you!")
else:
    # --- PROGRESS BAR ---
    next_milestone = 100 * ((total_user_score // 100) + 1)
    progress_percent = min(1.0, (total_user_score % 100) / 100)
    if total_user_score > 0 and total_user_score % 100 == 0:
        progress_percent = 1.0

    st.markdown(f"**Volunteer:** `{user_id}`")
    st.progress(progress_percent, text=f"Your Total Contribution: {total_user_score} / {next_milestone}")
    
    st.markdown(f"### Read this in **{region.capitalize()}** dialect:")
    st.info(f"### 🗣️ {st.session_state.current_text}")
    
    # Recoder with dynamic key
    audio_value = st.audio_input("Record", key=f"rec_{st.session_state.current_id}")

    if audio_value:
        if audio_value.getbuffer().nbytes < 5000: 
            st.warning("Audio too short.")
        else:
            if st.button("Submit Recording"):
                with st.spinner("Saving..."):
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    # Filename now includes USER_ID for credit
                    fname = f"{region}_{user_id}_{st.session_state.current_id}_{timestamp}.wav"
                    
                    if upload_to_hf(audio_value.read(), fname):
                        
                        # UPDATE BOTH SHEETS
                        update_global_and_user_stats(st.session_state.current_id, user_id)
                        
                        st.session_state.session_adds += 1
                        st.toast("Saved! Loading next...", icon="✅")
                        
                        text, s_id = get_next_sentence(region)
                        st.session_state.current_text = text
                        st.session_state.current_id = s_id
                        st.rerun()
