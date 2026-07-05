from pathlib import Path

def main():
    content = Path("converter.sh").read_text(encoding="utf-8")
    
    start_marker = "# begin conversion"
    end_marker = "done < scratch_files/all.csv\nwait"
    
    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    
    if start_idx == -1 or end_idx == -1:
        print("ERROR: Markers not found!")
        print("start_idx:", start_idx)
        print("end_idx:", end_idx)
        return
        
    replacement = '# begin conversion\npython convert_models.py "attachable_material=${attachable_material}" "block_material=${block_material}"\n'
    new_content = content[:start_idx] + replacement + content[end_idx + len(end_marker):]
    Path("converter.sh").write_text(new_content, encoding="utf-8")
    print("Successfully patched converter.sh!")

if __name__ == "__main__":
    main()
