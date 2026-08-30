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
from bs4 import BeautifulSoup 
# Note: openpyxl is needed by pandas for .xlsx, make sure it's installed
# pip install openpyxl

# --- Configuration ---
VTU_RESULTS_URL = "https://results.vtu.ac.in/JJEcbcs25/index.php"
MODEL_FILE = "vtu_captcha_predictor.h5" # <-- UPDATE THIS TO YOUR BEST MODEL
INPUT_CSV = "students.csv"
RAW_DATA_CSV = "raw_results.csv" # <-- [NEW] Intermediate save file
SUMMARY_DATA_CSV = "raw_summary.csv" # <-- [NEW] Intermediate save file
OUTPUT_EXCEL = "vtu_results.xlsx"
MAX_CAPTCHA_ATTEMPTS = 20
MAX_SUBJECTS = 10 # This is only used for the old "wide" format, but can be left

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

# --- Helper Function 3: Scrape Results ---
def scrape_results_page(page_source):
    """Parses the HTML of the results page and extracts subject data."""
    print(f"  [Info] Scraping results page...")
    soup = BeautifulSoup(page_source, 'html.parser')
    student_info = {}
    results_data = []
    summary_data = {}
    try:
        # --- 1. Scrape Student Info ---
        info_table = soup.find('table', {'class': 'table-condensed'})
        if info_table:
            rows = info_table.find_all('tr')
            if len(rows) >= 2:
                usn = rows[0].find_all('td')[1].text.strip().replace(':', '').strip()
                name = rows[1].find_all('td')[1].text.strip().replace(':', '').strip()
                student_info = {'usn': usn, 'name': name}
        if not student_info:
            print("  [Warn] Could not parse student USN/Name.")
            student_info = {'usn': 'UNKNOWN', 'name': 'UNKNOWN'}

        # --- 2. Scrape Subject Info ---
        table_body = soup.find('div', {'class': 'divTableBody'})
        if not table_body:
            print(f"  [Error] Could not find 'divTableBody' for {student_info.get('usn')}.")
            return student_info, [], {}
        rows = table_body.find_all('div', {'class': 'divTableRow'})
        total_marks_obtained = 0
        total_max_marks = 0
        for row in rows:
            cols = row.find_all('div', {'class': 'divTableCell'})
            if len(cols) == 7 and "Subject Code" not in cols[0].text:
                subject_code = cols[0].text.strip()
                subject_name = cols[1].text.strip()
                internal_marks = cols[2].text.strip()
                external_marks = cols[3].text.strip()
                total_marks_str = cols[4].text.strip()
                result = cols[5].text.strip()
                updated_on = cols[6].text.strip()
                subject_entry = {
                    "Subject Code": subject_code, "Subject Name": subject_name,
                    "Internal Marks": internal_marks, "External Marks": external_marks,
                    "Total Marks": total_marks_str, "Result": result,
                    "Announced / Updated on": updated_on
                }
                results_data.append(subject_entry)
                try:
                    total_marks_obtained += int(total_marks_str)
                except ValueError:
                    total_marks_obtained += 0
                total_max_marks += 100
        
        # --- 3. Calculate Percentage ---
        percentage = 0.0
        if total_max_marks > 0:
            percentage = (total_marks_obtained / total_max_marks) * 100
        summary_data = {
            'total_obtained': total_marks_obtained,
            'total_max': total_max_marks,
            'percentage': percentage
        }
        if not results_data: print(f"  [Warn] No subject data parsed for {student_info.get('usn')}.")
        else: print(f"  [Info] Found {len(results_data)} subjects for {student_info.get('usn')}.")
        
        # Return all three pieces of data
        return student_info, results_data, summary_data
    except Exception as e:
        print(f"  [Error] Scraping failed: {e}")
        return student_info, [], {}
# ----------------------------------------------------

# --- [NEW] Helper Function 4: Save Raw Data ---
def save_raw_data(all_subject_rows, all_summary_rows):
    """
    Saves the collected data to intermediate CSV files for robustness.
    This now OVERWRITES the files with the complete data set.
    """
    try:
        print(f"\n[Info] Saving raw scraped data...")
        # Save subjects
        subjects_df = pd.DataFrame(all_subject_rows)
        # Write header only if file doesn't exist or is empty
        subjects_df.to_csv(RAW_DATA_CSV, index=False, mode='w') # <-- OVERWRITE
        
        # Save summaries
        summary_df = pd.DataFrame(all_summary_rows)
        summary_df.to_csv(SUMMARY_DATA_CSV, index=False, mode='w') # <-- OVERWRITE
        print("[Info] Raw data saved.")
    except Exception as e:
        print(f"[Warn] Could not save raw CSV data: {e}")

# --- [MODIFIED] Helper Function 5: Process Data into Wide Excel ---
def process_data_to_excel():
    """Reads raw CSVs, pivots data, and saves to final Excel file."""
    print(f"\n[Info] Processing raw data into final Excel file '{OUTPUT_EXCEL}'...")
    try:
        # 1. Load the raw data
        subjects_df = pd.read_csv(RAW_DATA_CSV)
        summary_df = pd.read_csv(SUMMARY_DATA_CSV)

        # [FIX] Drop duplicates in case script was run multiple times
        subjects_df.drop_duplicates(inplace=True)
        summary_df.drop_duplicates(subset=['USN'], keep='last', inplace=True)

        if subjects_df.empty and summary_df.empty:
            print("[Warn] Raw results files are empty. No Excel file to generate.")
            return

        # 2. Pivot the subject data
        pivot_df = pd.DataFrame() # Create an empty one first
        if not subjects_df.empty:
            pivot_df = subjects_df.pivot_table(
                index=['USN', 'Name'],
                columns='Subject Code',
                values=['Internal Marks', 'External Marks', 'Total Marks', 'Result'],
                aggfunc='first' # Use 'first' to handle any potential duplicates
            )
            # Flatten the multi-level column headers
            pivot_df.columns = [f'{col[1]} - {col[0]}' for col in pivot_df.columns]
            pivot_df.reset_index(inplace=True) # Turn index (USN, Name) back into columns
        else:
            print("[Warn] No subject data found to pivot.")
            # Create empty pivot with just USN/Name if summary exists
            if not summary_df.empty:
                pivot_df = summary_df[['USN', 'Name']].drop_duplicates()
            else:
                pivot_df = pd.DataFrame(columns=['USN', 'Name'])


        # 4. Format the summary data
        if not summary_df.empty:
            summary_df['Percentage'] = summary_df['percentage'].apply(lambda x: f"{x:.2f}%" if isinstance(x, (int, float)) else "N/A")
            
            # --- [FIXED] Rename only the columns that need it ---
            summary_df = summary_df.rename(columns={
                'total_obtained': 'Overall Total',
                'total_max': 'Overall Max Marks'
            })
            # ----------------------------------------------------
            
            # Select the columns we need from the summary
            summary_df = summary_df[['USN', 'Name', 'Overall Total', 'Overall Max Marks', 'Percentage']]
        else:
             print("[Warn] No summary data found.")
             # Create empty summary columns if pivot data exists
             summary_df = pd.DataFrame(columns=['USN', 'Name', 'Overall Total', 'Overall Max Marks', 'Percentage'])


        # 5. Merge the pivoted subject data with the summary data
        final_df = pd.merge(pivot_df, summary_df, on=['USN', 'Name'], how='outer')
        
        # 6. Reorder columns to put summary at the end
        cols = [c for c in final_df.columns if c not in ['Overall Total', 'Overall Max Marks', 'Percentage']]
        cols.extend(['Overall Total', 'Overall Max Marks', 'Percentage'])
        final_df = final_df[cols]

        # 7. Save the final DataFrame to Excel
        final_df.to_excel(OUTPUT_EXCEL, index=False)
        print(f"[Success] Final report saved to '{OUTPUT_EXCEL}'.")

    except FileNotFoundError:
        print(f"[Error] '{RAW_DATA_CSV}' or '{SUMMARY_DATA_CSV}' not found. Did the scraping run correctly?")
    except Exception as e:
        print(f"[Error] Failed to process data into Excel: {e}")
# ---------------------------------------------------------------

# --- [NEW] Helper Function 6: Clear Raw Data Files ---
def clear_raw_data_files():
    """Deletes the intermediate CSV files."""
    print("[Info] Clearing raw data files for a fresh run...")
    if os.path.exists(RAW_DATA_CSV):
        os.remove(RAW_DATA_CSV)
    if os.path.exists(SUMMARY_DATA_CSV):
        os.remove(SUMMARY_DATA_CSV)
# -----------------------------------------------------

# --- Main Automation ---
def main():
    
    # --- [NEW] Clear previous raw files ---
    # This ensures we are starting a fresh run.
    clear_raw_data_files()
    # --------------------------------------

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

    # --- [NEW] Lists to hold all data for final processing ---
    all_subject_rows = [] 
    all_summary_rows = []
    # --------------------------------------------------------
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
                        # --- SUCCESS BLOCK ---
                        print(f"  [Success] CAPTCHA cracked for {usn}! Scraping page...")
                        success = True
                        
                        # 10. Scrape the data
                        scraped_info, scraped_data, summary_data = scrape_results_page(driver.page_source)
                        
                        # --- [NEW] Add USN/Name to each subject row ---
                        student_usn = scraped_info.get('usn', usn)
                        student_name = scraped_info.get('name', 'N/A')
                        
                        for subject in scraped_data:
                            subject['USN'] = student_usn
                            subject['Name'] = student_name
                        
                        if scraped_data:
                            all_subject_rows.extend(scraped_data)
                        
                        # Store summary data linked to the USN
                        summary_data['USN'] = student_usn
                        summary_data['Name'] = student_name
                        all_summary_rows.append(summary_data)
                        
                        break # Success, exit retry loop

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
                # [NEW] Add a failed entry to summary to avoid re-processing
                all_summary_rows.append({'USN': usn, 'Name': 'FETCH FAILED', 'percentage': 0, 'total_obtained': 0, 'total_max': 0, 'usn': usn, 'name': 'FETCH FAILED'})
            
            # --- [NEW] Save raw data progress after each student ---
            # This is the "fix" to prevent data loss on a crash
            save_raw_data(all_subject_rows, all_summary_rows)
            # ----------------------------------------------------
                
    except Exception as e:
        print(f"\nA fatal error occurred during the main loop: {e}")
        try:
            alert = driver.switch_to.alert; alert.accept()
        except NoAlertPresentException:
            pass
    finally:
        print("\nClosing browser.")
        driver.quit()

    # --- [MODIFIED] Process data and save to Excel at the end ---
    print(f"\n--- Scraping Finished ---")
    
    # Now, process the raw CSVs into the final Excel file
    process_data_to_excel()

    if failed_usns:
        print("\nThe following USNs failed after all attempts (this run):")
        for usn in failed_usns:
            print(f"  - {usn}")
    # -----------------------------------------

if __name__ == "__main__":
    main()

