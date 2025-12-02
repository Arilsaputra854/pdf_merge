import http.server
import socketserver
import cgi
import os
import uuid
import json
from PyPDF2 import PdfMerger, PdfReader
from PIL import Image

PORT = 8080
BASE_URL = f"http://localhost:{PORT}"
TEMP_DIR = "temp"

os.makedirs(TEMP_DIR, exist_ok=True)

DEFAULT_WIDTH = 595
DEFAULT_HEIGHT = 842


class Handler(http.server.SimpleHTTPRequestHandler):

    def send_json(self, data, status=200):
        response = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def get_pdf_size(self, pdf_path):
        try:
            reader = PdfReader(pdf_path)
            box = reader.pages[0].mediabox
            return float(box.width), float(box.height)
        except:
            return DEFAULT_WIDTH, DEFAULT_HEIGHT

    def convert_image_to_pdf(self, input_path, target_width, target_height):
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

    def do_POST(self):

        if self.path != "/merge":
            return self.send_json({"error": "Endpoint not found"}, 404)

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST"}
        )

        if "files" not in form:
            return self.send_json({"error": "No files uploaded"}, 400)

        files = form["files"]
        if not isinstance(files, list):
            files = [files]

        # SIMPAN SEMUA FILE SEKALI SAJA
        uploaded = []
        for f in files:
            temp_path = f"{TEMP_DIR}/{uuid.uuid4()}_{f.filename}"
            with open(temp_path, "wb") as tmp:
                tmp.write(f.file.read())
            uploaded.append({"name": f.filename.lower(), "path": temp_path})

        # 1️⃣ cari ukuran pdf pertama
        target_width = DEFAULT_WIDTH
        target_height = DEFAULT_HEIGHT

        for f in uploaded:
            if f["name"].endswith(".pdf"):
                target_width, target_height = self.get_pdf_size(f["path"])
                break

        # 2️⃣ merge final
        merger = PdfMerger()
        temp_files = []

        for f in uploaded:
            filename = f["name"]
            path = f["path"]

            if filename.endswith((".jpg", ".jpeg", ".png")):
                pdf_path = self.convert_image_to_pdf(path, int(target_width), int(target_height))
                temp_files.append(path)
                temp_files.append(pdf_path)
                merger.append(pdf_path)
            else:
                temp_files.append(path)
                merger.append(path)

        # output final
        filename_field = form.getvalue("filename")
        output_name = filename_field if filename_field else "merged"

        if not output_name.lower().endswith(".pdf"):
            output_name += ".pdf"

        final_name = f"{output_name.replace('.pdf','')}_{uuid.uuid4()}.pdf"
        final_path = f"{TEMP_DIR}/{final_name}"

        merger.write(final_path)
        merger.close()

        # hapus temp
        for p in temp_files:
            if os.path.exists(p):
                os.remove(p)

        return self.send_json({
            "status": "success",
            "message": "Merged successfully",
            "url": f"{BASE_URL}/{final_path}",
            "filename": final_name
        })


with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"🚀 Server running on http://localhost:{PORT}")
    httpd.serve_forever()
