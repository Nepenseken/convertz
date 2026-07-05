import sys
import os
import zipfile

def zip_dir(dir_path, zip_path, include_pattern=None, exclude_pattern=None):
    print(f"[ZIP] Zipping {dir_path} -> {zip_path}")
    dir_path = os.path.abspath(dir_path)
    zip_path = os.path.abspath(zip_path)
    
    # Ensure destination directory exists
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(dir_path):
            # Ignore directories starting with '.'
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                # Ignore files starting with '.'
                if file.startswith('.'):
                    continue
                
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, dir_path)
                
                # Check if we should only include files matching include_pattern
                if include_pattern:
                    if not arcname.endswith(include_pattern):
                        continue
                # Check if we should exclude files matching exclude_pattern
                if exclude_pattern:
                    if arcname.endswith(exclude_pattern):
                        continue
                
                zipf.write(filepath, arcname)
    print(f"[ZIP] Done.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python zip_pack.py <source_dir> <output_zip> [include_pattern] [exclude_pattern]")
        sys.exit(1)
        
    src = sys.argv[1]
    out = sys.argv[2]
    inc = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "None" else None
    exc = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != "None" else None
    
    zip_dir(src, out, include_pattern=inc, exclude_pattern=exc)
