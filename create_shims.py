import shutil
import sys
from pathlib import Path

def main():
    magick_path = shutil.which("magick")
    if not magick_path:
        import glob
        candidates = glob.glob(r"C:\Program Files\ImageMagick*\magick.exe")
        if candidates:
            magick_path = candidates[0]
            
    if not magick_path:
        print("ERROR: magick.exe not found in PATH or C:\\Program Files\\ImageMagick*!")
        sys.exit(1)
        
    print(f"Found magick.exe at: {magick_path}")
    shims_dir = Path("imagemagick_shims")
    shims_dir.mkdir(exist_ok=True)
    
    # Overwrite batch files with native binary copies
    for name in ["convert.exe", "identify.exe", "mogrify.exe", "magick.exe"]:
        dest = shims_dir / name
        try:
            shutil.copy2(magick_path, dest)
            print(f"Created shim: {dest}")
        except Exception as e:
            print(f"Failed to create shim {dest}: {e}")
            sys.exit(1)

    # Clean up old batch files if they exist
    for name in ["convert.bat", "identify.bat", "mogrify.bat"]:
        p = shims_dir / name
        if p.exists():
            p.unlink()

if __name__ == "__main__":
    main()
