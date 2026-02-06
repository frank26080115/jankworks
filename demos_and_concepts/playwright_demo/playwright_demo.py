from playwright.sync_api import sync_playwright
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python playwright_demo.py <url>")
    sys.exit(1)

url = sys.argv[1]

# Your Chrome profile
user_data = r"C:\Users\frank\AppData\Local\Google\Chrome\User Data"

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        #user_data_dir=user_data,
        user_data_dir = str(Path("playwright_chrome_profile").resolve()),
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        headless=False,
        args=["--profile-directory=Default"]
    )
    page = browser.new_page()
    page.goto(url)
    input("Press Enter to close...")
    browser.close()
