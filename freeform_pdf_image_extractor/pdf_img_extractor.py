import argparse
import os
import fitz  # PyMuPDF

def extract_images(pdf_path, output_dir):
    doc = fitz.open(pdf_path)
    image_count = 0

    for page_index in range(len(doc)):
        page = doc[page_index]
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)

            image_bytes = base_image["image"]
            image_ext = base_image["ext"]  # e.g. 'jpeg', 'png'

            # Normalize extension naming
            if image_ext.lower() in ["jpeg", "jpg"]:
                ext = "jpg"
            elif image_ext.lower() == "png":
                ext = "png"
            else:
                ext = image_ext  # fallback

            image_count += 1
            filename = f"{image_count:04d}.{ext}"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "wb") as f:
                f.write(image_bytes)

    print(f"Extracted {image_count} images to '{output_dir}'")


def main():
    parser = argparse.ArgumentParser(description="Extract images from a PDF")
    parser.add_argument("pdf_path", help="Path to the input PDF file")
    parser.add_argument(
        "-o", "--output",
        help="Output directory (optional)"
    )

    args = parser.parse_args()

    pdf_path = os.path.abspath(args.pdf_path)

    if not os.path.isfile(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        return

    # Determine output directory
    if args.output:
        output_dir = os.path.abspath(args.output)
    else:
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        output_dir = os.path.join(os.path.dirname(pdf_path), base_name)

    os.makedirs(output_dir, exist_ok=True)

    extract_images(pdf_path, output_dir)


if __name__ == "__main__":
    main()
