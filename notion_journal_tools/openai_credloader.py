class OpenAICredentialsLoader:
    def __init__(self, filepath: str = "openai_apikey.txt"):
        self.filepath = filepath
        self._data = {}
        self.load()

    def load(self):
        """Load key=value pairs from the credentials file."""
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        self._data[key.strip()] = value.strip()
        except FileNotFoundError:
            raise RuntimeError(f"Credentials file not found: {self.filepath}")
        except Exception as e:
            raise RuntimeError(f"Failed to load credentials: {e}")

    def get_credentials(self) -> dict:
        """Return credentials as a dictionary usable by OpenAI."""
        if not self._data:
            raise RuntimeError("Credentials not loaded. Call load() first.")
        return self._data

    def get_api_key(self) -> str:
        """Convenience method to get only the API key."""
        return self._data.get("api_key", "")

if __name__ == "__main__":
    x = OpenAICredentialsLoader()
    print(x.get_api_key())
