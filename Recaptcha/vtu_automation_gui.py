import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import queue

# --- Configuration ---
BACKEND_SCRIPT = "bulk_fetcher_4_excelfix.py"
DEFAULT_CSV = "students.csv"
# ---------------------

class LogRedirector:
    """A helper class to redirect stdout/stderr to a queue."""
    def __init__(self, queue):
        self.queue = queue
    
    def write(self, text):
        self.queue.put(text)
    
    def flush(self):
        pass

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VTU Bulk Result Fetcher")
        self.geometry("800x600")

        self.process = None
        self.log_queue = queue.Queue()
        self.setup_widgets()
        self.check_log_queue()

    def setup_widgets(self):
        # Frame for USN Input
        input_frame = ttk.Frame(self, padding="10")
        input_frame.pack(fill='x', expand=False)

        ttk.Label(input_frame, text="Enter USNs (one per line or comma-separated):").pack(anchor='w')
        
        # Text Box for USNs
        self.usn_text = tk.Text(input_frame, height=10, width=70)
        self.usn_text.pack(fill='x', expand=True, side='left', padx=(0, 10))

        # Frame for Buttons
        button_frame = ttk.Frame(input_frame)
        button_frame.pack(side='left', fill='y')

        self.import_button = ttk.Button(button_frame, text="Import from CSV", command=self.import_csv)
        self.import_button.pack(fill='x', expand=True, pady=5)
        
        self.start_button = ttk.Button(button_frame, text="Start Fetching", command=self.start_processing_thread)
        self.start_button.pack(fill='x', expand=True, pady=5)

        # Frame for Log Output
        log_frame = ttk.Frame(self, padding="10")
        log_frame.pack(fill='both', expand=True)

        ttk.Label(log_frame, text="Log Output:").pack(anchor='w')
        
        self.log_text = tk.Text(log_frame, state='disabled', bg="#f0f0f0")
        self.log_text.pack(fill='both', expand=True)

    def import_csv(self):
        """Loads USNs from the default CSV file into the text box."""
        if not os.path.exists(DEFAULT_CSV):
            messagebox.showerror("Error", f"Could not find '{DEFAULT_CSV}'.")
            return
            
        try:
            with open(DEFAULT_CSV, 'r') as f:
                # Read all lines, skip header ("USN")
                usns = f.readlines()[1:] 
                self.usn_text.delete('1.0', tk.END)
                self.usn_text.insert(tk.END, "".join(usns))
            self.log(f"Successfully imported {len(usns)} USNs from {DEFAULT_CSV}\n")
        except Exception as e:
            messagebox.showerror("Error importing CSV", str(e))

    def log(self, message):
        """Inserts a message into the log text widget."""
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END) # Auto-scroll
        self.log_text.configure(state='disabled')

    def check_log_queue(self):
        """Checks the queue for new log messages and displays them."""
        while not self.log_queue.empty():
            message = self.log_queue.get()
            self.log(message)
        self.after(100, self.check_log_queue)

    def start_processing_thread(self):
        """Starts the backend script in a separate thread."""
        self.start_button.configure(text="Running...", state='disabled')
        self.import_button.configure(state='disabled')
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.configure(state='disabled')

        # Get USNs from text box
        usn_input = self.usn_text.get('1.0', tk.END).strip()
        # Split by comma or newline
        usns = [usn.strip().upper() for usn in usn_input.replace(',', '\n').split('\n') if usn.strip()]

        if not usns:
            messagebox.showerror("Error", "No USNs provided.")
            self.start_button.configure(text="Start Fetching", state='normal')
            self.import_button.configure(state='normal')
            return
        
        # Create the thread
        self.thread = threading.Thread(target=self.run_fetcher_script, args=(usns,))
        self.thread.start()

    def run_fetcher_script(self, usn_list):
        """The target function for the thread. Runs the backend script."""
        try:
            # 1. Overwrite the students.csv file
            self.log(f"Generating temporary '{DEFAULT_CSV}' with {len(usn_list)} USNs...\n")
            with open(DEFAULT_CSV, 'w') as f:
                f.write("USN\n") # Write header
                for usn in usn_list:
                    f.write(f"{usn}\n")
            
            # 2. Find the correct Python executable (the one in the venv)
            python_executable = sys.executable
            self.log(f"Starting backend script: {BACKEND_SCRIPT}\n")
            self.log(f"Using Python: {python_executable}\n")
            self.log("-" * 30 + "\n")

            # 3. Run the backend script as a subprocess
            # We capture stdout and stderr in real-time
            self.process = subprocess.Popen(
                [python_executable, BACKEND_SCRIPT],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1, # Line-buffered
                encoding='utf-8'
            )

            # 4. Read the output line by line and put it in the queue
            if self.process.stdout:
                for line in iter(self.process.stdout.readline, ''):
                    self.log_queue.put(line)

            # 5. Wait for the process to complete
            self.process.wait()
            self.log_queue.put("\n" + "-" * 30 + "\n")
            self.log_queue.put(f"Backend script finished with exit code {self.process.returncode}\n")

        except Exception as e:
            self.log_queue.put(f"\n--- FATAL ERROR IN GUI SCRIPT ---\n{e}\n")
        finally:
            # Re-enable buttons
            # We must schedule this to run on the main thread
            self.after(0, self.on_processing_complete)

    def on_processing_complete(self):
        """Called when the thread finishes to re-enable buttons."""
        self.start_button.configure(text="Start Fetching", state='normal')
        self.import_button.configure(state='normal')

    def on_closing(self):
        """Handle window close event."""
        if self.process and self.process.poll() is None:
            if messagebox.askyesno("Confirm", "A process is still running. Do you want to stop it and exit?"):
                self.process.terminate() # Stop the backend script
                self.destroy() # Close the GUI
        else:
            self.destroy()

if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing) # Handle closing while running
    app.mainloop()
