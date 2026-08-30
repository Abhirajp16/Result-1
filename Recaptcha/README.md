# 📘 VTU Bulk Result Fetcher + CAPTCHA Solver + SGPA Calculator

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python)
![Flask](https://img.shields.io/badge/Flask-Web%20Framework-lightgrey?style=for-the-badge&logo=flask)
![TensorFlow](https://img.shields.io/badge/TensorFlow-Machine%20Learning-orange?style=for-the-badge&logo=tensorflow)
![Selenium](https://img.shields.io/badge/Selenium-Automation-green?style=for-the-badge&logo=selenium)

A fully automated VTU result-fetching system that utilizes **Machine Learning**, **Selenium**, and **Flask-SocketIO**. This tool automates the tedious process of fetching results for multiple USNs, solving CAPTCHAs using a trained Deep Learning model, processing subject data, and calculating SGPAs, finally exporting everything into a comprehensive Excel report.

---

## 🚀 Features

### 🤖 ML-Based CAPTCHA Solver
* **Deep Learning Core:** Powered by a custom trained TensorFlow/Keras model (`vtu_captcha_predictor.h5`).
* **Computer Vision:** Uses OpenCV for image preprocessing (grayscale, thresholding) to enhance prediction accuracy.
* **Zero Intervention:** Automatically predicts and inputs VTU CAPTCHAs during the scraping process.

### 🕸️ VTU Result Automation (Selenium)
* **Bulk Processing:** Iterates through a CSV list of USNs automatically.
* **Deep Scraping:** Extracts subject-wise marks, Internal Assessment (IA), External Assessment (EA), Totals, Result Status (P/F), and Percentages.
* **Robust Error Handling:** Automatically handles timeouts, alerts, and invalid USNs.

### ⚡ Real-Time Log Streaming
* **Live Feedback:** Integrated **Flask-SocketIO** pushes backend scraping logs to the browser instantly.
* **Interactive UI:** Watch the bot work in real-time on the web dashboard.

### 📊 SGPA Calculator & Excel Export
* **Dynamic Subject Detection:** Automatically extracts all unique subjects found across the fetched results.
* **Smart Credit Input:** User enters credits *once* for each subject via the UI.
* **Auto-Calculation:** Computes SGPA for every student based on VTU grading logic.
* **Rich Excel Report:** Generates `vtu_results.xlsx` containing raw scores + calculated SGPA.

---

## 🧠 Tech Stack

| Component | Technologies Used |
| :--- | :--- |
| **Backend** | Python, Flask, Flask-SocketIO, Eventlet |
| **Automation** | Selenium WebDriver, BeautifulSoup4 |
| **Machine Learning** | TensorFlow (Keras), OpenCV, NumPy |
| **Data Processing** | Pandas, OpenPyXL |
| **Frontend** | HTML5, TailwindCSS, JavaScript, Socket.IO Client |
| **Infrastructure** | ChromeDriver, Python `venv` |

---

## 📂 Project Structure

```text
📦 VTU-Result-Fetcher
 ┣ 📂 templates
 ┃ ┗ 📜 index.html                # Frontend UI (Log viewer + SGPA credit form)
 ┣ 📜 app.py                      # Main Flask backend + Socket.IO + SGPA logic
 ┣ 📜 bulk_fetcher_5_excelfix.py  # Selenium scraper + CAPTCHA solver module
 ┣ 📜 vtu_captcha_predictor.h5    # Pre-trained Keras model for CAPTCHA
 ┣ 📜 students.csv                # Input file containing list of USNs
 ┣ 📜 raw_results.csv             # Intermediate storage for scraped subject data
 ┣ 📜 raw_summary.csv             # Intermediate storage for raw totals
 ┣ 📜 vtu_results.xlsx            # Final output file (Result + SGPA)
 ┗ 📜 README.md                   # Project Documentation

https://github.com/Mayur-U/Recaptcha

## ⚙️ Setup & Installation
 
first open file vtu fetch folder 

Go to terminal type

D:\vtu result fetch> 

cmd

cd R*

tfenv\Scripts\activate

python app.py

http://127.0.0.1:5000

### 1. Prerequisites
* **Python 3.8+** installed on your system.
* **Google Chrome** browser installed.
* **ChromeDriver** matching your Chrome version.

### 2. Install Dependencies
You can install all required packages using pip. Run the following command in your terminal:

```bash
pip install flask flask-socketio eventlet selenium pandas tensorflow opencv-python beautifulsoup4 openpyxl
3. Setup ChromeDriver
Check your Chrome version (Settings > About Chrome).

Download the matching ChromeDriver from the official site.

Place the chromedriver.exe (Windows) or chromedriver (Mac/Linux) in your project folder or add it to your System PATH.

4. Prepare Input Data
Create or edit the students.csv file in the root directory. It should contain a header (optional, depending on code logic) or a simple list of USNs.

Example students.csv:

Code snippet

1GD23CS402
1GD23CS403
1GD23CS404
🖥️ Usage Guide
Step 1: Run the Application
Start the Flask server by running:

Bash

python app.py
You should see output indicating the server is running (usually on http://127.0.0.1:5000).

Step 2: Access the Dashboard
Open your web browser and go to http://127.0.0.1:5000.

Step 3: Start Fetching
Paste the current VTU Result URL (e.g., https://results.vtu.ac.in/...) into the input field.

Click "Start Fetching".

The logs section will stream real-time updates as the bot solves CAPTCHAs and scrapes data.

Step 4: Calculate SGPA
Once scraping is complete, the "Calculate SGPA" section will unlock.

The system will list all subjects found. Enter the Course Credits for each subject (e.g., Maths = 4, Lab = 1).

Click "Calculate & Download".

Step 5: View Results
The system will generate vtu_results.xlsx. Open this file to view the comprehensive report including the calculated SGPA for every student.

⚠️ Disclaimer
This project is intended for educational purposes only.

Automated scraping of university websites may violate their Terms of Service.

The author is not responsible for any misuse of this tool or IP bans resulting from excessive requests.

Please use this tool responsibly and consider adding delays between requests.

🤝 Contributing
Contributions are welcome! Please follow these steps:

Fork the repository.

Create a new branch (git checkout -b feature/YourFeature).

Commit your changes (git commit -m 'Add some feature').

Push to the branch (git push origin feature/YourFeature).

Open a Pull Request.

📧 Contact
Author: Mayur U

GitHub: Mayur-U