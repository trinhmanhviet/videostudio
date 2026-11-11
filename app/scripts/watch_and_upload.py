import sys, os, time, json, urllib.request, glob
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add scripts directory to path to import upload_to_gdrive
sys.path.insert(0, str(Path(__file__).resolve().parent))
from upload_to_gdrive import upload_video, FOLDER_COMEDY, FOLDER_CASE

def watch_and_upload(job_id, project_name=None, is_comedy=True, timeout_minutes=30):
    start = time.time()
    last_stage = None
    last_event = None
    print(f"Watching job {job_id} (Project: {project_name}, Comedy={is_comedy})...")
    
    while time.time() - start < timeout_minutes * 60:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:8877/api/jobs/{job_id}")
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.load(res)
        except Exception as e:
            print(f"API poll error: {e}")
            time.sleep(5)
            continue
            
        state = data.get('state')
        stage = data.get('stage')
        event = data.get('latest_event', {}).get('detail')
        
        if stage != last_stage or event != last_event:
            print(f"[{time.strftime('%H:%M:%S')}] State: {state} | Stage: {stage} | Event: {event}")
            last_stage = stage
            last_event = event
            
        if state == 'completed':
            print("\n*** JOB COMPLETED SUCCESSFULLY! ***")
            output_dir = Path(data.get('output'))
            project_dir = output_dir.parent
            
            # Find the final MP4 file
            render_video = data.get('checkpoints', {}).get('render', {}).get('video')
            mp4_candidates = []
            if render_video:
                mp4_candidates.append(Path(render_video))
            mp4_candidates.extend([
                output_dir.parent / f"video-{job_id}.mp4",
                output_dir.parent.parent / f"video-{job_id}.mp4",
                output_dir / "video.mp4"
            ])
            mp4_candidates.extend(list(output_dir.parent.glob("*.mp4")))
            mp4_candidates.extend(list(output_dir.parent.parent.glob("*.mp4")))
            
            final_mp4 = None
            for p in mp4_candidates:
                if p.is_file() and p.stat().st_size > 1024 * 1024:
                    final_mp4 = p
                    break
                    
            if not final_mp4:
                print(f"Error: Could not locate rendered MP4 in {project_dir}")
                return 1
                
            print(f"Found rendered video: {final_mp4} ({round(final_mp4.stat().st_size / (1024*1024), 2)} MB)")
            print(f"Initiating Google Drive upload to {'Comedy' if is_comedy else 'Case'} folder...")
            
            upload_result = upload_video(final_mp4, project_name=project_name or data.get('project'), is_comedy=is_comedy)
            print("\n==========================================")
            print("UPLOAD COMPLETED TO GOOGLE DRIVE!")
            print(f"File Name: {upload_result.get('name')}")
            print(f"Drive URL: {upload_result.get('url')}")
            print("==========================================\n")
            return 0
            
        if state == 'failed':
            print(f"\n*** JOB FAILED: {data.get('error')} ***")
            return 1
            
        time.sleep(5)
        
    print(f"Timeout after {timeout_minutes} minutes.")
    return 1

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python watch_and_upload.py <job_id> [project_name] [--comedy]")
        sys.exit(1)
    jid = sys.argv[1]
    pname = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else None
    comedy = '--comedy' in sys.argv or (pname and any(w in pname.lower() for w in ('hài', 'meme', 'chân nhân')))
    sys.exit(watch_and_upload(jid, pname, comedy))
