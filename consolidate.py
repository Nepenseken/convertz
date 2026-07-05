import os
import shutil
from pathlib import Path

def consolidate_files(dir_path):
    d = Path(dir_path)
    if not d.exists():
        return
        
    print(f"Consolidating files in {dir_path}...")
    
    # Get all files in subdirectories
    files_to_move = []
    for root, dirs, files in os.walk(d):
        rel_root = Path(root).relative_to(d)
        if rel_root == Path("."):
            continue
        for f in files:
            files_to_move.append(Path(root) / f)
            
    # Try to move them to the parent directory d
    pending = []
    for f in files_to_move:
        dest = d / f.name
        if not dest.exists():
            try:
                shutil.move(str(f), str(dest))
            except Exception:
                pending.append(f)
        else:
            pending.append(f)
            
    # Resolve collisions
    nr = 1
    while pending:
        next_pending = []
        for f in pending:
            dest = d / f"{nr}{f.name}"
            if not dest.exists():
                try:
                    shutil.move(str(f), str(dest))
                except Exception:
                    next_pending.append(f)
            else:
                next_pending.append(f)
        pending = next_pending
        nr += 1

    # Remove subdirectories
    for root, dirs, files in os.walk(d, topdown=False):
        if Path(root) == d:
            continue
        try:
            os.rmdir(root)
        except Exception:
            pass
            
    print(f"Successfully consolidated {dir_path}!")

def main():
    consolidate_files("./target/rp/animations")
    consolidate_files("./target/rp/models/blocks")
    consolidate_files("./target/rp/attachables")

if __name__ == "__main__":
    main()
