"""
SE 445 – HW1 & HW2: Social Content Repurposer
========================================
Workflow Architecture (matches rubric exactly):
  Trigger (HTTP POST) → Processing Function → External API (Google Sheets) → AI Completion (Gemini)

This script implements a FastAPI application that:
1. TRIGGER:       Receives source text via an HTTP POST endpoint (/repurpose).
2. PROCESSING:    Validates and extracts the source text from the incoming JSON payload.
3. EXTERNAL API:  Saves the raw data to Google Sheets as a new row.
4. AI COMPLETION: Sends the text to Google Gemini API to generate a short social-media summary,
                  then updates the Google Sheets row with the AI result.
"""

import os
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import google.generativeai as genai
from dotenv import load_dotenv

# Google Sheets imports
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# 0. Configuration
# ---------------------------------------------------------------------------

# Load environment variables from .env file (if present)
load_dotenv()

# Read the Gemini API key from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure the Gemini client
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Google Sheets configuration
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "credentials.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# Output directory for generated summaries (local backup)
OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# 1. FastAPI App Initialization
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Social Content Repurposer – HW1 & HW2",
    description="SE 445 Prompt Engineering – Homework 1 & 2: Component Foundations & Data Persistence",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# 2. Data Models (Pydantic)
# ---------------------------------------------------------------------------

class RepurposeRequest(BaseModel):
    """
    Incoming payload schema.
    - source_text: The long-form content (blog post, YouTube description, etc.)
                   that will be summarized by AI.
    - author_email: The email of the user submitting the content.
    """
    source_text: str
    author_email: str = ""


class RepurposeResponse(BaseModel):
    """
    Response payload returned to the caller.
    - status:       Whether the operation succeeded.
    - twitter_variant: Short summary for Twitter/X.
    - linkedin_variant: Professional summary for LinkedIn.
    - instagram_variant: Casual summary for Instagram.
    - detected_tone: The detected tone/intent of the original text.
    - output_file:  Path to the local backup file where the summary was saved.
    - sheet_row:    The row number in Google Sheets where data was stored.
    - timestamp:    When the request was processed.
    """
    status: str
    twitter_variant: str
    linkedin_variant: str
    instagram_variant: str
    detected_tone: str
    output_file: str
    sheet_row: int
    timestamp: str


# ---------------------------------------------------------------------------
# 3. Processing Function
# ---------------------------------------------------------------------------

def process_input(source_text: str, author_email: str) -> dict:
    """
    STEP 2 – Processing Function
    Validates the incoming text and email.
    Returns a dictionary with the cleaned text and metadata.
    """
    # Strip whitespace
    cleaned_text = source_text.strip()
    is_valid = True
    status = "processing"

    # Basic validation: must have a minimum length
    if not cleaned_text or len(cleaned_text) < 20:
        is_valid = False
        status = "Invalid (Text too short)"
        
    # Validation: Email must contain @
    if not author_email or "@" not in author_email:
        is_valid = False
        status = "Invalid (Bad Email)"

    # Return processed data
    return {
        "original_length": len(source_text),
        "cleaned_text": cleaned_text,
        "word_count": len(cleaned_text.split()),
        "author_email": author_email,
        "is_valid": is_valid,
        "status": status,
    }


# ---------------------------------------------------------------------------
# 4. External API – Google Sheets Connector
# ---------------------------------------------------------------------------

def get_sheets_client():
    """
    Creates and returns an authorized Google Sheets client.
    Uses a service account credentials JSON file.
    """
    creds_path = Path(__file__).parent / GOOGLE_SHEETS_CREDENTIALS

    if not creds_path.exists():
        raise FileNotFoundError(
            f"Google Sheets credentials file not found at: {creds_path}. "
            "Please download your service account JSON key and place it in the project folder."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    client = gspread.authorize(credentials)
    return client


def save_to_google_sheets(metadata: dict) -> int:
    """
    STEP 3 – External API (Google Sheets)
    Saves the raw processed data to Google Sheets as a new row.
    Returns the row number where data was inserted.

    This step happens BEFORE the AI call, matching the required architecture:
    Trigger → Processing → External API → AI Completion
    """
    if not GOOGLE_SHEET_ID:
        raise RuntimeError(
            "GOOGLE_SHEET_ID is not set. "
            "Please add your Google Sheet ID to the .env file."
        )

    client = get_sheets_client()
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

    # Prepare the row with raw data (AI columns will be updated later)
    timestamp = datetime.now().isoformat()
    row_data = [
        timestamp,                                      # Column A: Timestamp
        metadata["author_email"],                       # Column B: Author Email
        metadata["cleaned_text"][:500],                 # Column C: Source Text (first 500 chars)
        metadata["original_length"],                    # Column D: Original Length
        metadata["word_count"],                         # Column E: Word Count
        "pending",                                      # Column F: Twitter
        "pending",                                      # Column G: LinkedIn
        "pending",                                      # Column H: Instagram
        "pending",                                      # Column I: Tone
        metadata["status"],                             # Column J: Status
    ]

    # Append the row to the sheet
    sheet.append_row(row_data, value_input_option="USER_ENTERED")

    # Get the row number of the newly added row
    all_values = sheet.get_all_values()
    row_number = len(all_values)

    return row_number


def update_sheets_with_ai_result(row_number: int, ai_data: dict):
    """
    After the AI generates the variants, update the Google Sheets row
    with the AI results and mark the status as 'completed'.
    """
    if not GOOGLE_SHEET_ID:
        return

    client = get_sheets_client()
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

    # Update Columns F-J
    sheet.update_cell(row_number, 6, ai_data.get("twitter_variant", ""))
    sheet.update_cell(row_number, 7, ai_data.get("linkedin_variant", ""))
    sheet.update_cell(row_number, 8, ai_data.get("instagram_variant", ""))
    sheet.update_cell(row_number, 9, ai_data.get("detected_tone", ""))
    sheet.update_cell(row_number, 10, "completed")


# ---------------------------------------------------------------------------
# 5. AI Completion Function (Gemini)
# ---------------------------------------------------------------------------

def generate_summary(cleaned_text: str) -> dict:
    """
    STEP 4 – AI Completion
    Sends the cleaned text to Google Gemini and asks it to produce
    3 variants (Twitter, LinkedIn, Instagram) and detect the tone in JSON format.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Please create a .env file with your key. "
            "See .env.example for reference."
        )

    # Build the prompt
    prompt = (
        "You are a social media content strategist. "
        "Take the following source text and generate 3 variants and detect the tone.\n\n"
        "1. twitter_variant: Short, punchy, max 280 characters.\n"
        "2. linkedin_variant: Professional, slightly longer.\n"
        "3. instagram_variant: Casual, engaging, with 3-5 hashtags.\n"
        "4. detected_tone: The intent/urgency of the text (e.g., Promotional, Urgent, Informative, Casual).\n\n"
        "You MUST return the output ONLY as a valid JSON object with these exact keys: "
        "\"twitter_variant\", \"linkedin_variant\", \"instagram_variant\", \"detected_tone\". "
        "Do not include any markdown formatting like ```json\n\n"
        "--- SOURCE TEXT ---\n"
        f"{cleaned_text}\n"
        "--- END OF SOURCE TEXT ---\n"
    )

    # Call Gemini API
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)

    try:
        # Strip any markdown formatting Gemini might add
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        return json.loads(result_text.strip())
    except json.JSONDecodeError:
        # Fallback if JSON parsing fails
        return {
            "twitter_variant": "Error generating JSON",
            "linkedin_variant": "Error generating JSON",
            "instagram_variant": "Error generating JSON",
            "detected_tone": "Unknown"
        }


# ---------------------------------------------------------------------------
# 6. Local Backup Function (Save to File)
# ---------------------------------------------------------------------------

def save_local_backup(ai_data: dict, metadata: dict) -> str:
    """
    Saves a local backup of the AI-generated variants alongside metadata.
    Returns the path of the created file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"summary_{timestamp}.txt"
    filepath = OUTPUT_DIR / filename

    content = (
        f"=== Social Content Repurposer – Output ===\n"
        f"Timestamp       : {datetime.now().isoformat()}\n"
        f"Author Email    : {metadata['author_email']}\n"
        f"Original Length : {metadata['original_length']} characters\n"
        f"Word Count      : {metadata['word_count']} words\n"
        f"{'=' * 45}\n\n"
        f"AI-GENERATED VARIANTS:\n"
        f"[TWITTER]: {ai_data.get('twitter_variant')}\n\n"
        f"[LINKEDIN]: {ai_data.get('linkedin_variant')}\n\n"
        f"[INSTAGRAM]: {ai_data.get('instagram_variant')}\n\n"
        f"[TONE]: {ai_data.get('detected_tone')}\n\n"
        f"{'=' * 45}\n"
        f"ORIGINAL TEXT (first 500 chars):\n"
        f"{metadata['cleaned_text'][:500]}\n"
    )

    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


# ---------------------------------------------------------------------------
# 7. API Endpoint – Trigger
# ---------------------------------------------------------------------------

@app.post("/repurpose", response_model=RepurposeResponse)
async def repurpose_content(request: RepurposeRequest):
    """
    STEP 1 – Trigger (HTTP POST Endpoint)

    Receives source text and executes the full pipeline:
      Trigger → Processing → Google Sheets (External API) → AI Completion

    This follows the required architecture exactly:
    1. Trigger fires (this endpoint)
    2. Processing function validates and cleans data
    3. External API saves raw data to Google Sheets
    4. AI Completion generates social media summary
    5. Google Sheets row is updated with AI result
    """
    try:
        # ── Step 2: Processing ──
        metadata = process_input(request.source_text, request.author_email)

        # ── Step 3: External API (Google Sheets) ──
        # Save raw data to Google Sheets BEFORE AI processing
        row_number = save_to_google_sheets(metadata)

        # Check validation
        if not metadata["is_valid"]:
            # Stop processing AI if invalid, but data is already saved to Sheets with "Invalid" status
            raise HTTPException(status_code=400, detail=metadata["status"])

        # ── Step 4: AI Completion ──
        ai_data = generate_summary(metadata["cleaned_text"])

        # ── Update Sheets with AI result ──
        update_sheets_with_ai_result(row_number, ai_data)

        # ── Local backup (bonus) ──
        output_file = save_local_backup(ai_data, metadata)

        # Return response
        return RepurposeResponse(
            status="success",
            twitter_variant=ai_data.get("twitter_variant", ""),
            linkedin_variant=ai_data.get("linkedin_variant", ""),
            instagram_variant=ai_data.get("instagram_variant", ""),
            detected_tone=ai_data.get("detected_tone", ""),
            output_file=output_file,
            sheet_row=row_number,
            timestamp=datetime.now().isoformat(),
        )

    except HTTPException as e:
        raise e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# ---------------------------------------------------------------------------
# 8. Web Interface
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    """Returns the web interface for the application."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Social Content Repurposer</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-color: #0f172a;
                --surface: #1e293b;
                --primary: #6366f1;
                --primary-hover: #4f46e5;
                --text-main: #f8fafc;
                --text-muted: #94a3b8;
            }
            body {
                font-family: 'Outfit', sans-serif;
                background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
                color: var(--text-main);
                margin: 0;
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .container {
                background: rgba(30, 41, 59, 0.7);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 20px;
                padding: 40px;
                width: 90%;
                max-width: 800px;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
                animation: fadeIn 0.8s ease-out;
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }
            h1 {
                margin-top: 0;
                font-weight: 600;
                background: linear-gradient(to right, #818cf8, #c084fc);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            p.subtitle {
                color: var(--text-muted);
                margin-bottom: 24px;
            }
            textarea {
                width: 100%;
                height: 180px;
                background: rgba(15, 23, 42, 0.6);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                padding: 16px;
                color: var(--text-main);
                font-family: inherit;
                font-size: 16px;
                resize: vertical;
                transition: border-color 0.3s ease, box-shadow 0.3s ease;
                box-sizing: border-box;
                margin-bottom: 20px;
            }
            textarea:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
            }
            button {
                background: var(--primary);
                color: white;
                border: none;
                border-radius: 12px;
                padding: 14px 28px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                width: 100%;
                display: flex;
                justify-content: center;
                align-items: center;
                gap: 10px;
            }
            button:hover {
                background: var(--primary-hover);
                transform: translateY(-2px);
                box-shadow: 0 10px 15px -3px rgba(99, 102, 241, 0.4);
            }
            button:active {
                transform: translateY(0);
            }
            button:disabled {
                opacity: 0.6;
                cursor: not-allowed;
                transform: none;
            }
            .loading-spinner {
                display: none;
                width: 20px;
                height: 20px;
                border: 3px solid rgba(255,255,255,0.3);
                border-radius: 50%;
                border-top-color: white;
                animation: spin 1s ease-in-out infinite;
            }
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            #result-container {
                display: none;
                margin-top: 30px;
                padding: 24px;
                background: rgba(15, 23, 42, 0.5);
                border-left: 4px solid #34d399;
                border-radius: 0 12px 12px 0;
                animation: slideIn 0.5s ease-out;
            }
            @keyframes slideIn {
                from { opacity: 0; transform: translateX(-20px); }
                to { opacity: 1; transform: translateX(0); }
            }
            #summary-output {
                font-size: 18px;
                line-height: 1.6;
                margin-bottom: 16px;
            }
            .meta-text {
                font-size: 13px;
                color: var(--text-muted);
                margin: 4px 0;
            }
            .error {
                border-left-color: #f87171 !important;
            }
            .pipeline-info {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
                margin-bottom: 24px;
            }
            .pipeline-step {
                background: rgba(99, 102, 241, 0.15);
                border: 1px solid rgba(99, 102, 241, 0.3);
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
                color: #a5b4fc;
                display: flex;
                align-items: center;
                gap: 4px;
            }
            .pipeline-arrow {
                color: var(--text-muted);
                font-size: 14px;
            }
            .input-group {
                margin-bottom: 20px;
            }
            .input-group label {
                display: block;
                margin-bottom: 8px;
                font-size: 14px;
                color: var(--text-muted);
            }
            .input-group input {
                width: 100%;
                background: rgba(15, 23, 42, 0.6);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                padding: 14px;
                color: var(--text-main);
                font-family: inherit;
                font-size: 16px;
                box-sizing: border-box;
                transition: border-color 0.3s ease;
            }
            .input-group input:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
            }
            .variant-card {
                background: rgba(15, 23, 42, 0.8);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
                padding: 16px;
                margin-bottom: 12px;
            }
            .variant-card h3 {
                margin-top: 0;
                font-size: 14px;
                color: #818cf8;
                margin-bottom: 8px;
                display: flex;
                align-items: center;
                gap: 6px;
            }
            .variant-text {
                font-size: 15px;
                line-height: 1.5;
            }
            .tone-badge {
                display: inline-block;
                background: rgba(52, 211, 153, 0.2);
                color: #34d399;
                border: 1px solid rgba(52, 211, 153, 0.4);
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 12px;
                margin-bottom: 16px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✨ Social Content Repurposer</h1>
            <p class="subtitle">SE 445 – HW3 | Paste text and provide an email to generate multi-platform social variants via AI.</p>

            <div class="pipeline-info">
                <span class="pipeline-step">1️⃣ HTTP Trigger</span>
                <span class="pipeline-arrow">→</span>
                <span class="pipeline-step">2️⃣ Validation (Email)</span>
                <span class="pipeline-arrow">→</span>
                <span class="pipeline-step">3️⃣ AI Analysis (JSON)</span>
                <span class="pipeline-arrow">→</span>
                <span class="pipeline-step">4️⃣ CRM/Sheets</span>
            </div>

            <div class="input-group">
                <label for="authorEmail">Author Email (Required for Validation)</label>
                <input type="email" id="authorEmail" placeholder="e.g., student@atilim.edu.tr">
            </div>

            <div class="input-group">
                <label for="sourceText">Source Content</label>
                <textarea id="sourceText" placeholder="Paste your blog post, article, or video transcript here..."></textarea>
            </div>

            <button id="generateBtn">
                <span>Generate Variants</span>
                <div class="loading-spinner" id="spinner"></div>
            </button>

            <div id="result-container">
                <div id="tone-output" class="tone-badge"></div>
                <div id="variants-container"></div>
                
                <hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.1); margin: 20px 0;">
                
                <div class="meta-text" id="sheet-output"></div>
                <div class="meta-text" id="file-output"></div>
                <div class="meta-text" id="time-output"></div>
            </div>
        </div>

        <script>
            const btn = document.getElementById('generateBtn');
            const spinner = document.getElementById('spinner');
            const btnText = btn.querySelector('span');
            const resultContainer = document.getElementById('result-container');
            const sourceText = document.getElementById('sourceText');
            const authorEmail = document.getElementById('authorEmail');
            const variantsContainer = document.getElementById('variants-container');

            btn.addEventListener('click', async () => {
                const text = sourceText.value.trim();
                const email = authorEmail.value.trim();
                
                if (!text || !email) {
                    alert('Please provide both an email and the source text!');
                    return;
                }

                btn.disabled = true;
                btnText.textContent = 'Processing Pipeline...';
                spinner.style.display = 'block';
                resultContainer.style.display = 'none';
                resultContainer.classList.remove('error');
                variantsContainer.innerHTML = '';

                try {
                    const response = await fetch('/repurpose', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                            source_text: text,
                            author_email: email
                        })
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        throw new Error(data.detail || 'Validation Error or Server Error');
                    }

                    document.getElementById('tone-output').innerText = '🎭 Detected Tone: ' + data.detected_tone;
                    
                    variantsContainer.innerHTML = `
                        <div class="variant-card">
                            <h3>🐦 Twitter/X Variant</h3>
                            <div class="variant-text">${data.twitter_variant}</div>
                        </div>
                        <div class="variant-card">
                            <h3>💼 LinkedIn Variant</h3>
                            <div class="variant-text">${data.linkedin_variant}</div>
                        </div>
                        <div class="variant-card">
                            <h3>📸 Instagram Variant</h3>
                            <div class="variant-text">${data.instagram_variant}</div>
                        </div>
                    `;

                    document.getElementById('sheet-output').innerText = '📊 Saved to Google Sheets: Row #' + data.sheet_row;
                    document.getElementById('file-output').innerText = '💾 Local backup: ' + data.output_file.split('/').pop();
                    document.getElementById('time-output').innerText = '⏱️ Generated at: ' + new Date(data.timestamp).toLocaleTimeString();
                    resultContainer.style.display = 'block';

                } catch (err) {
                    document.getElementById('tone-output').innerText = '❌ Error';
                    variantsContainer.innerHTML = `<div class="variant-text" style="color:#f87171;">${err.message}</div>`;
                    document.getElementById('sheet-output').innerText = '';
                    document.getElementById('file-output').innerText = '';
                    document.getElementById('time-output').innerText = '';
                    resultContainer.classList.add('error');
                    resultContainer.style.display = 'block';
                } finally {
                    btn.disabled = false;
                    btnText.textContent = 'Generate Variants';
                    spinner.style.display = 'none';
                }
            });
        </script>
    </body>
    </html>
    """
    return html_content


# ---------------------------------------------------------------------------
# 9. Run the server (for direct execution)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
