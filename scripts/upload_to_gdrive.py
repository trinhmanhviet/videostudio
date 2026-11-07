import sys, os, subprocess, json, unicodedata, re, shutil
from pathlib import Path

FOLDER_CASE = '1XhXjWOS-5KJ0G4RiBBX_-N--w9todh56'
FOLDER_COMEDY = '122P5aD6itxRhA8KAha3v4MtI_4i99T5w'

def to_slug(name):
    s = unicodedata.normalize('NFD', name)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace('đ', 'd').replace('Đ', 'd')
    s = re.sub(r'[^a-zA-Z0-9\s_-]', '', s).strip().lower()
    return re.sub(r'[\s_]+', '-', s)

gdrive_bin = shutil.which('gdrive') or 'gdrive.cmd'

def list_drive_folder(folder_id):
    try:
        cmd = [gdrive_bin, 'readonly', 'ls', folder_id, '--json']
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE, shell=True)
        files = []
        for line in out.strip().splitlines():
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                files.append(json.loads(line))
        return files
    except Exception as e:
        # fallback to plain ls
        try:
            cmd = [gdrive_bin, 'readonly', 'ls', folder_id]
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE, shell=True)
            names = []
            for line in out.strip().splitlines()[2:]:
                parts = line.split()
                if len(parts) >= 2:
                    names.append(parts[1])
            return [{'name': n} for n in names]
        except Exception:
            return []

def get_next_filename(folder_id, base_slug, ext='.mp4'):
    existing = list_drive_folder(folder_id)
    existing_names = {f.get('name', '') for f in existing}
    
    candidate = f"{base_slug}{ext}"
    if candidate not in existing_names:
        return candidate
    
    idx = 1
    while True:
        candidate = f"{base_slug}_{idx}{ext}"
        if candidate not in existing_names:
            return candidate
        idx += 1

def upload_video(video_path, project_name=None, is_comedy=False):
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    folder_id = FOLDER_COMEDY if is_comedy else FOLDER_CASE
    base_slug = to_slug(project_name or video_path.stem)
    target_name = get_next_filename(folder_id, base_slug, ext=video_path.suffix or '.mp4')
    
    # Create temporary copy with target name in same directory
    temp_path = video_path.parent / target_name
    import shutil
    shutil.copy2(video_path, temp_path)
    
    try:
        print(f"Uploading {target_name} to folder {folder_id}...")
        cmd = [
            gdrive_bin, 'mutate', 'upload',
            str(temp_path),
            '--parent', folder_id,
            '--mime-type', 'video/mp4'
        ]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, shell=True)
        print(out.strip())
        
        # Extract File ID
        m = re.search(r'\(ID:\s*([a-zA-Z0-9_-]+)\)', out)
        if m:
            file_id = m.group(1)
            url_cmd = [gdrive_bin, 'readonly', 'url', file_id]
            url = subprocess.check_output(url_cmd, text=True, shell=True).strip()
            print(f"File URL: {url}")
            return {'file_id': file_id, 'name': target_name, 'url': url, 'folder_id': folder_id}
        return {'name': target_name, 'folder_id': folder_id}
    finally:
        if temp_path != video_path and temp_path.exists():
            temp_path.unlink()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python upload_to_gdrive.py <video_path> [project_name] [--comedy]")
        sys.exit(1)
    vpath = sys.argv[1]
    pname = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else None
    comedy = '--comedy' in sys.argv or (pname and 'hài' in pname.lower())
    upload_video(vpath, pname, comedy)
