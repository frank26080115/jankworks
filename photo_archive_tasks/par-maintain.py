import os
import argparse
import subprocess

def verify_par2(par2_file, multipar_path, recover=False):
    """Verify and optionally repair using a .par2 file."""
    try:
        args = [multipar_path, '/v', par2_file]
        if recover:
            args = [multipar_path, '/r', par2_file]
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print(f"{'Recovering' if recover else 'Verifying'}: {par2_file}")
        print(result.stdout)
        if result.returncode != 0:
            print(f"Error or corruption detected in: {par2_file}")
    except Exception as e:
        print(f"Failed to process {par2_file}: {e}")

def scan_and_process(root_path, multipar_path, recover=False):
    """Scan for .par2 files and process them."""
    for dirpath, dirnames, filenames in os.walk(root_path):
        for file in filenames:
            if file.endswith('.par2') and not file.startswith('vol'):  # Only base .par2 files
                par2_path = os.path.join(dirpath, file)
                verify_par2(par2_path, multipar_path, recover=recover)

def main():
    parser = argparse.ArgumentParser(description="Drive maintenance and recovery using PAR2")
    parser.add_argument('--src', required=True, help='Root path to scan (e.g., D:\\)')
    parser.add_argument('--multipar', required=True, help='Path to MultiPar.exe')
    parser.add_argument('--recover', action='store_true', help='Attempt recovery on corrupted files')
    args = parser.parse_args()

    scan_and_process(args.src, args.multipar, recover=args.recover)

if __name__ == '__main__':
    main()
