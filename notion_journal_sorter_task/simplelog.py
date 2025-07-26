import os
import datetime
import traceback

class SimpleLog:
    def __init__(self, prefix: str, logger, directory: str = "logs"):
        self.logger = logger
        self.directory = directory
        self.prefix = prefix
        self.filename = f"{self.prefix}.txt"
        self.filepath = os.path.join(self.directory, self.filename)
        self.file = None

        try:
            os.makedirs(self.directory, exist_ok=True)
            self._rotate_if_needed()
            self.file = open(self.filepath, 'a', encoding='utf-8')
        except Exception as e:
            self.logger.error(f"SimpleLog init failed: {e}")
            self.logger.debug(traceback.format_exc())

    def _rotate_if_needed(self):
        if os.path.exists(self.filepath):
            size = os.path.getsize(self.filepath)
            if size > 0.5 * 1024 * 1024:  # 0.5 MB
                date_str = datetime.datetime.now().strftime("%Y%m%d")
                new_name = f"{self.prefix}-{date_str}.txt"
                new_path = os.path.join(self.directory, new_name)
                try:
                    os.rename(self.filepath, new_path)
                except Exception as e:
                    self.logger.warning(f"Log rotation failed: {e}")
                    self.logger.debug(traceback.format_exc())

    def log(self, message: str, dt = None):
        try:
            if dt is None:
                dt = datetime.datetime.now()
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S,")
            self.file.write(f"{timestamp} {message}\n")
            self.file.flush()
        except Exception as e:
            self.logger.error(f"Write to log failed: {e}")
            self.logger.debug(traceback.format_exc())
