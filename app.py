import os
import uuid
import schedule
import time
import threading
from flask import Flask, request, render_template, send_from_directory, flash, redirect, url_for
from PyPDF2 import PdfMerger, PdfReader
from PIL import Image

app = Flask(__name__)
app.secret_key = os.urandom(24)

PORT = 8080
BASE_URL = f"http://localhost:{PORT}"
TEMP_DIR = "temp"

os.makedirs(TEMP_DIR, exist_ok=True)

DEFAULT_WIDTH = 595
DEFAULT_HEIGHT = 842

def get_pdf_size(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        box = reader.pages[0].mediabox
        return float(box.width), float(box.height)
    except:
        return DEFAULT_WIDTH, DEFAULT_HEIGHT

def convert_image_to_pdf(input_path, target_width, target_height):
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
    return output_pdf

def cleanup_temp_files():
    now = time.time()
    for filename in os.listdir(TEMP_DIR):
        file_path = os.path.join(TEMP_DIR, filename)
        if os.path.isfile(file_path):
            if os.path.getmtime(file_path) < now - 24 * 3600:
                os.remove(file_path)
                print(f"Deleted old temp file: {filename}")

def run_scheduler():
    schedule.every().day.at("01:00").do(cleanup_temp_files)
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/merge', methods=['POST'])
def merge():
    if 'files' not in request.files:
        flash('No files uploaded')
        return redirect(url_for('index'))

    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        flash('No selected files')
        return redirect(url_for('index'))

    uploaded = []
    for f in files:
        temp_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_{f.filename}")
        f.save(temp_path)
        uploaded.append({"name": f.filename.lower(), "path": temp_path})

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

        if filename.endswith((".jpg", ".jpeg", ".png")):
            pdf_path = convert_image_to_pdf(path, int(target_width), int(target_height))
            temp_files.append(path)
            temp_files.append(pdf_path)
            merger.append(pdf_path)
        elif filename.endswith(".pdf"):
            temp_files.append(path)
            merger.append(path)
        else:
            # unsupported file type
            temp_files.append(path)


    output_name = request.form.get("filename") if request.form.get("filename") else "merged"
    if not output_name.lower().endswith(".pdf"):
        output_name += ".pdf"

    final_name = f"{output_name.replace('.pdf','')}_{uuid.uuid4()}.pdf"
    final_path = os.path.join(TEMP_DIR, final_name)

    merger.write(final_path)
    merger.close()

    for p in temp_files:
        if os.path.exists(p):
            os.remove(p)

    return redirect(url_for('download', filename=final_name))

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(TEMP_DIR, filename, as_attachment=True)

if __name__ == '__main__':
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    app.run(port=PORT, debug=True)
