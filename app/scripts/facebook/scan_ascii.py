import re
from pathlib import Path
from collections import Counter

output_dir = Path(r'D:\Projects\videostudio\data\facebook_cases\dem-nay-lai-co-chuyen')
md_files = [f for f in output_dir.glob('*.md') if f.name != 'README.md']

# Look for lowercase words without vietnamese accents that might be evasion words
# E.g. words >= 4 letters, consisting solely of a-z, and check frequency
candidates = Counter()
vietnamese_accents = set('àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ')

common_safe_latin = {'video', 'studio', 'facebook', 'page', 'online', 'camera', 'jeep', 'clip', 'game', 'bar', 'live', 'stream', 'poster', 'fan', 'link', 'post', 'status', 'view', 'like', 'share', 'comment', 'chat', 'internet', 'net', 'sim', 'web', 'laptop', 'macbook', 'iphone', 'ipad', 'smartphone', 'karaoke', 'hotel', 'motel', 'resort', 'club', 'pub', 'cafe', 'coffee', 'shipper', 'ship', 'taxi', 'grab', 'uber', 'bus', 'oto', 'xe', 'phim', 'show', 'mc', 'vip', 'dna', 'adn', 'vtv', 'vtv3', 'thpt', 'thcs', 'ptth', 'dai', 'hoc', 'trung', 'hoc', 'tieu', 'tap', 'chi', 'doanh', 'nghiep', 'nhan', 'vien', 'can', 'bo', 'cong', 'an', 'vien', 'kiem', 'sat', 'toa', 'an', 'giam', 'doc', 'pho', 'truong', 'phong', 'ban', 'doi', 'to', 'nhom', 'truong', 'thanh', 'pho', 'tinh', 'huyen', 'xa', 'phuong', 'thon', 'ap', 'ban', 'to', 'dan', 'pho', 'khu', 'pho', 'duong', 'ngo', 'ngach', 'hem', 'so', 'nha', 'can', 'ho', 'toa', 'nha', 'chung', 'cu', 'biet', 'thu', 'nha', 'rieng', 'phong', 'tro', 'nha', 'nghi', 'khach', 'san', 'benh', 'vien', 'trung', 'tam', 'y', 'te', 'tram', 'phong', 'kham', 'nha', 'thuoc', 'hieu', 'tiem', 'cua', 'hang', 'sieu', 'thi', 'cho', 'trung', 'tam', 'thuong', 'mai', 'cong', 'vien', 'quang', 'truong', 'san', 'van', 'dong', 'nha', 'thi', 'dau', 'be', 'boi', 'bai', 'bien', 'song', 'ho', 'suoi', 'thac', 'kenh', 'rach', 'dong', 'ruong', 'vuon', 'rung', 'nui', 'doi', 'deo', 'thung', 'lung', 'hang', 'dong', 'cau', 'cong', 'duong', 'ham', 'nga', 'ba', 'nga', 'tu', 'vong', 'xuyen', 'ben', 'xe', 'ga', 'tau', 'san', 'bay', 'cang', 'bien', 'hai', 'quan', 'cua', 'khau', 'tram', 'thu', 'phi', 'don', 'bien', 'phong', 'tru', 'so', 'co', 'quan', 'nha', 'may', 'xi', 'nghiep', 'phan', 'xuong', 'kho', 'bai', 'cong', 'truong', 'mo', 'nong', 'truong', 'lam', 'truong', 'trai', 'giam', 'trai', 'tam', 'giam', 'nha', 'tam', 'giu'}

for f in md_files:
    txt = f.read_text(encoding='utf-8')
    # find words composed only of ASCII a-z
    words = re.findall(r'\b[a-z]{3,15}\b', txt)
    for w in words:
        if w not in common_safe_latin:
            candidates[w] += 1

# Write top 200 candidates to inspect
with open(str(Path(__file__).resolve().parents[3]/'data/facebook_cases/scratch/scratch_ascii_words.txt'), 'w', encoding='utf-8') as out:
    for w, count in candidates.most_common(300):
        out.write(f"{w}: {count}\n")

print("Done scanning ascii words.")
