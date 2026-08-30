import os
# os.environ["CUDA_VISIBLE_DEVICES"] = "-1" # Uncomment if you want to force CPU
import sys
import numpy as np
import cv2
import tensorflow as tf
from tensorflow.keras import backend as K
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoAlertPresentException, UnexpectedAlertPresentException
import time
import pandas as pd
# BeautifulSoup is not needed for this version, but we'll need it later
# from bs4 import BeautifulSoup 

# --- Configuration ---
VTU_RESULTS_URL = "https://results.vtu.ac.in/JJEcbcs25/index.php"
MODEL_FILE = "vtu_captcha_predictor.h5" # <-- UPDATE THIS TO YOUR BEST MODEL
INPUT_CSV = "students.csv"
# OUTPUT_EXCEL = "vtu_results.xlsx" # Not used in this version
MAX_CAPTCHA_ATTEMPTS = 5

# --- Model Constants (MUST MATCH train.py) ---
IMG_WIDTH = 160
IMG_HEIGHT = 75
CHARACTERS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_LENGTH = 6
num_to_char = {i: char for i, char in enumerate(CHARACTERS)}
# -------------------------------------------


# --- Helper Function 1: Preprocessing (From your solve.py file) ---
def preprocess_image(img_path):
    """Loads and preprocesses a HORIZONTAL image with cleaning."""
    try:
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        if img is None: raise Exception("Image is None (corrupted file?)")
        
        # --- Preprocessing steps from your solve.py ---
        # 1. Blur
        img = cv2.GaussianBlur(img, (5, 5), 0)
        # 2. Threshold (Otsu)
        _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # --------------------------------------------------------

        # 3. Resize
        img = cv2.resize(img, (IMG_WIDTH, IMG_HEIGHT))
        # 4. Normalize
        img = img / 255.0
        # 5. Add channel dimension
        img = np.expand_dims(img, axis=-1)
        # 6. Add batch dimension for prediction
        img = np.expand_dims(img, axis=0) 
        return img
    except Exception as e:
        print(f"  [Error] Preprocessing failed: {e}", file=sys.stderr)
        return None

# --- Helper Function 2: Decoding (From solve.py) ---
def decode_prediction(pred):
    """Decodes the raw model output (CTC) into a string."""
    input_len = np.ones(pred.shape[0]) * pred.shape[1]
    results = K.ctc_decode(pred, input_length=input_len, greedy=True)[0][0]
    output_text = ""
    for num in results[0]:
        num = num.numpy()
        if num == -1: break
        if num < len(num_to_char):
            output_text += num_to_char[num]
    return output_text[:MAX_LENGTH]

# --- Helper Function 3: Scrape Results (NOT USED IN THIS VERSION) ---
# We will write this function *after* you provide the HTML output
def scrape_results_page(page_source, usn):
    print(f"  [Info] Skipping scraping for now.")
    return []

# --- Main Automation ---
def main():
    # 1. Load USN list
    try:
        usn_df = pd.read_csv(INPUT_CSV)
        if "USN" not in usn_df.columns:
            print(f"Error: Input CSV '{INPUT_CSV}' must have a column named 'USN'."); return
        usn_list = usn_df["USN"].str.strip().str.upper().tolist()
        print(f"Loaded {len(usn_list)} USNs from '{INPUT_CSV}'.")
    except FileNotFoundError: print(f"Error: Input file not found: '{INPUT_CSV}'"); return
    except Exception as e: print(f"Error reading CSV: {e}"); return

    # 2. Load the trained model
    print(f"Loading model from {MODEL_FILE}...")
    try:
        model = tf.keras.models.load_model(MODEL_FILE)
        model.summary()
    except Exception as e: print(f"Error loading model: {e}"); return
        
    # 3. Set up Selenium
    print("Starting browser...")
    try:
        service = Service() 
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless")
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e: print(f"Error starting Selenium WebDriver: {e}"); return

    # all_student_results = [] # Not used
    failed_usns = []

    # 4. --- Main Loop ---
    try:
        for usn in usn_list:
            print(f"\n--- Processing USN: {usn} ---")
            success = False
            driver.get(VTU_RESULTS_URL)
            wait = WebDriverWait(driver, 10)
            
            for attempt in range(MAX_CAPTCHA_ATTEMPTS):
                print(f"  [Attempt {attempt + 1}/{MAX_CAPTCHA_ATTEMPTS}]")
                try:
                    # 5. Find elements
                    usn_box = wait.until(EC.presence_of_element_located((By.NAME, "lns")))
                    captcha_box = driver.find_element(By.NAME, "captchacode")
                    captcha_image = driver.find_element(By.XPATH, "//img[contains(@src, 'vtu_captcha.php')]")
                    submit_button = driver.find_element(By.ID, "submit")
                    
                    # 6. Enter USN
                    usn_box.clear(); captcha_box.clear()
                    usn_box.send_keys(usn)
                    
                    # 7. Solve CAPTCHA
                    print("  [Info] Solving CAPTCHA...")
                    captcha_screenshot_path = "captcha_screenshot.png"
                    captcha_image.screenshot(captcha_screenshot_path)
                    
                    image_data = preprocess_image(captcha_screenshot_path)
                    if image_data is None: 
                        print("  [Warn] Preprocessing failed, refreshing..."); 
                        driver.refresh(); continue
                        
                    prediction = model.predict(image_data, verbose=0)
                    solved_text = decode_prediction(prediction)
                    print(f"  [Info] Model Predicted: '{solved_text}'")
                    
                    # 8. Submit
                    captcha_box.send_keys(solved_text)
                    current_url = driver.current_url
                    submit_button.click()
                    
                    # 9. Check for success (URL change)
                    WebDriverWait(driver, 5).until(EC.url_changes(current_url))
                    
                    # URL changed! Check if it's a success page or failure alert
                    try:
                        # Check for "Invalid Captcha" or other alerts on the *new* page
                        alert_wait = WebDriverWait(driver, 2)
                        alert = alert_wait.until(EC.alert_is_present())
                        alert_text = alert.text
                        print(f"  [Fail] Alert detected on new page: '{alert_text}'.")
                        alert.accept()
                        
                        if "results" in alert_text.lower() and "not found" in alert_text.lower():
                            print(f"  [Info] Results not found for {usn}. Skipping.")
                            success = False; break 
                        else:
                            print("  [Info] CAPTCHA was incorrect. Going back to retry...")
                            driver.get(VTU_RESULTS_URL); continue 

                    except (TimeoutException, NoAlertPresentException):
                        # --- [MODIFIED] SUCCESS BLOCK ---
                        # NO alert! This is TRUE success!
                        print(f"  [Success] CAPTCHA cracked for {usn}! Saving page HTML...")
                        success = True
                        
                        # 10. Save the page source
                        html_filename = "result_page.html"
                        with open(html_filename, "w", encoding="utf-8") as f:
                            f.write(driver.page_source)
                        print(f"  [Info] Successfully saved results page to '{html_filename}'.")
                        print("  [Info] Exiting script as requested.")
                        break # Success, exit retry loop
                        # ---------------------------------

                except TimeoutException:
                    # (Error handling remains the same)
                    print("  [Fail] URL did not change. Handling alert.")
                    try:
                        alert = wait.until(EC.alert_is_present()) 
                        print(f"  [Info] Alert detected: '{alert.text}'. Clicking 'OK'.")
                        alert.accept()
                    except (TimeoutException, NoAlertPresentException):
                        print("  [Info] No alert box found. Refreshing CAPTCHA.")
                    try:
                        refresh_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//img[contains(@src, 'refresh.png')]")))
                        refresh_button.click(); time.sleep(1)
                    except Exception:
                        print("  [Warn] Could not refresh CAPTCHA, forcing page reload."); driver.refresh()

                except UnexpectedAlertPresentException as e:
                    # (Error handling remains the same)
                    print(f"  [Fail] Unexpected alert blocked operation: {e.alert_text}")
                    try:
                        alert = driver.switch_to.alert; alert.accept()
                    except NoAlertPresentException: pass 
                    try:
                        refresh_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//img[contains(@src, 'refresh.png')]")))
                        refresh_button.click(); time.sleep(1)
                    except Exception:
                        print("  [Warn] Could not refresh CAPTCHA, forcing page reload."); driver.refresh()
                
                except Exception as e:
                    # (Error handling remains the same)
                    print(f"  [Error] An unexpected error occurred on attempt {attempt + 1}: {e}")
                    try: alert = driver.switch_to.alert; alert.accept() 
                    except NoAlertPresentException: pass
                    driver.refresh(); time.sleep(1)
            
            if not success:
                print(f"--- [FAILED] Could not fetch results for USN: {usn} ---")
                failed_usns.append(usn)
                
            # --- [NEW] Exit outer loop on success ---
            if success:
                break
            # ------------------------------------------
                
    except Exception as e:
        print(f"\nA fatal error occurred during the main loop: {e}")
        try:
            alert = driver.switch_to.alert; alert.accept()
        except NoAlertPresentException:
            pass
    finally:
        print("\nClosing browser.")
        driver.quit()

    # --- [MODIFIED] No Excel saving in this version ---
    print("\n--- Script Finished ---")
    if failed_usns:
        print("The following USNs failed before a successful attempt:")
        for usn in failed_usns:
            print(f"  - {usn}")

if __name__ == "__main__":
    main()
