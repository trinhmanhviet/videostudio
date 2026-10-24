import json, wave, shutil, hashlib, subprocess, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

job_dir = Path(r'E:\Videos\1-000-nam-tien-hoa-cua-ao-giap-chau-au-cuoc-chay-dua-giua-th-20261025-032619')
src_dir = job_dir / 'narration-attempt-02'
dst_dir = job_dir / 'narration-attempt-03'

with open(src_dir / 'script.json', 'r', encoding='utf-8') as f:
    script = json.load(f)

scenes = script['scenes']
wav_files = sorted(src_dir.glob('speech-*.wav'))
durs = [wave.open(str(w), 'rb').getnframes() / wave.open(str(w), 'rb').getframerate() for w in wav_files]

drop_set = set(range(70, 72)) | set(range(77, 84)) | set(range(122, 126)) | set(range(142, 158)) | set(range(199, 208)) | set(range(211, 218))
kept_indices = [i for i in range(len(scenes)) if i not in drop_set]

dst_dir.mkdir(exist_ok=True)
retained_scenes = [scenes[i] for i in kept_indices]

print(f'Creating narration-attempt-03: {len(retained_scenes)} scenes')

manifest = []
concat_lines = []
for new_idx, old_idx in enumerate(kept_indices):
    old_wav = src_dir / f'speech-{old_idx:04}.wav'
    new_wav = dst_dir / f'speech-{new_idx:04}.wav'
    new_json = dst_dir / f'speech-{new_idx:04}.json'
    
    shutil.copy2(old_wav, new_wav)
    
    with open(new_wav, 'rb') as wf:
        sha = hashlib.sha256(wf.read()).hexdigest()
        
    scene = scenes[old_idx]
    old_receipt = src_dir / f'speech-{old_idx:04}.json'
    old_saved = json.loads(old_receipt.read_text()) if old_receipt.is_file() else {}
    identity = old_saved.get('identity', '')
    
    new_json.write_text(json.dumps({'identity': identity, 'sha256': sha}, ensure_ascii=False, indent=2), encoding='utf8')
    
    manifest.append({
        'new_index': new_idx,
        'old_index': old_idx,
        'duration': durs[old_idx],
        'narration': scene['narration'],
        'sha256': sha
    })
    concat_lines.append("file '" + new_wav.resolve().as_posix() + "'")

(dst_dir / 'speech-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
new_script = {
    'narration': ' '.join(s['narration'] for s in retained_scenes),
    'source_paths': script.get('source_paths', []),
    'scenes': retained_scenes,
    'chapters': script.get('chapters', [])
}
(dst_dir / 'script.json').write_text(json.dumps(new_script, ensure_ascii=False, indent=2), encoding='utf8')

listing = dst_dir / 'speech-concat.txt'
listing.write_text('\n'.join(concat_lines), encoding='utf8')

out_speech = dst_dir / 'speech.wav'
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-c:a', 'pcm_s16le', str(out_speech)], check=True)

# Probe final speech.wav
probe_res = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(out_speech)]))
actual_dur = float(probe_res['format']['duration'])
print(f'PROBED DURATION: {actual_dur:.4f}s')
print(f'TARGET: 600.0s | REMAINING HOLD: {600.0 - actual_dur:.4f}s')

# Run audio_report on out_speech
from videostudio.media import audio_report
report = audio_report(out_speech, lambda: None)
print(f"AUDIO REPORT: RMS={report['rms']:.6f}, PEAK={report['peak']:.6f}, CLIPPED={report['clipped_fraction']:.6f}")
