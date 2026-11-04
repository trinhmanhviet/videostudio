# Prompt vẽ asset meme trong app ChatGPT

Làm trong **app ChatGPT/Codex trên máy bạn (tab Chat)**, không dùng trình duyệt riêng của VideoStudio. Mỗi đợt = 1 tin nhắn dán vào chat. Đã bỏ các ảnh đã có: bg_bedroom, bg_living_room, prop_food.

## Cách làm (mỗi đợt)

1. Mở **chat mới** (mỗi đợt một chat mới cho khỏi lẫn style và đỡ chạm giới hạn).
2. Dán tin nhắn trong khung code của đợt đó, gửi.
3. Nếu ChatGPT chỉ vẽ 1 ảnh rồi dừng, gõ `tiếp` để nó vẽ ảnh kế tiếp. Nếu nó hỏi lại thì gõ `không cần hỏi, cứ vẽ`.
4. Khi đủ ảnh: bấm tải từng ảnh về **theo đúng thứ tự 1, 2, 3...** (ảnh đầu tải trước).
5. Chạy đúng dòng lệnh ghi dưới đợt đó (trong thư mục VideoStudio) để đổi tên và chuyển vào `new\`:
   `python scripts\nhan_ten_anh.py tên1 tên2 ...` (thêm `--xem` để xem trước, chưa chuyển file).
6. Làm xong bao nhiêu đợt cũng được. Lần tạo video meme kế tiếp tự nạp ảnh mới vào danh mục. Muốn nạp ngay: `python scripts\import_meme_library.py`.

Ưu tiên: các đợt đầu tiên là cảnh/đồ dùng phổ biến nhất, nếu hết lượt vẽ thì dừng ở đó cũng đã dùng được.

**Lưu ý với bảng đồ vật (sheet):** số đồ vật phải đúng bằng số ghi trong prompt, vì script cắt dựa vào thứ tự. Nếu ChatGPT vẽ thừa/thiếu hoặc nền không phải màu hồng #FF00FF/trong suốt thì bảo nó vẽ lại.

## Đợt B1: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. a small home kitchen with a gas stove and shelves
2. a small tiled bathroom with a toilet and a sink
3. an open office with desks and computers
4. a school classroom with a green chalkboard and wooden desks
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_kitchen bg_bathroom bg_office bg_classroom`

## Đợt B2: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. a clinic room with a patient bed and a cabinet
2. a cozy coffee shop interior with a counter and small tables
3. a Vietnamese sidewalk eatery with plastic stools and a metal table
4. a convenience store aisle with shelves of products without labels
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_clinic bg_coffee_shop bg_street_eatery bg_store`

## Đợt B3: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. a gym with weights and a treadmill
2. the inside of an elevator
3. a city street with shops and parked motorbikes, daytime
4. a narrow Vietnamese alley
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_gym bg_elevator bg_street bg_alley`

## Đợt B4: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. a local open-air market
2. a park with trees and a bench
3. a school yard
4. a sunny beach
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_market bg_park bg_school_yard bg_beach`

## Đợt B5: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. countryside rice fields
2. green mountains under a blue sky
3. a bus stop by the road
4. a rooftop at sunset
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_countryside bg_mountains bg_bus_stop bg_rooftop`

## Đợt B6: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. an empty theater stage with red curtains and a spotlight
2. outer space with stars and planets
3. a city street at night with street lights
4. a bedroom at night, lights off, moonlight from the window
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_stage bg_space bg_street_night bg_bedroom_night`

## Đợt B7: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. a hospital corridor with benches and doors
2. a supermarket checkout counter with a conveyor belt
3. a bank service counter with glass windows
4. a cinema hall with red seats facing a blank screen
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_hospital_corridor bg_supermarket_checkout bg_bank_counter bg_cinema`

## Đợt B8: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. a quiet library with tall bookshelves
2. an outdoor swimming pool with deck chairs
3. a decorated Vietnamese wedding hall with flowers and round tables
4. a Vietnamese living room decorated for Lunar New Year with a peach blossom branch, a kumquat tree and red lanterns
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_library bg_swimming_pool bg_wedding_hall bg_tet_house`

## Đợt B9: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. inside a city bus with seats and hand straps
2. inside a car seen from the back seat, dashboard and windshield
3. a restaurant dining room with tables and hanging lamps
4. a karaoke room with a sofa, a big screen and disco lights
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_bus_interior bg_car_interior bg_restaurant bg_karaoke_room`

## Đợt B10: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. an apartment building corridor with doors
2. an office meeting room with a long table and a blank screen
3. a construction site with scaffolding and sand piles
4. a Vietnamese countryside farmyard with a haystack and a well
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_apartment_corridor bg_meeting_room bg_construction_site bg_farm`

## Đợt B11: 4 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 4 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. a green forest path
2. a city street in heavy rain with puddles
3. an airport departure hall with seats and big windows
4. a train station platform
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_forest bg_rainy_street bg_airport bg_train_station`

## Đợt B12: 2 nền

```
Tôi đang làm bộ asset dùng lại cho video meme hoạt hình ngắn kiểu gấu trúc 'biaoqing' của Trung Quốc. Hãy vẽ 2 ảnh RIÊNG BIỆT, mỗi ảnh một cảnh, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận.
Mỗi ảnh: dọc 9:16, cảnh NỀN TRỐNG, không có người, động vật hay nhân vật nào. Tường có thể có vài vệt ố mờ. Sàn nhà/mặt đất chiếm 1/3 phía dưới, để trống khu vực giữa và dưới cho nhân vật đặt vào sau. Phong cách: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Dùng CÙNG MỘT phong cách cho tất cả các ảnh.
Các cảnh:
1. a very messy bedroom with clothes and snacks everywhere
2. an empty office at night, only one desk lamp on
```

Đặt tên: `python scripts\nhan_ten_anh.py bg_messy_room bg_office_night`

## Đợt S1: prop_furniture, prop_home

```
Tôi cần 2 ảnh RIÊNG BIỆT (bảng sticker đồ vật) cho bộ asset video meme hoạt hình, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận. Dùng cùng một phong cách cho cả hai.
Ảnh 1: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: plastic stool, office chair, small table, sofa, bed, wardrobe, door, window.

Ảnh 2: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: standing fan, TV, floor lamp, fridge, wall clock, pillow, blanket, umbrella.
```

Đặt tên: `python scripts\nhan_ten_anh.py prop_furniture prop_home`

## Đợt S2: prop_kitchen_tech, prop_study_office

```
Tôi cần 2 ảnh RIÊNG BIỆT (bảng sticker đồ vật) cho bộ asset video meme hoạt hình, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận. Dùng cùng một phong cách cho cả hai.
Ảnh 1: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: cooking pot, frying pan, smartphone, laptop, headphones, TV remote, phone charger, game controller.

Ảnh 2: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: book, notebook, pen, school backpack, stack of papers, briefcase, desktop computer, whiteboard.
```

Đặt tên: `python scripts\nhan_ten_anh.py prop_kitchen_tech prop_study_office`

## Đợt S3: prop_vehicles, prop_daily

```
Tôi cần 2 ảnh RIÊNG BIỆT (bảng sticker đồ vật) cho bộ asset video meme hoạt hình, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận. Dùng cùng một phong cách cho cả hai.
Ảnh 1: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 3 rows. Đúng 6 đồ vật, không thêm không bớt. Objects: scooter motorbike, bicycle, small car, city bus, taxi, delivery tricycle.

Ảnh 2: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: paper money bills, wallet, handbag, toilet paper roll, toothbrush, medicine box, gift box, cardboard box.
```

Đặt tên: `python scripts\nhan_ten_anh.py prop_vehicles prop_daily`

## Đợt S4: fx_stickers, prop_tet

```
Tôi cần 2 ảnh RIÊNG BIỆT (bảng sticker đồ vật) cho bộ asset video meme hoạt hình, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận. Dùng cùng một phong cách cho cả hai.
Ảnh 1: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 3 columns x 3 rows. Đúng 9 đồ vật, không thêm không bớt. Objects: sweat drop, question mark, exclamation mark, red heart, broken heart, ring of stars, smoke puff, lightning bolt, water splash.

Ảnh 2: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: square banh chung rice cake wrapped in green leaves, blank red lucky money envelope, peach blossom branch in a vase, small kumquat tree in a pot, red paper lantern, tray of five fruits, round Tet candy box, yellow apricot blossom branch in a vase.
```

Đặt tên: `python scripts\nhan_ten_anh.py fx_stickers prop_tet`

## Đợt S5: prop_sports, prop_clothes

```
Tôi cần 2 ảnh RIÊNG BIỆT (bảng sticker đồ vật) cho bộ asset video meme hoạt hình, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận. Dùng cùng một phong cách cho cả hai.
Ảnh 1: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: soccer ball, dumbbell, badminton racket with shuttlecock, pair of running shoes, jump rope, rolled yoga mat, sports whistle, basketball.

Ảnh 2: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: plain t-shirt, jeans, sneakers, baseball cap, Vietnamese conical hat, sunglasses, necktie, raincoat.
```

Đặt tên: `python scripts\nhan_ten_anh.py prop_sports prop_clothes`

## Đợt S6: prop_tools, prop_medical

```
Tôi cần 2 ảnh RIÊNG BIỆT (bảng sticker đồ vật) cho bộ asset video meme hoạt hình, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận. Dùng cùng một phong cách cho cả hai.
Ảnh 1: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: broom, bucket, mop, toolbox, ladder, watering can, screwdriver, flashlight.

Ảnh 2: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: pill bottle, two pills, thermometer, adhesive bandage, face mask, ice pack, pair of crutches, wheelchair.
```

Đặt tên: `python scripts\nhan_ten_anh.py prop_tools prop_medical`

## Đợt S7: prop_animals, prop_shopping

```
Tôi cần 2 ảnh RIÊNG BIỆT (bảng sticker đồ vật) cho bộ asset video meme hoạt hình, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận. Dùng cùng một phong cách cho cả hai.
Ảnh 1: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: cute dog, cute cat, chicken, duck, pig, goldfish in a round bowl, parrot, water buffalo.

Ảnh 2: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: pile of gold coins, gold bar, piggy bank, blank bank card, ATM machine, shopping bag, shopping cart, blank price tag.
```

Đặt tên: `python scripts\nhan_ten_anh.py prop_animals prop_shopping`

## Đợt S8: prop_party, prop_school

```
Tôi cần 2 ảnh RIÊNG BIỆT (bảng sticker đồ vật) cho bộ asset video meme hoạt hình, vẽ lần lượt trong cùng câu trả lời này. Không hỏi lại, không xin xác nhận. Dùng cùng một phong cách cho cả hai.
Ảnh 1: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: bunch of balloons, party hat, party popper with confetti, microphone, acoustic guitar, loudspeaker box, wine glass, crate of beer bottles.

Ảnh 2: A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 2 columns x 4 rows. Đúng 8 đồ vật, không thêm không bớt. Objects: calculator, exam paper with red cross marks, ruler, eraser, globe, school drum, pieces of chalk, abacus.
```

Đặt tên: `python scripts\nhan_ten_anh.py prop_party prop_school`

## Đợt S9: fx_more

```
Tôi cần 1 ảnh (bảng sticker đồ vật) cho bộ asset video meme hoạt hình. Không hỏi lại.
A sticker sheet of separate objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos. Front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch or overlap, no ground shadows, neat grid of 3 columns x 3 rows. Đúng 9 đồ vật, không thêm không bớt. Objects: music notes, fire flames, glowing idea light bulb, small rain cloud, snowflake, cartoon skull, puddle of tears, pair of heart shapes, ring of little birds circling.
```

Đặt tên: `python scripts\nhan_ten_anh.py fx_more`

---
Tổng: 46 nền + 17 bảng đồ vật.
