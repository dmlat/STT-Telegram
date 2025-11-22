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
            
            print(f"\n--- GOOGLE SHEETS CONNECTION ---")
            print(f"Bot Email: {creds.service_account_email}")
            print(f"Please share your Google Sheet '{SHEET_NAME}' with this email as 'Editor'.")
            print(f"--------------------------------\n")

            try:
                self.sheet = self.client.open(SHEET_NAME)
                print(f"Successfully connected to sheet: {SHEET_NAME}")
            except gspread.SpreadsheetNotFound:
                print(f"ERROR: Could not find Google Sheet named '{SHEET_NAME}'.")
                print(f"1. Create a Google Sheet named exactly '{SHEET_NAME}'")
                print(f"2. Share it with: {creds.service_account_email}")
                print("3. Restart the bot.")
                return
            
            self._ensure_headers()
            print("Headers checked/created successfully.")
            
        except Exception as e:
            logging.error(f"Failed to connect to Google Sheets: {e}")
            print(f"CRITICAL ERROR: {e}")

    def _ensure_headers(self):
        try:
            # 1. Users Sheet
            try:
                users_ws = self.sheet.worksheet("Users")
            except gspread.WorksheetNotFound:
                users_ws = self.sheet.add_worksheet(title="Users", rows=1000, cols=10)

            if not users_ws.row_values(1):
                users_ws.append_row([
                    "ID пользователя", "Дата регистрации", "Последняя активность", "Всего сообщений", 
                    "Сообщений (30 дней)", "Сообщений (7 дней)", "Сообщений (Сегодня)", "Ср. длина (сек)", "Ср. символов",
                    "Статус", "Остаток лимита (мин)"
                ])
            else:
                # Check if headers are correct (Russian and full list)
                current_headers = users_ws.row_values(1)
                expected_headers = [
                    "ID пользователя", "Дата регистрации", "Последняя активность", "Всего сообщений", 
                    "Сообщений (30 дней)", "Сообщений (7 дней)", "Сообщений (Сегодня)", "Ср. длина (сек)", "Ср. символов",
                    "Статус", "Остаток лимита (мин)"
                ]
                # If headers are different or incomplete, update them
                if current_headers != expected_headers:
                    # Ensure we don't overwrite data in other rows, just update row 1
                    users_ws.update(range_name="A1:K1", values=[expected_headers])
                    print("Headers updated to Russian format.")

            # 2. Voice Messages Sheet
            try:
                voice_ws = self.sheet.worksheet("VoiceMessages")
            except gspread.WorksheetNotFound:
                voice_ws = self.sheet.add_worksheet(title="VoiceMessages", rows=1000, cols=10)

            # Force update headers to new format
            header = voice_ws.row_values(1)
            expected_header = ["Дата", "Время", "ID пользователя", "Скорость обработки (сек)", "Длина (сек)", "Длина (символов)"]
            if not header or header != expected_header:
                 # Update headers if they don't match
                 voice_ws.update(range_name="A1:F1", values=[expected_header])
                 print("VoiceMessages headers updated.")

            # 3. Reviews Sheet (New)
            try:
                reviews_ws = self.sheet.worksheet("Reviews")
            except gspread.WorksheetNotFound:
                reviews_ws = self.sheet.add_worksheet(title="Reviews", rows=1000, cols=10)
            
            reviews_header = reviews_ws.row_values(1)
            expected_reviews_header = ["Дата", "Время", "ID пользователя", "Тип", "Отзыв/Содержание"]
            
            if not reviews_header or reviews_header != expected_reviews_header:
                reviews_ws.update(range_name="A1:E1", values=[expected_reviews_header])
                print("Reviews headers updated.")

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
            
            usage_min = stats.get('daily_usage', 0)
            is_premium = stats.get('is_premium', False)
            premium_until = stats.get('premium_until')
            
            status_str = "Free"
            remaining_str = "0:00"
            
            if is_premium and premium_until:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                delta = premium_until - now
                days_left = delta.days
                if days_left < 0:
                    # Should have been handled by DB check, but just in case
                    status_str = "Free (Expired)"
                else:
                    # e.g. "Premium (7 дн.)"
                    status_str = f"Premium ({days_left} дн.)"
                    remaining_str = "Безлимит"
            else:
                 # Calculate remaining time in m:ss
                 # usage_min is float minutes. limit is 5 mins = 300 sec
                 # usage_min * 60 = used seconds
                 used_sec = usage_min * 60
                 limit_sec = 300
                 left_sec = max(0, int(limit_sec - used_sec))
                 
                 m = left_sec // 60
                 s = left_sec % 60
                 remaining_str = f"{m}:{s:02}"

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
                remaining_str
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
                now.strftime("%d.%m.%Y"), # Date dd.mm.yyyy
                now.strftime("%H:%M"),     # Time hh:mm
                str(data['user_id']),
                data['process_speed'],
                data['length_sec'],
                data['length_chars']
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
                data['type'],    # Positive, Negative (Reason), Suggestion
                data['content']  # The text or '-'
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
