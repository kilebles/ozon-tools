from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    company_id: str = "681930"
    cookies_path: Path = Path("cookies.json")
    google_credentials_path: Path = Path("credentials.json")
    spreadsheet_id: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
