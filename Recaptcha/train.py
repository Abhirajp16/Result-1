import os
#os.environ["CUDA_VISIBLE_DEVICES"] = "-1" # This MUST be at the top
import numpy as np
import cv2
import tensorflow as tf
from tensorflow.keras.layers import (Input, Conv2D, MaxPooling2D, GRU, 
                                     Dense, Dropout, Bidirectional, Reshape,
                                     Layer) # Import 'Layer'
from tensorflow.keras.models import Model
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from sklearn.model_selection import train_test_split

# --- Custom CTCLayer (This is correct) ---
class CTCLayer(Layer):
    def __init__(self, name=None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.loss_fn = tf.keras.backend.ctc_batch_cost

    def call(self, inputs):
        y_true, y_pred, input_length, label_length = inputs
        loss = self.loss_fn(y_true, y_pred, input_length, label_length)
        self.add_loss(tf.reduce_mean(loss))
        return y_pred
# -----------------------------------------------


# --- 1. Configuration ---

# Point to your dataset
DATA_DIR = "archive/captchas/" # Or "dataset_5k/", etc.

# Using the REAL dimensions from your screenshot
IMG_WIDTH = 160
IMG_HEIGHT = 75

CHARACTERS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_LENGTH = 6

# --- 2. Data Loading and Preprocessing ---

# --- [MODIFIED] Preprocessing Function ---
def preprocess_image(img_path):
    """Loads and preprocesses a HORIZONTAL image."""
    try:
        # Load image as grayscale
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        
        if img is None:
            raise Exception("Image is None (corrupted file)")

        # --- [NEW] CLEANING STEP ---
        # Add a Gaussian blur to reduce noise
        img = cv2.GaussianBlur(img, (5, 5), 0)
        
        # Add a binary threshold.
        # This is the key: it isolates the dark text (like "2a4hjg")
        # and removes all the lighter background text (like "CAMPUS").
        # THRESH_BINARY_INV makes the text white (255) and bg black (0).
        _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # -----------------------------
        
        # Resize to the standard (Width, Height)
        # We want a (75, 160) array.
        # cv2.resize dsize is (width, height) = (160, 75)
        img = cv2.resize(img, (IMG_WIDTH, IMG_HEIGHT))
        
        # Normalize pixels from [0, 255] to [0, 1]
        img = img / 255.0
        
        # Add a channel dimension -> (75, 160, 1)
        img = np.expand_dims(img, axis=-1)
        
        return img
    except Exception as e:
        print(f"Error loading image {img_path}: {e}")
        return None
# -------------------------------------------

def build_dataset():
    """Loads all images and labels from the DATA_DIR."""
    images = []
    labels = []
    
    print(f"Loading images from {DATA_DIR}...")
    filenames = os.listdir(DATA_DIR)
    
    for filename in filenames:
        if filename.endswith((".png", ".jpg", ".jpeg")):
            path = os.path.join(DATA_DIR, filename)
            label = os.path.splitext(filename)[0]
            
            if len(label) > MAX_LENGTH:
                print(f"Warning: Skipping {filename}, label > MAX_LENGTH")
                continue
            
            if not all(char in CHARACTERS for char in label):
                print(f"Warning: Skipping {filename}, contains invalid characters")
                continue

            img = preprocess_image(path)
            
            if img is not None:
                images.append(img)
                labels.append(label)
                
    print(f"Loaded {len(images)} images.")
    return images, labels

# --- 3. Label Encoding (This is correct) ---
char_to_num = {char: i for i, char in enumerate(CHARACTERS)}
num_to_char = {i: char for i, char in enumerate(CHARACTERS)}

def encode_labels(labels):
    encoded_labels = np.zeros((len(labels), MAX_LENGTH), dtype=np.float32)
    label_lengths = []
    
    for i, label in enumerate(labels):
        label_lengths.append(len(label))
        for j, char in enumerate(label):
            encoded_labels[i, j] = char_to_num[char]
            
    return encoded_labels, np.array(label_lengths)

# --- 4. The Model Architecture (This is correct) ---

def build_model():
    """Builds the CNN + RNN + CTC model."""
    
    # Inputs Shape: (Height, Width, 1) = (75, 160, 1)
    input_img = Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1), name="image")
    labels = Input(name="labels", shape=[MAX_LENGTH], dtype="float32")
    input_length = Input(name="input_length", shape=[1], dtype="int64")
    label_length = Input(name="label_length", shape=[1], dtype="int64")

    # CNN
    x = Conv2D(32, (3, 3), activation="relu", padding="same")(input_img)
    x = MaxPooling2D((2, 2))(x) # Shape: (37, 80, 32)
    
    x = Conv2D(64, (3, 3), activation="relu", padding="same")(x)
    x = MaxPooling2D((2, 2))(x) # Shape: (18, 40, 64)
    
    # Reshape for RNN
    # Timesteps = IMG_WIDTH // 4 = 160 // 4 = 40
    # Features = (IMG_HEIGHT // 4) * 64 = (75 // 4) * 64 = 18 * 64 = 1152
    new_shape = (IMG_WIDTH // 4, (IMG_HEIGHT // 4) * 64)
    x = Reshape(target_shape=new_shape)(x)
    
    x = Dense(64, activation="relu")(x)
    x = Dropout(0.2)(x)
    
    # RNN
    x = Bidirectional(GRU(128, return_sequences=True))(x)
    x = Bidirectional(GRU(64, return_sequences=True))(x)
    
    # Output Layer
    output = Dense(len(CHARACTERS) + 1, activation="softmax", name="ctc_output")(x)
    
    # CTC Loss
    loss_output = CTCLayer(name="ctc_loss")(
        [labels, output, input_length, label_length]
    )
    
    # Training Model
    model = Model(
        inputs=[input_img, labels, input_length, label_length],
        outputs=loss_output,
        name="ocr_model_v1"
    )
    model.compile(optimizer="adam")
    
    # Prediction Model
    prediction_model = Model(
        inputs=input_img,
        outputs=output,
        name="ocr_prediction_model"
    )
    
    return model, prediction_model

# --- 5. Main Training Script (This is correct) ---

def main():
    # 1. Load and preprocess data
    images_data, labels_data = build_dataset()
    if not images_data:
        print("No images loaded. Check DATA_DIR and image files.")
        return
        
    labels_encoded, label_lengths = encode_labels(labels_data)
    images_data = np.array(images_data)
    
    # 2. Split data
    (x_train, x_val, 
     y_train, y_val,
     len_train, len_val) = train_test_split(
        images_data, 
        labels_encoded, 
        label_lengths, 
        test_size=0.1,
        random_state=42
    )
    
    print(f"Training with {len(x_train)} images, validating with {len(x_val)} images.")

    # 3. Build the model
    training_model, prediction_model = build_model()
    training_model.summary()
    
    # 4. Prepare data for CTC Loss
    # Timesteps = 160 // 4 = 40
    train_input_len = np.ones(len(x_train)) * (IMG_WIDTH // 4)
    val_input_len = np.ones(len(x_val)) * (IMG_WIDTH // 4)
    
    train_inputs = {
        'image': x_train,
        'labels': y_train,
        'input_length': train_input_len,
        'label_length': len_train
    }
    val_inputs = {
        'image': x_val,
        'labels': y_val,
        'input_length': val_input_len,
        'label_length': len_val
    }
    
    # 5. Callbacks
    save_callback = ModelCheckpoint(
        "vtu_captcha_model.h5", 
        monitor="val_loss",
        save_best_only=True,
        save_weights_only=False
    )
    stop_callback = EarlyStopping(
        monitor="val_loss", 
        patience=10,
        restore_best_weights=True
    )
    
    # 6. Train the Model!
    print("\n--- Starting Training ---")
    
    training_model.fit(
        train_inputs,
        y=np.zeros(len(x_train)),
        validation_data=(
            val_inputs,
            np.zeros(len(x_val))
        ),
        epochs=100,
        batch_size=8,
        callbacks=[save_callback, stop_callback]
    )
    
    # 7. Save the final prediction model
    prediction_model.save("vtu_captcha_predictor.h5")
    
    print("\n--- Training Complete ---")
    print("Best model saved as 'vtu_captcha_model.h5'")
    print("Final prediction model saved as 'vtu_captcha_predictor.h5'")


if __name__ == "__main__":
    main()