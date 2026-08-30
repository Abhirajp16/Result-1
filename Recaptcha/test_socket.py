import socketio
import time

sio = socketio.Client()

@sio.on("connect")
def on_connect():
    print("Connected!")

@sio.on("log-message")
def on_log(msg):
    print("LOG:", msg.get("data", ""))

@sio.on("csv-data")
def on_csv(data):
    print("CSV DATA:", data.get("usns", ""))

@sio.on("fetch-started")
def on_fetch_start():
    print("Fetch started!")

@sio.on("fetch-complete")
def on_fetch_complete():
    print("Fetch complete!")
    sio.disconnect()

sio.connect("http://127.0.0.1:5000")
print("Emitting import-csv...")
sio.emit("import-csv")
time.sleep(2)
print("Test done")
sio.disconnect()
