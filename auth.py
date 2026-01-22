import json
import os
import time
import requests
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TOKEN_FILE = "tokens.json"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


class TokenManager:
    def __init__(self, token_file=TOKEN_FILE):
        self.token_file = token_file
        self.token_data = self.load_tokens()

    def load_tokens(self):
        if not os.path.exists(self.token_file):
            raise FileNotFoundError(f"Token file '{self.token_file}' does not exist.")

        with open(self.token_file, encoding="utf-8") as f:
            data = json.load(f)

        for field in ("access_token", "refresh_token", "expires_at"):
            if field not in data:
                raise ValueError(f"Missing '{field}' in token file")

        return data

    def save_tokens(self):
        with open(self.token_file, "w", encoding="utf-8") as f:
            json.dump(self.token_data, f, indent=2)

    def is_expired(self):
        return self.token_data["expires_at"] <= time.time()

    def refresh(self):
        logger.info("Refreshing access token...")

        if not CLIENT_ID:
            logger.error("CLIENT_ID is not set!")
        if not CLIENT_SECRET:
            logger.error("CLIENT_SECRET is not set!")
        if not self.token_data["refresh_token"]:
            logger.error("Refresh token is missing!")

        payload = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": self.token_data["refresh_token"],
        }

        r = requests.post(TOKEN_URL, data=payload)
        if not r.ok:
            logger.error(f"Refresh failed: {r.text}")
            r.raise_for_status()

        data = r.json()

        self.token_data["access_token"] = data["access_token"]
        self.token_data["refresh_token"] = data.get(
            "refresh_token", self.token_data["refresh_token"]
        )
        self.token_data["expires_at"] = int(time.time()) + data["expires_in"]

        self.save_tokens()

    def get_valid_token(self):
        if self.is_expired():
            self.refresh()
        return self.token_data["access_token"]
