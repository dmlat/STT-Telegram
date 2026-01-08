import gspread
import asyncio
import logging
from oauth2client.service_account import ServiceAccountCredentials
from src.config import GOOGLE_CREDENTIALS_PATH, SHEET_NAME
from datetime import datetime, timezone

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
                logging.error(f"Sheet {SHEET_NAME} not found.")
                return
            
            self._ensure_headers()
            
        except Exception as e:
            logging.error(f"Failed to connect to Google Sheets: {e}")

    def _ensure_headers(self):
        try:
            # 1. Users Sheet
            try:
                users_ws = self.sheet.worksheet("Users")
            except gspread.WorksheetNotFound:
                users_ws = self.sheet.add_worksheet(title="Users", rows=1000, cols=11)

            expected_user_headers = [
                "ID пользователя", "Дата регистрации", "Последняя активность", "Всего сообщений", 
                "Сообщений (30 дней)", "Сообщений (7 дней)", "Сообщений (Сегодня)", "Ср. длина (сек)", "Ср. символов",
                "Статус", "Баланс (мин)"
            ]
            
            if not users_ws.row_values(1) or users_ws.row_values(1) != expected_user_headers:
                 users_ws.update(range_name="A1:K1", values=[expected_user_headers])

            # 2. Voice Messages Sheet
            try:
                voice_ws = self.sheet.worksheet("VoiceMessages")
            except gspread.WorksheetNotFound:
                voice_ws = self.sheet.add_worksheet(title="VoiceMessages", rows=1000, cols=8)

            # Updated headers with Status and Reason
            expected_voice_header = ["Дата", "Время", "ID пользователя", "Скорость (сек)", "Длина (сек)", "Длина (симв)", "Статус", "Причина"]
            if not voice_ws.row_values(1) or voice_ws.row_values(1) != expected_voice_header:
                 voice_ws.update(range_name="A1:H1", values=[expected_voice_header])

            # 3. Reviews Sheet
            try:
                reviews_ws = self.sheet.worksheet("Reviews")
            except gspread.WorksheetNotFound:
                reviews_ws = self.sheet.add_worksheet(title="Reviews", rows=1000, cols=5)
            
            expected_reviews_header = ["Дата", "Время", "ID пользователя", "Тип", "Отзыв/Содержание"]
            if not reviews_ws.row_values(1) or reviews_ws.row_values(1) != expected_reviews_header:
                reviews_ws.update(range_name="A1:E1", values=[expected_reviews_header])

        except Exception as e:
            logging.error(f"Error ensuring headers: {e}")

    def update_user_row_sync(self, stats: dict):
        if not self.sheet:
            return
        
        try:
            ws = self.sheet.worksheet("Users")
            try:
                cell = ws.find(str(stats['user_id']), in_column=1)
            except gspread.exceptions.CellNotFound:
                cell = None
            
            balance = stats.get('balance_minutes', 0.0)
            free_left = stats.get('free_left_minutes', 0.0)
            
            status_str = "Active"
            balance_str = f"{balance} мин (+{free_left} free)"

            # Format dates for better readability
            reg_date_str = stats['reg_date'].strftime("%d.%m.%Y | %H:%M") if stats.get('reg_date') else "-"
            last_act_str = stats['last_activity'].strftime("%d.%m.%Y | %H:%M") if stats.get('last_activity') else "-"

            row_data = [
                str(stats['user_id']),
                reg_date_str,
                last_act_str,
                stats['total_msgs'],
                stats['msgs_30d'],
                stats['msgs_7d'],
                stats.get('msgs_today', 0),
                stats['avg_length_sec'],
                stats['avg_chars'],
                status_str,
                balance_str
            ]

            if cell:
                ws.update(range_name=f"A{cell.row}:K{cell.row}", values=[row_data])
            else:
                ws.append_row(row_data)
        except Exception as e:
            logging.error(f"Error updating user row: {e}")

    def add_voice_message_sync(self, data: dict):
        if not self.sheet:
            return
        
        try:
            ws = self.sheet.worksheet("VoiceMessages")
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            ws.append_row([
                now.strftime("%d.%m.%Y"), 
                now.strftime("%H:%M"),     
                str(data['user_id']),
                data.get('process_speed', 0),
                data['length_sec'],
                data.get('length_chars', 0),
                data.get('status', 'success'),
                data.get('error_reason', '')
            ])
        except Exception as e:
            logging.error(f"Error adding voice message log: {e}")

    def add_review_sync(self, data: dict):
        if not self.sheet:
            return
        try:
            ws = self.sheet.worksheet("Reviews")
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            ws.append_row([
                now.strftime("%d.%m.%Y"),
                now.strftime("%H:%M"),
                str(data['user_id']),
                data['type'],    
                data['content'] 
            ])
        except Exception as e:
            logging.error(f"Error adding review: {e}")

    async def update_user_stats(self, stats: dict):
        if self.sheet:
            await asyncio.to_thread(self.update_user_row_sync, stats)

    async def log_voice_message(self, data: dict):
        if self.sheet:
            await asyncio.to_thread(self.add_voice_message_sync, data)

    async def log_review(self, data: dict):
        if self.sheet:
            await asyncio.to_thread(self.add_review_sync, data)

gs_service = GoogleSheetsService()
