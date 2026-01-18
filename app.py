import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
from googleapiclient.errors import HttpError # Add this import at the top if missing
from huggingface_hub import HfApi
import io
import random

# --- CONFIGURATION ---
# We load secrets from Streamlit's secret manager (works on Local & Cloud)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_google_creds():
    # This helps us run locally using the file, or on cloud using the secrets manager
    if "gcp_service_account" in st.secrets:
        return ServiceAccountCredentials.from_json_keyfile_dict(
            dict(st.secrets["gcp_service_account"]), SCOPES
        )
    else:
        # Local fallback
        return ServiceAccountCredentials.from_json_keyfile_name("secrets.json", SCOPES)

def get_drive_service(creds):
    return build('drive', 'v3', credentials=creds)

# --- BACKEND LOGIC ---

def get_next_sentence(region):
    creds = get_google_creds()
    client = gspread.authorize(creds)
    
    # Open the Sheet (Change name if needed)
    sheet = client.open("Dialect_Database").sheet1
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

    # FILTER: Match Region AND Count < Target
    # explicit conversion to int ensures comparison works
    mask = (df['region'] == region) & (df['recording_count'] < df['target_count'])
    available_sentences = df[mask]

    if available_sentences.empty:
        return None, None
    
    # Randomly pick one to avoid collisions
    selected = available_sentences.sample(1).iloc[0]
    return selected['sentence_text'], selected['id']



def upload_to_hf(audio_bytes, filename):
    try:
        api = HfApi(token=st.secrets["HF_TOKEN"])
        repo_id = st.secrets["HF_REPO"]
        
        # This uploads the file directly to your dataset repo
        api.upload_file(
            path_or_fileobj=io.BytesIO(audio_bytes),
            path_in_repo=f"audio/{filename}", # Saves in an 'audio' folder
            repo_id=repo_id,
            repo_type="dataset"
        )
        return True
    except Exception as e:
        st.error(f"Upload failed: {e}")
        return False

def update_sheet_count(sentence_id):
    creds = get_google_creds()
    client = gspread.authorize(creds)
    sheet = client.open("Dialect_Database").sheet1
    
    # Find the cell to update. 
    # NOTE: This is slow for massive sheets, but fine for <5000 rows.
    cell = sheet.find(str(sentence_id))
    # The count is in column 4 (D), so we update row=cell.row, col=4
    current_val = int(sheet.cell(cell.row, 4).value)
    sheet.update_cell(cell.row, 4, current_val + 1)

# --- FRONTEND (UI) ---

st.set_page_config(page_title="Dialect Recorder", layout="centered")

# 1. Get Region from URL (e.g. ?region=barisal)
params = st.query_params
region = params.get("region", None)

if not region:
    st.error("No region specified! Use the link provided by your admin.")
    st.stop()

# 2. Session State Management
if 'current_text' not in st.session_state:
    text, s_id = get_next_sentence(region)
    st.session_state.current_text = text
    st.session_state.current_id = s_id

# 3. The Interface
if st.session_state.current_text is None:
    st.success("🎉 All sentences for this region are finished! Thank you!")
else:
    st.progress(50, text="Community Progress") # You can make this dynamic later
    
    st.markdown(f"### Read this in **{region.capitalize()}** dialect:")
    
    # Big Box for Text
    st.info(f"### 🗣️ {st.session_state.current_text}")
    
    # The Recorder
    audio_value = st.audio_input("Record")

    if audio_value:
        # Check length (rough estimate: 1 sec of wav is huge, check bytes)
        if audio_value.getbuffer().nbytes < 5000: 
            st.warning("Audio too short! Please try again.")
        else:
            if st.button("Submit Recording"):
                with st.spinner("Saving..."):
                    # 1. Generate Filename
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    fname = f"{region}_{st.session_state.current_id}_{timestamp}.wav"
                    
                    # 2. Upload (CHECK IF SUCCESSFUL)
                    upload_success = upload_to_hf(audio_value.read(), fname)
                    
                    if upload_success:
                        # 3. Only Update Sheet if Upload Worked
                        update_sheet_count(st.session_state.current_id)
                        
                        st.toast("Saved! Loading next...", icon="✅")
                        
                        # 4. Reset for next
                        text, s_id = get_next_sentence(region)
                        st.session_state.current_text = text
                        st.session_state.current_id = s_id
                        st.rerun()
                    else:
                        # If upload failed, do NOT update sheet, do NOT rerun.
                        # The error message from upload_to_hf function will stay visible.
                        pass



