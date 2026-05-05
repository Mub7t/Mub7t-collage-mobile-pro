# RL Maintenance Report Generator

A web application for RL field maintenance teams that automates the creation of
end-of-day maintenance reports from supervisor assignment email images.

---

## What it does

1. Technician uploads a screenshot / photo of the supervisor's assignment email.
2. The system performs OCR and extracts task information automatically.
3. The technician reviews and edits the extracted data on a clean web page.
4. The technician fills in "Action Taken" for each task, selects the status, and clicks Generate.
5. A professionally formatted Microsoft Word `.docx` report is downloaded instantly.

---

## Project Structure

```
rl_report_generator/
│
├── app.py                     # Flask entry point & routes
├── requirements.txt
├── README.md
│
├── services/
│   ├── ocr_service.py         # OCR extraction (swappable with Vision AI)
│   ├── parser_service.py      # Text → structured task data
│   └── report_service.py      # python-docx report generation
│
├── static/
│   ├── css/style.css
│   └── js/main.js
│
├── templates/
│   ├── index.html             # Home page
│   ├── upload.html            # Image upload page
│   └── review.html            # Review & edit page
│
├── uploads/                   # Temporary uploaded images
└── generated_reports/         # Generated .docx files
```

---

## Setup & Installation

### 1. Prerequisites

- Python 3.10 or later
- Tesseract OCR installed on your operating system

**Install Tesseract:**

- **Ubuntu / Debian:**
  ```bash
  sudo apt update && sudo apt install tesseract-ocr
  ```

- **macOS (Homebrew):**
  ```bash
  brew install tesseract
  ```

- **Windows:**
  Download and install from https://github.com/UB-Mannheim/tesseract/wiki  
  Then add the Tesseract folder to your `PATH`, or set the path in `ocr_service.py`:
  ```python
  pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
  ```

---

### 2. Create a virtual environment

```bash
cd rl_report_generator
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

---

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Run the application

```bash
python app.py
```

Then open your browser at: **http://localhost:5000**

---

## How to use

1. Click **"Prepare Report"** on the home page.
2. Upload a clear screenshot or photo of the supervisor's assignment email.
3. Click **"Extract Data"** — the system reads the image and parses the tasks.
4. On the **Review** page:
   - Correct any extraction errors (Supervisor, Team, Date, Shift, Time).
   - Fill in **Action Taken** for each task.
   - Set the **Current Status** (Solved / Pending) for each task.
   - Add or remove rows as needed.
5. Click **"Generate Word Report"** — the `.docx` file downloads automatically.

---

## OCR Backends

The OCR layer (`services/ocr_service.py`) is modular.

### Default: pytesseract + Pillow

Requires the Tesseract binary installed on the OS (see above).

### Alternative: EasyOCR

EasyOCR runs entirely in Python with no OS-level installation.

```bash
pip install easyocr
```

The system will fall back to EasyOCR automatically if pytesseract fails.

---

## Connecting a Vision AI Service

For much better accuracy on low-quality or complex images, you can replace the
OCR backend with an AI Vision API. Open `services/ocr_service.py` and follow
the commented-out instructions at the bottom of the file.

### OpenAI Vision (GPT-4o)

```bash
pip install openai
export OPENAI_API_KEY=sk-...
```

Then uncomment and fill in the OpenAI section in `ocr_service.py`.

### Claude Vision (Anthropic)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

Then uncomment and fill in the Anthropic section in `ocr_service.py`.

No other code changes are needed — the rest of the application calls
`extract_text_from_image()` and is unaffected by which backend you use.

---

## Environment Variables

| Variable     | Default              | Description                         |
|--------------|----------------------|-------------------------------------|
| `SECRET_KEY` | `rl-report-secret-key-2026` | Flask session secret key    |
| `OPENAI_API_KEY` | —                | Required only if using OpenAI Vision |
| `ANTHROPIC_API_KEY` | —             | Required only if using Claude Vision |

---

## Supported Image Formats

PNG, JPG, JPEG — maximum **10 MB** per file.

---

## Report Output

The generated `.docx` file:

- Is compatible with Microsoft Word (2016 and later).
- Uses landscape orientation for wide tables.
- Has a professional dark-navy header row.
- Shows "Solved" in green, "Pending" in amber.
- Highlights "Waiting for RM confirmation" in yellow.
- Is named `RL_Maintenance_Report_YYYY-MM-DD.docx`.

---

## Sample Test Text

If you want to test the parser without an image, you can call
`parse_email_text()` directly:

```python
from services.parser_service import parse_email_text



---

## Notes

- No login or authentication is required in this version.
- Uploaded images are stored temporarily in `uploads/`.
- Generated reports are stored in `generated_reports/`.
- Both folders can be cleaned out periodically without affecting the application.
- The system never invents SAP Notification numbers or site IDs.
- All fields are manually editable before report generation.
