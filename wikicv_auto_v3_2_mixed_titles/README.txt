WIKICV CRAWLER V3.2 - TEN MUC TRUYEN HON HOP (CODE ONLY)

NHUNG GI DA SUA SO VOI V3.1.2
- Khong mac dinh ten phai bat dau bang 'Chuong + so'. Nhan 'Trang', 'Phan',
  'De 020-021 chuong', '13. Chuong 13 ...', va ten muc khong co so.
- Ten tieu de duoc giu nguyen theo nhan tren trang doc (hoac muc luc khi dung --use-index).
- Thu tu va ten file TXT duoc gan theo VI TRI DUYET (00001, 00002, ...),
  khong theo so trong tieu de. 'De 020-021 chuong' la MOT muc neu website co MOT URL.
- Ket thuc khi den CHINH URL duoc danh dau Moi nhat; khong dung phep so sanh so.
- Giu ca loi tua/chuong nam ben trong mot 'Trang' (khong cat nham o 'Chuong 1').
- Xu ly URL co %7E thay cho dau ~.
- Neu thieu tieu de, link Moi nhat hoac link tiep theo: bao loi, khong tu doan.
- Chuong le va truyen_gop.txt khong co dong 'Nguon: ...'. URL nguon nam trong truyen.json.
- Mac dinh van duyet tuan tu, KHONG su dung API /book/index.
- Giu random delay 2.198347 den 3.982344 giay GIUA CAC MUC nhu v3.1.
- Kiem tra robots.txt (dung neu bi cam hoac khong xac minh duoc), dung tren 403,
  429, va dau hieu Cloudflare 1006; khong thay doi IP hay vuot chan.

CAI DAT VA CHAY
1. Neu can, cai Python 3.10+ va danh dau 'Add Python to PATH'.
2. Giai nen ZIP, nhap dup chay_windows.bat, dan URL gioi thieu, Enter.
3. Thu voi 2 muc (neu website cho phep):
   py -3 crawl_wikicv.py --max-chapters 2
4. Ban cu da co 'du_lieu_truyen': CHI CAN CHEP THU MUC NAY VAO THU MUC V3.2.
   Chuong da luu co the duoc tiep tuc, khong can tai lai tu dau.
5. Chi tao lai file gop tu du lieu da tai, khong goi mang:
   tao_lai_truyen_gop.bat
   hoac python crawl_wikicv.py --rebuild-only
6. Chay kiem thu offline:
   py -3 -m unittest discover -s tests -v

DU LIEU
- du_lieu_truyen/<ten-truyen>/chapters/chuong_00001.txt ...
- du_lieu_truyen/<ten-truyen>/truyen_gop.txt
- du_lieu_truyen/<ten-truyen>/truyen.json (danh sach URL nguon)
- du_lieu_truyen/<ten-truyen>/chapters.json (manifest noi bo)

LUU Y QUAN TRONG
- Mot 'Trang' co the chua nhieu chuong nho: so muc tai ve KHONG phai so
  chuong thuc te. Cong cu khong tu chia noi dung mot URL thanh nhieu chuong.
- Neu tren website co chuong bi chen sai thu tu, cong cu theo dung thu tu
  duong dan 'Tiep theo' hoac muc luc; khong tu suy doan va sua thu tu.
- V3.2 da vuot qua bo kiem thu offline, CHUA duoc chay thuc te tren website
  tu moi truong nay. Khong bao dam khong bi khoa IP.
- Chi su dung voi noi dung ban co quyen sao chep/lai, va khong thuc hien
  neu website da cam truy cap tu dong. Neu bi chan, dung, lien he quan tri.
