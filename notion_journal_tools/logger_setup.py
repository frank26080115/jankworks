import logging
from logging.handlers import RotatingFileHandler
import os

# Optional: ensure log folder exists
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_path = os.path.join(log_dir, "main.log")

# Create a shared logger
logger = logging.getLogger("notion-router")
level = logging.DEBUG
logger.setLevel(level)

# Avoid adding multiple handlers on reload
if not logger.handlers:
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
