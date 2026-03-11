from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClient:
    def __init__(self, credentials_path: Path, spreadsheet_id: str) -> None:
        creds = Credentials.from_service_account_file(str(credentials_path), scopes=_SCOPES)
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(spreadsheet_id)

    def get_worksheet(self, title: str) -> gspread.Worksheet:
        return self._spreadsheet.worksheet(title)

    def worksheets(self) -> list[gspread.Worksheet]:
        return self._spreadsheet.worksheets()
