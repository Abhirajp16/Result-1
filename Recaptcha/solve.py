import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1" # Hide the GPU
import sys
import numpy as np
import cv2
import tensorflow as tf
from tensorflow.keras import backend as K
import editdistance # <-- NEW IMPORT for CER calculation

# --- Configuration (MUST MATCH train.py) ---
MODEL_PATH = "vtu_captcha_predictor.h5" # Or vtu_captcha_model.h5 if needed

IMG_WIDTH = 160
IMG_HEIGHT = 75
CHARACTERS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Create the reverse mapping
num_to_char = {i: char for i, char in enumerate(CHARACTERS)}
# -------------------------------------------

def preprocess_image(img_path):
    """Loads and preprocesses a single image (must match train.py)."""
    try:
        # Load image as grayscale
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        
        if img is None:
            raise Exception("Image is None (corrupted file?)")

        # --- [NEW] CLEANING STEP (MUST MATCH train.py preprocessing) ---
        img = cv2.GaussianBlur(img, (5, 5), 0)
        _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # ------------------------------------------------------------

        # Resize to the standard (Width, Height) -> (75, 160)
        img = cv2.resize(img, (IMG_WIDTH, IMG_HEIGHT))
        
        # Normalize pixels from [0, 255] to [0, 1]
        img = img / 255.0
        
        # Add a channel dimension -> (75, 160, 1)
        img = np.expand_dims(img, axis=-1)
        
        # Add a batch dimension -> (1, 75, 160, 1)
        img = np.expand_dims(img, axis=0)
        
        return img
    except Exception as e:
        print(f"Error loading/processing image {img_path}: {e}")
        return None

def decode_prediction(pred):
    """Decodes the raw model output (CTC) into a string."""
    input_len = np.ones(pred.shape[0]) * pred.shape[1]
    
    # Use Keras's CTC decoder (greedy=True means pick best path)
    results = K.ctc_decode(pred, input_length=input_len, greedy=True)[0][0]
    
    # Convert the numbers back to characters
    output_text = ""
    for num in results[0]:
        num = num.numpy()
        if num == -1: # -1 is the CTC "blank" character
            break
        if num < len(num_to_char): # Check bounds
            output_text += num_to_char[num]
            
    return output_text

# --- NEW FUNCTION: Calculate CER ---
def calculate_cer(true_label, predicted_label):
    """Calculates the Character Error Rate."""
    if not true_label: # Avoid division by zero if true label is empty
        return 1.0 if predicted_label else 0.0
    distance = editdistance.eval(true_label, predicted_label)
    return distance / len(true_label)
# ------------------------------------

def main():
    # Check for image path and optional true label
    # --- [FIXED CONDITION] ---
    # The script should accept 2 arguments (script + image)
    # OR 3 arguments (script + image + label)
    if len(sys.argv) != 2 and len(sys.argv) != 3:
        print("Usage: python3 solve.py /path/to/captcha.png [OptionalTrueLabel]")
        return
    # -------------------------

    image_path = sys.argv[1]
    true_label = sys.argv[2] if len(sys.argv) == 3 else None

    if not os.path.exists(image_path):
        print(f"Error: Image not found at {image_path}")
        return

    # 1. Load the model
    print("Loading model...")
    try:
        # Load the predictor model saved by train.py
        model = tf.keras.models.load_model(MODEL_PATH)
    except Exception as e:
        print(f"Error loading model: {e}")
        print(f"Make sure '{MODEL_PATH}' is in this directory.")
        return

    # 2. Preprocess the image
    print(f"Processing image: {image_path}")
    image = preprocess_image(image_path)

    if image is None:
        return

    # 3. Predict
    prediction = model.predict(image, verbose=0) # verbose=0 silences progress bar

    # 4. Decode
    predicted_label = decode_prediction(prediction)

    # 5. Print result and metrics (if true label provided)
    print("\n--- OCR Result ---")
    print(f"Predicted: '{predicted_label}'")

    if true_label is not None:
        print(f"True Label: '{true_label}'")

        # Calculate Exact Match
        is_correct = (true_label == predicted_label)
        print(f"Exact Match: {is_correct}")

        # Calculate CER
        cer = calculate_cer(true_label, predicted_label)
        print(f"Character Error Rate (CER): {cer:.4f} (Lower is better)")

if __name__ == "__main__":
    main()