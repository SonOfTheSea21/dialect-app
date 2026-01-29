import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from huggingface_hub import HfApi
from datetime import datetime
import pytz # NEW IMPORT FOR TIMEZONE
import io

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

    region_mask = (df['region'] == region)
    pending_mask = (df['recording_count'] < df['target_count'])
    
    # Priority 1: Test
    test_mask = (df['split'] == 'test')
    available_test = df[region_mask & pending_mask & test_mask]
    
    if not available_test.empty:
        return available_test.sample(1).iloc[0]
        
    # Priority 2: Train
    train_mask = (df['split'] == 'train')
    available_train = df[region_mask & pending_mask & train_mask]
    
    if not available_train.empty:
        return available_train.sample(1).iloc[0]
        
    return None

def get_user_stats(user_id):
    try:
        creds = get_google_creds()
        client = gspread.authorize(creds)
        sheet = client.open("Dialect_Database").worksheet("User_Stats")
        cell = sheet.find(user_id)
        return int(sheet.cell(cell.row, 2).value)
    except:
        return 0

def update_global_and_user_stats(global_id, user_id):
    creds = get_google_creds()
    client = gspread.authorize(creds)
    spreadsheet = client.open("Dialect_Database")
    
    # 1. Update Global
    sheet_data = spreadsheet.sheet1
    cell_s = sheet_data.find(str(global_id))
    current_s_val = int(sheet_data.cell(cell_s.row, 6).value)
    sheet_data.update_cell(cell_s.row, 6, current_s_val + 1)
    
    # 2. Update User (With DHAKA Time)
    sheet_users = spreadsheet.worksheet("User_Stats")
    
    # Get Dhaka Time
    dhaka_tz = pytz.timezone('Asia/Dhaka')
    current_time = datetime.now(dhaka_tz).strftime("%Y-%m-%d %H:%M:%S")

    try:
        cell_u = sheet_users.find(user_id)
        current_u_val = int(sheet_users.cell(cell_u.row, 2).value)
        sheet_users.update_cell(cell_u.row, 2, current_u_val + 1)
        sheet_users.update_cell(cell_u.row, 3, current_time)
    except:
        sheet_users.append_row([user_id, 1, current_time])

def upload_to_hf(audio_bytes, filename, dataset_source, split, region):
    try:
        api = HfApi(token=st.secrets["HF_TOKEN"])
        repo_id = st.secrets["HF_REPO"]
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
        
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

# --- CUSTOM CSS FOR BIGGER & CENTERED UI ---
st.markdown("""
<style>
    /* 1. Center the Audio Widget and Make it Bigger */
    div[data-testid="stAudioInput"] {
        margin: 0 auto !important; /* Center horizontally */
        width: 100% !important; /* Full width of the column */
        transform: scale(1.2); /* Make it 20% bigger */
        transform-origin: center top;
        margin-bottom: 20px !important;
    }

    /* 2. Center the Submit Button */
    div[data-testid="stButton"] {
        display: flex;
        justify-content: center;
        margin-top: 20px;
    }
    
    /* 3. Style the Text Prompt Box */
    .stAlert {
        text-align: center;
        font-size: 1.2rem;
    }
</style>
""", unsafe_allow_html=True)

# 1. URL Params
params = st.query_params
region = params.get("region", None)
user_id = params.get("user", "guest")

if not region:
    st.title("🇧🇩 Dialect Collection Project")
    st.write("Please use your assigned link.")
    st.stop()

if 'current_data' not in st.session_state:
    row = get_next_sentence(region)
    st.session_state.current_data = row

if 'user_db_count' not in st.session_state:
    st.session_state.user_db_count = get_user_stats(user_id)
    st.session_state.session_adds = 0 

total_user_score = st.session_state.user_db_count + st.session_state.session_adds

if st.session_state.current_data is None:
    st.balloons()
    st.success("🎉 All sentences for this region are finished!")
else:
    row = st.session_state.current_data
    current_text = row['sentence_text']
    current_id = str(row['global_id'])
    current_split = row['split']
    current_dataset = row['dataset_source']

    # Progress Bar
    next_milestone = 100 * ((total_user_score // 100) + 1)
    progress_percent = min(1.0, (total_user_score % 100) / 100)
    if total_user_score > 0 and total_user_score % 100 == 0:
        progress_percent = 1.0

    st.markdown(f"**Volunteer:** `{user_id}`")
    st.progress(progress_percent, text=f"Total: {total_user_score} / {next_milestone}")
    
    st.markdown(f"<h3 style='text-align: center;'>Read in {region.capitalize()}:</h3>", unsafe_allow_html=True)
    st.info(f"### {current_text}")
    
    # --- CENTERED RECORDER LAYOUT ---
    # We use columns to force centering because CSS transform can sometimes be tricky
    col1, col2, col3 = st.columns([1, 6, 1])
    
    with col2:
        audio_value = st.audio_input("Record", key=f"rec_{current_id}")
        
        if audio_value:
            if audio_value.getbuffer().nbytes < 5000: 
                st.warning("Audio too short.")
            else:
                # This button will now be centered by the CSS above
                if st.button("Submit Recording", type="primary"):
                    with st.spinner("Saving..."):
                        # FIX: Timezone for Filename
                        dhaka_tz = pytz.timezone('Asia/Dhaka')
                        timestamp = datetime.now(dhaka_tz).strftime("%Y%m%d_%H%M%S")
                        
                        fname = f"{current_dataset}_{region}_{current_split}_{current_id}_{user_id}_{timestamp}.wav"
                        
                        success = upload_to_hf(
                            audio_value.read(), 
                            fname, 
                            current_dataset, 
                            current_split, 
                            region
                        )
                        
                        if success:
                            update_global_and_user_stats(current_id, user_id)
                            st.session_state.session_adds += 1
                            st.toast("Saved! Loading next...", icon="✅")
                            
                            st.session_state.current_data = get_next_sentence(region)
                            st.rerun()
