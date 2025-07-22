class AuthTokenFileReader:
    def __init__(self, file_path: str = "authtoken.txt"):
        try:
            with open(file_path, "r") as f:
                self._token = f.read().strip()
        except FileNotFoundError:
            self._token = ""

    def get_token(self) -> str:
        return self._token
