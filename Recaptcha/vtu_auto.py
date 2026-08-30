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
# --- [MODIFIED] Import NoAlertPresentException ---
from selenium.common.exceptions import TimeoutException, NoAlertPresentException
import time

# --- Configuration ---
# UPDATE this to the current, working VTU results page URL!
VTU_RESULTS_URL = "https://results.vtu.ac.in/JJEcbcs25/index.php"

# Find your saved model. Use .keras if you have it, otherwise fall back to .h5
MODEL_FILE = "vtu_captcha_predictor.h5" # <-- UPDATE THIS TO YOUR BEST MODEL FILE

# --- Model Constants (MUST MATCH train.py) ---
IMG_WIDTH = 160
IMG_HEIGHT = 75
CHARACTERS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_LENGTH = 6 # <-- ADDED THIS
num_to_char = {i: char for i, char in enumerate(CHARACTERS)}
# -------------------------------------------


# --- Helper Function 1: Preprocessing (From your uploaded solve.py) ---
def preprocess_image(img_path):
    """Loads and preprocesses a HORIZONTAL image with cleaning."""
    try:
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        if img is None: raise Exception("Image is None")
        
        # --- Preprocessing steps from your solve.py ---
        # 1. Blur
        img = cv2.GaussianBlur(img, (5, 5), 0)
        # 2. Threshold (Otsu)
        _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # --------------------------------------------------------

        # 4. Resize
        img = cv2.resize(img, (IMG_WIDTH, IMG_HEIGHT))
        # 5. Normalize
        img = img / 255.0
        # 6. Add channel dimension
        img = np.expand_dims(img, axis=-1)
        # 7. Add batch dimension for prediction
        img = np.expand_dims(img, axis=0) 
        return img
    except Exception as e:
        print(f"Error processing image {img_path}: {e}", file=sys.stderr)
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
            
    # --- [NEW FIX] ---
    # Force the output to be max 6 characters
    # This fixes "stutters" like 'gV5crAA' -> 'gV5crA'
    return output_text[:MAX_LENGTH]
    # -----------------

# --- Main Automation ---
def main():
    # --- Get USN from user input ---
    usn = input("Please enter your USN: ").strip().upper()
    if not usn:
        print("USN cannot be empty.")
        return
    
    MAX_ATTEMPTS = 5
    success = False
    
    # 1. Load the trained model
    print(f"Loading model from {MODEL_FILE}...")
    try:
        model = tf.keras.models.load_model(MODEL_FILE)
        model.summary()
    except Exception as e:
        print(f"Error loading model: {e}"); return
        
    # 2. Set up Selenium
    print("Starting browser...")
    try:
        service = Service() 
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless") # Uncomment to run headless
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"Error starting Selenium WebDriver: {e}")
        print("Please ensure 'chromedriver' is installed and in your system PATH.")
        return

    # 3. Automate the website
    try:
        print(f"Navigating to {VTU_RESULTS_URL}...")
        driver.get(VTU_RESULTS_URL)
        wait = WebDriverWait(driver, 10) # 10 second wait time
        
        # --- Retry Loop ---
        for attempt in range(MAX_ATTEMPTS):
            print(f"\n--- Attempt {attempt + 1} of {MAX_ATTEMPTS} ---")
            
            try:
                # 4. Find elements (must re-find them each loop)
                usn_box = wait.until(EC.presence_of_element_located((By.NAME, "lns")))
                captcha_box = driver.find_element(By.NAME, "captchacode")
                captcha_image = driver.find_element(By.XPATH, "//img[contains(@src, 'vtu_captcha.php')]")
                submit_button = driver.find_element(By.ID, "submit")
                
                # Clear boxes and enter USN
                usn_box.clear()
                captcha_box.clear()
                usn_box.send_keys(usn)
                
                # 5. Save and solve CAPTCHA
                print("Screenshotting and solving CAPTCHA...")
                captcha_screenshot_path = "captcha_screenshot.png"
                captcha_image.screenshot(captcha_screenshot_path)
                
                image_data = preprocess_image(captcha_screenshot_path)
                if image_data is None:
                    print("Could not process CAPTCHA image, refreshing page...")
                    driver.refresh()
                    continue
                    
                prediction = model.predict(image_data, verbose=0)
                solved_text = decode_prediction(prediction)
                print(f"Model Predicted: '{solved_text}'")
                
                # 7. Enter solved CAPTCHA and submit
                captcha_box.send_keys(solved_text)
                
                # Get current URL *before* clicking
                current_url = driver.current_url
                submit_button.click()
                
                # --- [FIXED] Alert Handling Logic ---
                
                # 8. Check for success (if URL changes, it worked)
                print("Checking for success (waiting for URL to change)...")
                try:
                    WebDriverWait(driver, 5).until(EC.url_changes(current_url))
                    # URL changed! BUT is it a success or a failure alert?
                    print("URL changed. Checking for 'Invalid Captcha' alert on new page...")
                    
                    try:
                        # Check for an alert on the NEW page
                        alert_wait = WebDriverWait(driver, 2)
                        alert = alert_wait.until(EC.alert_is_present())
                        
                        alert_text = alert.text
                        print(f"Alert detected: '{alert_text}'. Clicking 'OK'.")
                        alert.accept()
                        
                        print("CAPTCHA was incorrect. Going back to retry...")
                        driver.get(VTU_RESULTS_URL) # Go back to the main page
                        continue # Continue to the next attempt

                    except (TimeoutException, NoAlertPresentException):
                        # NO ALERT found on the new page! This is TRUE success!
                        print("No alert found. CAPTCHA cracked successfully! Loading results...")
                        success = True
                        break # Exit the loop
                
                except TimeoutException:
                    # This block runs if the URL *did not* change (old failure case)
                    print(f"Attempt {attempt + 1} failed (URL did not change).")
                    
                    # Handle the alert on the *current* page
                    try:
                        alert_wait = WebDriverWait(driver, 2)
                        alert = alert_wait.until(EC.alert_is_present())
                        alert_text = alert.text
                        print(f"Alert detected: '{alert_text}'. Clicking 'OK'.")
                        alert.accept()
                    except (TimeoutException, NoAlertPresentException):
                        print("No alert box found. Proceeding to refresh CAPTCHA.")

                    # Refresh CAPTCHA image
                    try:
                        print("Refreshing CAPTCHA image...")
                        refresh_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//img[contains(@src, 'refresh.png')]")))
                        refresh_button.click()
                        time.sleep(1) 
                    except Exception as e:
                        print(f"Could not refresh CAPTCHA, forcing page reload. Error: {e}")
                        driver.refresh()
                    
                    print("Retrying...")
                    # Loop continues
                # --- [END FIXED LOGIC] ---
                
            except Exception as e:
                print(f"An error occurred during attempt {attempt + 1}: {e}")
                driver.refresh() # Refresh the page on unexpected errors
                time.sleep(1)
                
        # --- End of Loop ---
        
        if success:
            print("\nForm submitted! Displaying results for 30 seconds...")
            time.sleep(30) # Wait 30s for you to see the result page
        else:
            print(f"\nFailed to solve CAPTCHA after {MAX_ATTEMPTS} attempts.")
            time.sleep(5) # Wait 5s to see the final failed page
            
    except Exception as e:
        print(f"A fatal error occurred: {e}")
    finally:
        print("Closing browser.")
        driver.quit()

if __name__ == "__main__":
    main()

