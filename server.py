import asyncio
import websockets
import json
import subprocess
import sys
import os
import uuid  # Import the uuid module

# =================================================================================================
# Configuration
# =================================================================================================

HOST = "0.0.0.0"  # Listen on all interfaces
PORT = 8765       # Choose a suitable port
DOLPHIN_PATH = "/path/to/dolphin"  # <--- IMPORTANT: Change this to your Dolphin executable path
# You can find this by right clicking on dolphin in steam,
# going to properties, and copying the path from there.
# common paths include:
# Windows: "C:\\Program Files\\Dolphin\\Dolphin.exe"
# Linux: "/usr/bin/dolphin-emu"
# Steam Deck: "/home/deck/.local/share/Steam/steamapps/common/Dolphin Emulator/Dolphin"
DEBUG_MODE = True  # Added for debug mode.  Set to False to disable.
MAX_CLIENTS = 4 # Maximum number of clients allowed

# =================================================================================================
# Global Variables
# =================================================================================================

connected_clients = {}  # Store clients by their unique IDs (uuid)
dolphin_process = None
# Input conversion mapping (customize as needed)
INPUT_MAP = {
    "A": "a",
    "B": "b",
    "X": "x",
    "Y": "y",
    "Z": "z",
    "START": "start",
    "DPAD_UP": "dpad_up",
    "DPAD_DOWN": "dpad_down",
    "DPAD_LEFT": "dpad_left",
    "DPAD_RIGHT": "dpad_right",
    "L": "l",
    "R": "r",
    "ZL": "zl",
    "ZR": "zr",
    "ANALOG_LEFT_X": "left_x",
    "ANALOG_LEFT_Y": "left_y",
    "ANALOG_RIGHT_X": "right_x",
    "ANALOG_RIGHT_Y": "right_y",
}

# =================================================================================================
# Helper Functions
# =================================================================================================

def log(message):
    """Simple logging function."""
    print(f"[INFO] {message}")
    sys.stdout.flush() # Make sure prints show up immediately

def error(message):
    """Error logging function."""
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.stderr.flush()

def is_dolphin_running():
    """Check if Dolphin is already running."""
    global dolphin_process
    if dolphin_process:
        if dolphin_process.poll() is None:
            return True
        else:
            dolphin_process = None # Reset if it has finished.
            return False
    else:
        try:
            # Check for the process, cross-platform
            if os.name == 'nt': # Windows
                result = subprocess.run(['tasklist', '/FI', 'imagename eq Dolphin.exe'], capture_output=True, text=True)
                return 'Dolphin.exe' in result.stdout
            else: # Linux / macOS
                result = subprocess.run(['pgrep', '-x', 'dolphin-emu'], capture_output=True, text=True)
                return result.stdout.strip() != ""
        except Exception as e:
            error(f"Error checking for Dolphin process: {e}")
            return False

def send_command_to_dolphin(player_id, command):
    """
    Send a command to Dolphin.  This is a placeholder.  You'll need to
    replace this with the *actual* method for sending commands to Dolphin.
    This could involve:
    - Using a FIFO (named pipe)
    - Using a TCP socket
    - Using a Dolphin control socket (if available)
    - Using a library like `pydolphin` (if it meets your needs)

    This example uses a subprocess to send keystrokes using `xdotool` (Linux)
    or `SendInput` (Windows), but this is NOT the recommended way to control
    Dolphin.  Direct control via a socket or API is much better.

    Args:
        player_id (int):  The ID of the player (1-4) to send the command to.
        command (dict): The command to send.  This will contain
                        the button/analog stick and its value.
    """
    if not command:
        return

    try:
        if os.name == 'posix':  # Linux (and macOS, though untested)
            # Example using xdotool (you'll need to install it: `sudo apt install xdotool`)
            #  This is just an *example* and is NOT ideal for real-time control.
            if 'ANALOG' in command:
                if 'X' in command:
                    x_value = int(command['ANALOG_LEFT_X'] * 128 + 128) #convert to 0-255 range
                    subprocess.run(['xdotool', 'mousemove', '--relative', '--sync', f'{x_value}','0'])
                elif 'Y' in command:
                    y_value = int(command['ANALOG_LEFT_Y'] * 128 + 128)
                    subprocess.run(['xdotool', 'mousemove', '--relative', '--sync',  '0',f'{y_value}'])
                #  No good way to send analog right
            elif command['type'] == 'button':
                button = command['button']
                if command['value']:
                    subprocess.run(['xdotool', 'key', button.upper()])  # Press the key
                # Release is harder with xdotool, and not usually needed for gamepads
        elif os.name == 'nt':  # Windows
            #  Use SendInput or a similar Windows API.  pydirectinput is a good option
            #  Example using pydirectinput (install it: `pip install pydirectinput`)
            #  pydirectinput.press(button) # simplified
            log("Windows input not fully implemented.  Use pydirectinput or raw SendInput.")

        else:
            log(f"Unsupported OS: {os.name}.  Cannot send input.")
    except Exception as e:
        error(f"Error sending command to Dolphin: {e}")

# =================================================================================================
# WebSocket Handlers
# =================================================================================================

async def handle_client(websocket):
    """Handle a new WebSocket connection."""
    if len(connected_clients) >= MAX_CLIENTS:
        error(f"Connection refused: Maximum number of clients ({MAX_CLIENTS}) reached.")
        await websocket.send(json.dumps({"error": "Too many clients"}))
        await websocket.close()
        return

    client_id = str(uuid.uuid4())  # Generate a unique ID for the client
    connected_clients[client_id] = websocket  # Store the client with its ID
    try:
        log(f"Client connected: {websocket.remote_address} with ID: {client_id}")
        await websocket.send(json.dumps({"message": "Connected to Dolphin Controller Server", "client_id": client_id})) #send the client ID
        async for message in websocket:
            try:
                data = json.loads(message)
                if DEBUG_MODE:
                    log(f"Received message from {websocket.remote_address} (ID: {client_id}): {data}")
                # Process the input command and send it to Dolphin
                if "type" in data and data["type"] == "controller_input":
                    #  Remap the data
                    remapped_data = {}
                    for key, value in data['input'].items():
                         if key in INPUT_MAP:
                            remapped_data[INPUT_MAP[key]] = value
                    #  Send the command and the client ID
                    send_command_to_dolphin(client_id, remapped_data)
                elif "command" in data:
                    if data["command"] == "start_dolphin":
                        await start_dolphin()
                    elif data["command"] == "stop_dolphin":
                        await stop_dolphin()
                    elif data["command"] == "status":
                        status = "Running" if is_dolphin_running() else "Stopped"
                        await websocket.send(json.dumps({"status": status}))
            except json.JSONDecodeError:
                error(f"Invalid JSON received from {websocket.remote_address}: {message}")
            except KeyError as e:
                error(f"KeyError: {e} in message: {message}")

    except websockets.ConnectionClosed:
        log(f"Client disconnected: {websocket.remote_address} with ID: {client_id}")
    finally:
        if client_id in connected_clients: #check if the client id exists
            del connected_clients[client_id]  # Remove the client from the dictionary

async def start_dolphin():
    """Start the Dolphin emulator."""
    global dolphin_process
    if is_dolphin_running():
        log("Dolphin is already running.")
        return

    try:
        log(f"Starting Dolphin from: {DOLPHIN_PATH}")
        dolphin_process = subprocess.Popen([DOLPHIN_PATH],
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)
        # Consider adding a timeout here, in case Dolphin fails to start.
        #  Use a try/except around the communicate() call.
        # For example:
        # try:
        #     stdout, stderr = dolphin_process.communicate(timeout=10) # 10 second timeout
        # except subprocess.TimeoutExpired:
        #     dolphin_process.kill()
        #     error("Dolphin failed to start within the timeout.")

        log("Dolphin started.")
    except FileNotFoundError:
        error(f"Dolphin executable not found at: {DOLPHIN_PATH}")
        for client in connected_clients.values(): # Iterate over the values in connected_clients
            await client.send(json.dumps({"error": "Dolphin executable not found"}))
    except Exception as e:
        error(f"Error starting Dolphin: {e}")
        for client in connected_clients.values():
            await client.send(json.dumps({"error": f"Failed to start Dolphin: {e}"}))

async def stop_dolphin():
    """Stop the Dolphin emulator."""
    global dolphin_process
    if not is_dolphin_running():
        log("Dolphin is not running.")
        return

    try:
        log("Stopping Dolphin.")
        if dolphin_process:
           dolphin_process.terminate() # Or .kill(), if terminate doesn't work.
           dolphin_process.wait() # Wait for the process to exit
        # Use a try/except around the communicate() call if you used it in start_dolphin
        log("Dolphin stopped.")
    except Exception as e:
        error(f"Error stopping Dolphin: {e}")
        for client in connected_clients.values():
            await client.send(json.dumps({"error": f"Failed to stop Dolphin: {e}"}))
    finally:
        dolphin_process = None

async def main():
    """Main function to start the WebSocket server."""
    async with websockets.serve(handle_client, HOST, PORT):
        log(f"WebSocket server started at ws://{HOST}:{PORT}")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    # Check if Dolphin is running on startup
    if is_dolphin_running():
        log("Dolphin is already running on startup.")

    # Set the asyncio debug flag, which can be helpful for development.
    # asyncio.get_event_loop().set_debug(True) # VERY verbose, remove if needed
    asyncio.run(main())
