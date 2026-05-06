import os
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "credentials.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

creds_path = Path(__file__).parent / GOOGLE_SHEETS_CREDENTIALS
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
credentials = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
client = gspread.authorize(credentials)
sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

# Get all data
all_values = sheet.get_all_values()

if len(all_values) <= 1:
    print("No data to migrate.")
    exit()

headers = all_values[0]
old_rows = all_values[1:]

new_rows = []
for row in old_rows:
    # Check if the row is already migrated (e.g. has 10 columns and col B is empty or an email)
    # The old rows only had 6 columns. If it has > 6 columns, it might already be migrated or new.
    # But let's assume all rows with exactly 6 columns are old data.
    
    # Pad row to 6 columns if it's shorter for some reason
    while len(row) < 6:
        row.append("")
        
    if len(row) == 6 or (len(row) > 6 and row[6] == ""):
        # It's an old row
        # Old structure: 0:Timestamp, 1:Source Text, 2:Orig Length, 3:Word Count, 4:AI Summary, 5:Status
        timestamp = row[0]
        source_text = row[1]
        orig_len = row[2]
        word_count = row[3]
        ai_summary = row[4]
        status = row[5]
        
        new_row = [
            timestamp,
            "Legacy Data (HW1/HW2)",  # Author Email
            source_text,              # Source Text
            orig_len,                 # Original Length
            word_count,               # Word Count
            ai_summary,               # Twitter Variant (putting old summary here)
            "N/A",                    # LinkedIn Variant
            "N/A",                    # Instagram Variant
            "N/A",                    # Detected Tone
            status                    # Status
        ]
        new_rows.append(new_row)
    else:
        # Row is already migrated or in new format
        # Pad to 10 columns
        while len(row) < 10:
            row.append("")
        new_rows.append(row[:10])

# Clear the sheet and rewrite everything
sheet.clear()
sheet.update('A1', [headers] + new_rows)

# Re-apply header formatting
sheet.format('A1:J1', {
    "backgroundColor": {
        "red": 0.2,
        "green": 0.2,
        "blue": 0.2
    },
    "textFormat": {
        "foregroundColor": {
            "red": 1.0,
            "green": 1.0,
            "blue": 1.0
        },
        "bold": True
    },
    "horizontalAlignment": "CENTER"
})

print("Successfully migrated old data to match new HW3 headers.")
