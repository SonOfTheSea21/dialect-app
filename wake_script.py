from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import os
import time

# Get URL from GitHub Secrets or fall back to your hardcoded link
STREAMLIT_URL = os.environ.get("STREAMLIT_APP_URL", "https://dialect-app.streamlit.app")

def main():
    print(f"Starting wake-up routine for: {STREAMLIT_URL}")
    
    # 1. Setup Chrome Options (Headless = No GUI)
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    
    driver = webdriver.Chrome(options=options)

    try:
        driver.get(STREAMLIT_URL)
        print("Page loaded. Checking for 'Yes, get this app back up' button...")

        # 2. Wait up to 15 seconds for the button
        wait = WebDriverWait(driver, 15)
        
        try:
            # Look for the specific button Streamlit uses when sleeping
            button = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Yes, get this app back up')]"))
            )
            print("💤 App is sleeping. Clicking wake button...")
            button.click()
            
            # Wait to ensure the click registered
            time.sleep(5)
            print("✅ Wake button clicked. App should be rebooting.")

        except TimeoutException:
            print("✨ No wake button found. The app is likely already awake!")

    except Exception as e:
        print(f"❌ Error occurred: {e}")
        # We don't exit(1) here because we don't want the GitHub Action to mark as 'Failed' 
        # just because the app was already awake.
        
    finally:
        driver.quit()
        print("Script finished.")

if __name__ == "__main__":
    main()
