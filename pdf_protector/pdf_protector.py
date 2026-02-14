import argparse
import os
import sys
from getpass import getpass
from pypdf import PdfReader, PdfWriter


def encrypt_pdf(input_path: str, password: str):
    if not os.path.isfile(input_path):
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    base, ext = os.path.splitext(input_path)
    if ext.lower() != ".pdf":
        print("Error: Input file must be a PDF.")
        sys.exit(1)

    output_path = f"{base}.encrypted.pdf"

    reader = PdfReader(input_path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    # AES-256 encryption
    writer.encrypt(
        user_password=password,
        owner_password=None,
        algorithm="AES-256"
    )

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"Encrypted PDF written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt a PDF with AES-256 password protection."
    )
    parser.add_argument(
        "input_file",
        help="Path to the input PDF file"
    )

    args = parser.parse_args()

    password = getpass("Enter password for PDF encryption: ")
    confirm = getpass("Confirm password: ")

    if password != confirm:
        print("Error: Passwords do not match.")
        sys.exit(1)

    if not password:
        print("Error: Password cannot be empty.")
        sys.exit(1)

    encrypt_pdf(args.input_file, password)


if __name__ == "__main__":
    main()
