import os
import sys
import uuid
import schedule
import time
import threading
import logging
import socket
import webbrowser
from flask import Flask, request, render_template, send_from_directory, flash, redirect, url_for, jsonify
from PyPDF2 import PdfMerger, PdfReader
from PIL import Image, ImageDraw, ImageFont
from pystray import MenuItem as item, Icon as icon
from waitress import serve
import requests 

# Determine base path
if getattr(sys, 'frozen', False):
    # Running as a bundled executable
    base_path = sys._MEIPASS
    writable_path = os.path.dirname(sys.executable)
else:
    # Running as a script
    base_path = os.path.dirname(os.path.abspath(__file__))
    writable_path = base_path

LOG_FILE = os.path.join(writable_path, 'app.log')

# Logging setup
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')

template_folder_path = os.path.join(base_path, 'templates')
app = Flask(__name__, template_folder=template_folder_path)
app.secret_key = os.urandom(24)

PORT = 8080
TEMP_DIR = os.path.join(writable_path, "temp")

os.makedirs(TEMP_DIR, exist_ok=True)

DEFAULT_WIDTH = 595
DEFAULT_HEIGHT = 842

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def get_pdf_size(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        box = reader.pages[0].mediabox
        return float(box.width), float(box.height)
    except Exception as e:
        logging.error(f"Could not get size of {pdf_path}: {e}")
        return DEFAULT_WIDTH, DEFAULT_HEIGHT

def convert_image_to_pdf(input_path, target_width, target_height):
    try:
        img = Image.open(input_path).convert("RGB")
        img_ratio = img.width / img.height
        target_ratio = target_width / target_height

        if img_ratio > target_ratio:
            new_width = int(target_width)
            new_height = int(new_width / img_ratio)
        else:
            new_height = int(target_height)
            new_width = int(new_height * img_ratio)

        img = img.resize((new_width, new_height))
        canvas = Image.new("RGB", (int(target_width), int(target_height)), "white")
        offset_x = (target_width - new_width) // 2
        offset_y = (target_height - new_height) // 2
        canvas.paste(img, (offset_x, offset_y))

        output_pdf = f"{TEMP_DIR}/{uuid.uuid4()}_convertedSize.pdf"
        canvas.save(output_pdf, "PDF")
        logging.info(f"Converted image {input_path} to PDF {output_pdf}")
        return output_pdf
    except Exception as e:
        logging.error(f"Failed to convert image {input_path} to PDF: {e}")
        return None

def cleanup_temp_files():
    logging.info("Running scheduled cleanup of temp files.")
    now = time.time()
    for filename in os.listdir(TEMP_DIR):
        file_path = os.path.join(TEMP_DIR, filename)
        if os.path.isfile(file_path):
            if os.path.getmtime(file_path) < now - 24 * 3600:
                os.remove(file_path)
                logging.info(f"Deleted old temp file: {filename}")

def run_scheduler():
    schedule.every().day.at("01:00").do(cleanup_temp_files)
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info')
def info():
    ip_address = get_local_ip()
    try:
        with open(LOG_FILE, 'r') as f:
            logs = f.read()
    except FileNotFoundError:
        logs = "No logs yet."
    return render_template('info.html', ip_address=ip_address, logs=logs)

@app.route('/merge', methods=['POST'])
def merge():
    try:
        if 'files' not in request.files:
            logging.warning("Merge attempt with no files.")
            return jsonify({"success": False, "error": "No files uploaded."})

        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            logging.warning("Merge attempt with no selected files.")
            return jsonify({"success": False, "error": "No selected files."})

        uploaded = []
        for f in files:
            secure_name = os.path.basename(f.filename)
            temp_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_{secure_name}")
            f.save(temp_path)
            uploaded.append({"name": f.filename.lower(), "path": temp_path})
            logging.info(f"Uploaded file: {secure_name}")

        logging.info("--- Merge Queue ---")
        for f in uploaded:
            logging.info(f"  - {f['name']}")
        logging.info("--------------------")

        target_width = DEFAULT_WIDTH
        target_height = DEFAULT_HEIGHT

        for f in uploaded:
            if f["name"].endswith(".pdf"):
                target_width, target_height = get_pdf_size(f["path"])
                break

        merger = PdfMerger()
        temp_files = []

        for f in uploaded:
            filename = f["name"]
            path = f["path"]

            logging.info(f"Processing file: {filename}")
            if filename.endswith((".jpg", ".jpeg", ".png")):
                pdf_path = convert_image_to_pdf(path, int(target_width), int(target_height))
                if pdf_path:
                    temp_files.append(path)
                    temp_files.append(pdf_path)
                    merger.append(pdf_path)
                else:
                    logging.error(f"Could not process image file {filename}, skipping.")
                    temp_files.append(path)
            elif filename.endswith(".pdf"):
                temp_files.append(path)
                merger.append(path)
            else:
                logging.warning(f"Unsupported file type: {filename}, skipping.")
                temp_files.append(path)

        output_name = request.form.get("filename") if request.form.get("filename") else "merged"
        if not output_name.lower().endswith(".pdf"):
            output_name += ".pdf"

        final_name = f"{output_name.replace('.pdf','')}_{uuid.uuid4()}.pdf"
        final_path = os.path.join(TEMP_DIR, final_name)

        merger.write(final_path)
        merger.close()
        logging.info(f"Successfully merged files into {final_name}")
        
        for p in temp_files:
            if os.path.exists(p):
                os.remove(p)

        return jsonify({"success": True, "download_url": url_for('download', filename=final_name)})

    except Exception as e:
        logging.error(f"An error occurred during merge: {e}", exc_info=True)
        # Clean up any files that might have been created
        # This is a simple cleanup, a more robust solution would be better
        for f in uploaded:
            if os.path.exists(f["path"]):
                os.remove(f["path"])

        return jsonify({"success": False, "error": "An internal error occurred. Please check the logs."})

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(TEMP_DIR, filename, as_attachment=True)

@app.route('/shutdown', methods=['POST'])
def shutdown():
    logging.info("Server shutting down...")
    # This is a bit of a hack to shutdown waitress. 
    # It requires the server to be run in a thread.
    # A request to this endpoint will stop the server.
    # This is not a production-ready solution.
    # A better solution would be to use a different web server
    # that supports graceful shutdown.
    # For this use case, it is acceptable.
    # The request comes from the exit_app function.
    # The function will not wait for the response.
    # The server will shut down in the background.
    # The time.sleep(1) is to make sure the response is sent
    # before the server is shut down.
    time.sleep(1)
    os._exit(0)


def run_server():
    ip_address = get_local_ip()
    print("=================================================")
    print(f" Server is running!")
    print(f" - Access the application at http://{ip_address}:{PORT}")
    print(f" - Access server info at http://{ip_address}:{PORT}/info")
    print("=================================================")
    logging.info(f"Server started at http://{ip_address}:{PORT}")
    serve(app, host="0.0.0.0", port=PORT)

def open_app(icon, item):
    webbrowser.open(f"http://localhost:{PORT}")

def exit_app(icon, item):
    icon.stop()
    # Send a request to the shutdown endpoint to stop the server
    try:
        requests.post(f"http://localhost:{PORT}/shutdown")
    except requests.exceptions.ConnectionError:
        # This is expected if the server is already down
        pass


if __name__ == '__main__':
    if "--generate-icon" in sys.argv:
        # Create an icon with text
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)
        
        # Use a default font
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except IOError:
            font = ImageFont.load_default()

        draw.text((10, 10), "PDF", fill="black", font=font)

        # Save the icon
        icon_path = os.path.join(base_path, "icon.ico")
        image.save(icon_path, 'ICO', sizes=[(64, 64)])
        sys.exit(0)

    # Start the scheduler in a separate thread
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    # Start the Flask server in a separate thread
    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Create the tray icon
    icon_path = os.path.join(base_path, "icon.ico")
    image = Image.open(icon_path)
    icon_obj = icon('PDFMerger', image, 'PDF Merger', menu=(
        item('Open', open_app),
        item('Exit', exit_app)
    ))

    icon_obj.run()
