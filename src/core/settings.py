from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    company_id: str = "681930"
    proxy_path: Path = Path("proxy.txt")
    google_credentials_path: Path = Path("credentials.json")
    sheets_dir: Path = Path("sheets")
    bot_token: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
