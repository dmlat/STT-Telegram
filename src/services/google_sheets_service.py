import gspread
import asyncio
from oauth2client.service_account import ServiceAccountCredentials
from src.config import GOOGLE_CREDENTIALS_PATH, SHEET_NAME
from datetime import datetime

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]

class GoogleSheetsService:
    def __init__(self):
        self.client = None
        self.sheet = None

    def connect(self):
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                GOOGLE_CREDENTIALS_PATH, SCOPE
            )
            self.client = gspread.authorize(creds)
            try:
                self.sheet = self.client.open(SHEET_NAME)
            except gspread.SpreadsheetNotFound:
                # Create if not exists (optional, but helpful)
                self.sheet = self.client.create(SHEET_NAME)
                self.sheet.share(creds.service_account_email, perm_type='user', role='owner')
                # Create worksheets
                try:
                    self.sheet.add_worksheet(title="Users", rows=1000, cols=10)
                    self.sheet.add_worksheet(title="VoiceMessages", rows=1000, cols=10)
                    # Remove default 'Sheet1'
                    sheet1 = self.sheet.get_worksheet(0)
                    if sheet1.title == "Sheet1":
                        self.sheet.del_worksheet(sheet1)
                except:
                    pass
            
            # Ensure headers
            self._ensure_headers()
            print("Connected to Google Sheets")
        except Exception as e:
            print(f"Failed to connect to Google Sheets: {e}")

    def _ensure_headers(self):
        # Users Sheet
        users_ws = self.sheet.worksheet("Users")
        if not users_ws.row_values(1):
            users_ws.append_row([
                "User ID", "Reg Date", "Last Activity", "Total Msgs", 
                "Msgs 30d", "Msgs 7d", "Avg Length (sec)", "Avg Chars"
            ])

        # Voice Messages Sheet
        voice_ws = self.sheet.worksheet("VoiceMessages")
        if not voice_ws.row_values(1):
            voice_ws.append_row([
                "Date", "User ID", "Process Speed (sec)", "Length (sec)", "Length (chars)"
            ])

    def update_user_row_sync(self, stats: dict):
        if not self.sheet:
            return
        
        ws = self.sheet.worksheet("Users")
        # Check if user exists
        cell = ws.find(str(stats['user_id']), in_column=1)
        
        row_data = [
            str(stats['user_id']),
            str(stats['reg_date']),
            str(stats['last_activity']),
            stats['total_msgs'],
            stats['msgs_30d'],
            stats['msgs_7d'],
            stats['avg_length_sec'],
            stats['avg_chars']
        ]

        if cell:
            # Update existing row
            # gspread uses 1-based indexing
            ws.update(range_name=f"A{cell.row}:H{cell.row}", values=[row_data])
        else:
            # Append new
            ws.append_row(row_data)

    def add_voice_message_sync(self, data: dict):
        if not self.sheet:
            return
        
        ws = self.sheet.worksheet("VoiceMessages")
        ws.append_row([
            str(datetime.utcnow()),
            str(data['user_id']),
            data['process_speed'],
            data['length_sec'],
            data['length_chars']
        ])

    async def update_user_stats(self, stats: dict):
        await asyncio.to_thread(self.update_user_row_sync, stats)

    async def log_voice_message(self, data: dict):
        await asyncio.to_thread(self.add_voice_message_sync, data)

gs_service = GoogleSheetsService()

