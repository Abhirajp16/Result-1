import requests
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3 # Import the urllib3 module

# --- Configuration ---

# --- [FIXED URL] ---
# Updated the PAGE_URL to the new 'JJEcbcs25' one you provided.
PAGE_URL = "https://results.vtu.ac.in/JJEcbcs25/index.php"
# -------------------

# A base URL to handle relative links (like /captcha/...)
BASE_URL = "https://results.vtu.ac.in/"

# Output folder for our dataset
OUTPUT_FOLDER = "captcha_dataset"

# How many images to download in this run
IMAGES_TO_DOWNLOAD = 2000 # You can increase this number later
# ---------------------

# This line will disable the "InsecureRequestWarning" that
# requests will print when we use verify=False.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def download_captchas():
    print(f"Starting CAPTCHA download to '{OUTPUT_FOLDER}'...")
    
    # Create the output folder if it doesn't exist
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    
    # Use a Session object to keep the session (cookies) alive
    with requests.Session() as session:
        
        # Set a User-Agent to look like a real browser
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        for i in range(IMAGES_TO_DOWNLOAD):
            try:
                # 1. Get the main page
                # We need to do this *every time* to get a new session/captcha
                print(f"[{i+1}/{IMAGES_TO_DOWNLOAD}] Loading main page to get new session...")
                
                # We still need verify=False to get around the SSL error
                page_response = session.get(PAGE_URL, verify=False)
                
                page_response.raise_for_status() # Check for errors (like 404)
                
                # 2. Parse the HTML to find the CAPTCHA image URL
                soup = BeautifulSoup(page_response.text, 'html.parser')
                
                # Find the <img> tag by looking for its 'src' attribute
                img_tag = soup.find('img', src=lambda s: 'vtu_captcha.php' in s)
                
                if not img_tag:
                    print("Error: Could not find CAPTCHA <img> tag on the page.")
                    print("The page structure might have changed.")
                    continue
                    
                image_relative_url = img_tag['src']
                
                # 3. Build the full, absolute URL
                image_absolute_url = urljoin(BASE_URL, image_relative_url)
                
                # 4. Download the image *using the same session*
                print(f"  -> Downloading image from: {image_absolute_url}")
                
                # We still need verify=False here too
                image_response = session.get(image_absolute_url, verify=False)
                
                image_response.raise_for_status()
                
                # 5. Save the image
                # We don't know the label, so just save with a number
                file_path = os.path.join(OUTPUT_FOLDER, f"img_{i+1:04d}.png")
                
                with open(file_path, 'wb') as f:
                    f.write(image_response.content)
                
                print(f"  -> Saved to {file_path}")

            except requests.exceptions.RequestException as e:
                print(f"Error during download: {e}")
                
    print("\nDownload complete.")
    print(f"Please check the '{OUTPUT_FOLDER}' folder.")
    print("Your next step is to manually label all these images!")

if __name__ == "__main__":
    download_captchas()