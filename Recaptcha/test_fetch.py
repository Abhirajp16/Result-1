import socketio
import time
import sys

sio = socketio.Client()

@sio.on("connect")
def on_connect():
    print("Connected!")

@sio.on("log-message")
def on_log(msg):
    data = msg.get("data", "")
    print("LOG:", repr(data))
    sys.stdout.flush()

@sio.on("fetch-started")
def on_fetch_start():
    print("Fetch started signal received!")

@sio.on("fetch-complete")
def on_fetch_complete():
    print("Fetch complete!")
    sio.disconnect()

@sio.on("download-ready")
def on_download():
    print("Download ready!")

@sio.on("*")
def all_events(event, data):
    print(f"Event: {event} -> {data}")

print("Connecting...")
sio.connect("http://127.0.0.1:5000")
print("Connected, emitting start-fetch...")

# Test with a fake USN and URL - should at least start
sio.emit("start-fetch", {
    "usns": ["1GD24CS402"],
    "url": "https://results.vtu.ac.in/JJEcbcs25/index.php"
})

print("Waiting for events (30s timeout)...")
time.sleep(30)
print("Done waiting")
sio.disconnect()
