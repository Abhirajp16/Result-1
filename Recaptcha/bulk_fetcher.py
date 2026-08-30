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
# --- [ENABLED] Import BeautifulSoup ---
from bs4 import BeautifulSoup 

# --- Configuration ---
VTU_RESULTS_URL = "https://results.vtu.ac.in/JJEcbcs25/index.php"
MODEL_FILE = "vtu_captcha_predictor.h5" # <-- UPDATE THIS TO YOUR BEST MODEL
INPUT_CSV = "students.csv"
OUTPUT_EXCEL = "vtu_results.xlsx" # <-- [ENABLED]
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

# --- [MODIFIED] Helper Function 3: Scrape Results ---
# This function is now built to parse your result_page.html
def scrape_results_page(page_source, usn):
    """Parses the HTML of the results page and extracts subject data."""
    print(f"  [Info] Scraping results for {usn}...")
    soup = BeautifulSoup(page_source, 'html.parser')
    results_data = []
    
    try:
        # Find the div containing the subject table body
        table_body = soup.find('div', {'class': 'divTableBody'})
        
        if not table_body:
            print(f"  [Error] Could not find 'divTableBody' for {usn}.")
            return []

        # Find all rows in the table
        rows = table_body.find_all('div', {'class': 'divTableRow'})
        
        # Loop through all rows, skipping the header
        for row in rows:
            # Find all cells in the row
            cols = row.find_all('div', {'class': 'divTableCell'})
            
            # Check if this is a data row (header row won't have 7 cells in this exact format)
            # and that it's not the header (by checking text)
            if len(cols) == 7 and "Subject Code" not in cols[0].text:
                subject_code = cols[0].text.strip()
                subject_name = cols[1].text.strip()
                internal_marks = cols[2].text.strip()
                external_marks = cols[3].text.strip()
                total_marks = cols[4].text.strip()
                result = cols[5].text.strip()
                updated_on = cols[6].text.strip()
                
                # Add to our list
                results_data.append({
                    "USN": usn,
                    "Subject Code": subject_code,
                    "Subject Name": subject_name,
                    "Internal Marks": internal_marks,
                    "External Marks": external_marks,
                    "Total Marks": total_marks,
                    "Result": result,
                    "Announced / Updated on": updated_on
                })
        
        if not results_data:
             print(f"  [Warn] Found table, but no subject data was parsed for {usn}.")
        else:
             print(f"  [Info] Found {len(results_data)} subjects for {usn}.")
        return results_data

    except Exception as e:
        print(f"  [Error] Scraping failed for {usn}: {e}")
        return []
# ----------------------------------------------------

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

    all_student_results = [] # <-- [ENABLED] List to store all data
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
                        print(f"  [Success] CAPTCHA cracked for {usn}! Scraping page...")
                        success = True
                        
                        # 10. Scrape the data
                        student_data = scrape_results_page(driver.page_source, usn)
                        if student_data:
                            all_student_results.extend(student_data)
                        else:
                            print(f"  [Warn] Successfully loaded page, but no data was scraped for {usn}.")
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
            
            # --- [NEW] SAVE PROGRESS AFTER EACH STUDENT ---
            if all_student_results: # Check if there is anything to save
                print(f"  [Info] Saving progress ({len(all_student_results)} subject entries) to {OUTPUT_EXCEL}...")
                try:
                    results_df = pd.DataFrame(all_student_results)
                    results_df = results_df[["USN", "Subject Code", "Subject Name", "Internal Marks", "External Marks", "Total Marks", "Result", "Announced / Updated on"]]
                    results_df.to_excel(OUTPUT_EXCEL, index=False)
                    print("  [Info] Progress saved.")
                except Exception as e:
                    print(f"  [Warn] Could not save progress to Excel: {e}")
            # ---------------------------------------------
                
    except Exception as e:
        print(f"\nA fatal error occurred during the main loop: {e}")
        try:
            alert = driver.switch_to.alert; alert.accept()
        except NoAlertPresentException:
            pass
    finally:
        print("\nClosing browser.")
        driver.quit()

    # --- [MODIFIED] Final Save / Summary Message ---
    print(f"\n--- Script Finished ---")
    if all_student_results:
        print(f"Final results for {len(all_student_results)} subject entries are saved in '{OUTPUT_EXCEL}'.")
    else:
        print("No results were fetched to save.")

    if failed_usns:
        print("\nThe following USNs failed after all attempts:")
        for usn in failed_usns:
            print(f"  - {usn}")
    # -----------------------------------------

if __name__ == "__main__":
    main()
