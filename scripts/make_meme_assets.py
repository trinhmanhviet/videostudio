"""Ask ChatGPT (through the VideoStudio dedicated-Chrome daemon) to draw the generic meme asset library.

Run from VideoStudio while the system is up (tray -> Mo he thong):
    python scripts/make_meme_assets.py --test      # 2 images to check the style first
    python scripts/make_meme_assets.py             # everything not drawn yet
    python scripts/make_meme_assets.py --only bg_park,prop_food

Each asset has a fixed task id, so a rerun skips finished files and the daemon
reconciles an interrupted request instead of sending it again.
"""
import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets' / 'Meme_Animation_Asset_Pack' / 'new'
DAEMON = 'http://127.0.0.1:8879'
NAMESPACE = uuid.UUID('6f1c2a7e-4b1d-4c55-9a43-6d0b3f1e8a10')

# Canonical style (docs/meme-video.md, "Phong cách chuẩn"). Every asset must match it.
STYLE = ("Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, "
         "single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy "
         "muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. "
         "Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no "
         "reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, "
         "letters, numbers, signs with words or brand logos.")


def background(scene):
    return ("An EMPTY background scene for a meme cartoon, vertical 9:16. " + STYLE +
            " A few faint stains on the walls are fine. No people, no animals, no characters. The floor or ground "
            "fills the bottom third; keep the middle and lower area open so characters can be placed there later. "
            "Scene: " + scene + ".")


def sheet(items, grid='2 columns x 4 rows'):
    return ("A sticker sheet of separate objects on a fully transparent background (if real transparency "
            "is impossible, use a solid flat #FF00FF magenta background instead, never a checkerboard). " + STYLE +
            " Front or 3/4 view, each object isolated with plenty of empty space around it, objects never "
            "touch or overlap, no ground shadows, neat grid of " + grid + ". Objects: " + items + ".")


ASSETS = [
    ('bg_living_room', background('a Vietnamese living room with tiled floor, wooden sofa and TV cabinet')),
    ('bg_bedroom', background('a simple bedroom with a bed, a window and a standing fan')),
    ('bg_kitchen', background('a small home kitchen with a gas stove and shelves')),
    ('bg_bathroom', background('a small tiled bathroom with a toilet and a sink')),
    ('bg_office', background('an open office with desks and computers')),
    ('bg_classroom', background('a school classroom with a green chalkboard and wooden desks')),
    ('bg_clinic', background('a clinic room with a patient bed and a cabinet')),
    ('bg_coffee_shop', background('a cozy coffee shop interior with a counter and small tables')),
    ('bg_street_eatery', background('a Vietnamese sidewalk eatery with plastic stools and a metal table')),
    ('bg_store', background('a convenience store aisle with shelves of products without labels')),
    ('bg_gym', background('a gym with weights and a treadmill')),
    ('bg_elevator', background('the inside of an elevator')),
    ('bg_street', background('a city street with shops and parked motorbikes, daytime')),
    ('bg_alley', background('a narrow Vietnamese alley')),
    ('bg_market', background('a local open-air market')),
    ('bg_park', background('a park with trees and a bench')),
    ('bg_school_yard', background('a school yard')),
    ('bg_beach', background('a sunny beach')),
    ('bg_countryside', background('countryside rice fields')),
    ('bg_mountains', background('green mountains under a blue sky')),
    ('bg_bus_stop', background('a bus stop by the road')),
    ('bg_rooftop', background('a rooftop at sunset')),
    ('bg_stage', background('an empty theater stage with red curtains and a spotlight')),
    ('bg_space', background('outer space with stars and planets')),
    ('bg_street_night', background('a city street at night with street lights')),
    ('bg_bedroom_night', background('a bedroom at night, lights off, moonlight from the window')),
    ('prop_furniture', sheet('plastic stool, office chair, small table, sofa, bed, wardrobe, door, window')),
    ('prop_home', sheet('standing fan, TV, floor lamp, fridge, wall clock, pillow, blanket, umbrella')),
    ('prop_food', sheet('bowl of noodles with chopsticks, plate of rice, banh mi sandwich, bubble tea cup, '
                        'coffee cup, beer can, water bottle, birthday cake')),
    ('prop_kitchen_tech', sheet('cooking pot, frying pan, smartphone, laptop, headphones, TV remote, '
                                'phone charger, game controller')),
    ('prop_study_office', sheet('book, notebook, pen, school backpack, stack of papers, briefcase, '
                                'desktop computer, whiteboard')),
    ('prop_vehicles', sheet('scooter motorbike, bicycle, small car, city bus, taxi, delivery tricycle',
                            '2 columns x 3 rows')),
    ('prop_daily', sheet('paper money bills, wallet, handbag, toilet paper roll, toothbrush, medicine box, '
                         'gift box, cardboard box')),
    ('fx_stickers', sheet('sweat drop, question mark, exclamation mark, red heart, broken heart, ring of '
                          'stars, smoke puff, lightning bolt, water splash', '3 columns x 3 rows')),

    # ---- second batch (more generic locations) ----
    ('bg_hospital_corridor', background('a hospital corridor with benches and doors')),
    ('bg_supermarket_checkout', background('a supermarket checkout counter with a conveyor belt')),
    ('bg_bank_counter', background('a bank service counter with glass windows')),
    ('bg_cinema', background('a cinema hall with red seats facing a blank screen')),
    ('bg_library', background('a quiet library with tall bookshelves')),
    ('bg_swimming_pool', background('an outdoor swimming pool with deck chairs')),
    ('bg_wedding_hall', background('a decorated Vietnamese wedding hall with flowers and round tables')),
    ('bg_tet_house', background('a Vietnamese living room decorated for Lunar New Year with a peach blossom branch, a kumquat tree and red lanterns')),
    ('bg_bus_interior', background('inside a city bus with seats and hand straps')),
    ('bg_car_interior', background('inside a car seen from the back seat, dashboard and windshield')),
    ('bg_restaurant', background('a restaurant dining room with tables and hanging lamps')),
    ('bg_karaoke_room', background('a karaoke room with a sofa, a big screen and disco lights')),
    ('bg_apartment_corridor', background('an apartment building corridor with doors')),
    ('bg_meeting_room', background('an office meeting room with a long table and a blank screen')),
    ('bg_construction_site', background('a construction site with scaffolding and sand piles')),
    ('bg_farm', background('a Vietnamese countryside farmyard with a haystack and a well')),
    ('bg_forest', background('a green forest path')),
    ('bg_rainy_street', background('a city street in heavy rain with puddles')),
    ('bg_airport', background('an airport departure hall with seats and big windows')),
    ('bg_train_station', background('a train station platform')),
    ('bg_messy_room', background('a very messy bedroom with clothes and snacks everywhere')),
    ('bg_office_night', background('an empty office at night, only one desk lamp on')),
]
TEST = ('bg_living_room', 'prop_food')

# Extra sticker sheets: name -> [(item id, English for the prompt, Vietnamese tag for the script writer)]
SHEET_ITEMS = {
    'prop_tet': [('banh_chung', 'square banh chung rice cake wrapped in green leaves', 'bánh chưng'),
                 ('red_envelope', 'blank red lucky money envelope', 'bao lì xì'),
                 ('peach_blossom', 'peach blossom branch in a vase', 'cành đào'),
                 ('kumquat_tree', 'small kumquat tree in a pot', 'cây quất'),
                 ('red_lantern', 'red paper lantern', 'đèn lồng đỏ'),
                 ('fruit_tray', 'tray of five fruits', 'mâm ngũ quả'),
                 ('candy_box', 'round Tet candy box', 'hộp mứt Tết'),
                 ('apricot_blossom', 'yellow apricot blossom branch in a vase', 'cành mai')],
    'prop_sports': [('soccer_ball', 'soccer ball', 'quả bóng đá'), ('dumbbell', 'dumbbell', 'tạ tay'),
                    ('badminton_racket', 'badminton racket with shuttlecock', 'vợt cầu lông'),
                    ('running_shoes', 'pair of running shoes', 'giày chạy bộ'), ('jump_rope', 'jump rope', 'dây nhảy'),
                    ('yoga_mat', 'rolled yoga mat', 'thảm tập'), ('whistle', 'sports whistle', 'còi'),
                    ('basketball', 'basketball', 'quả bóng rổ')],
    'prop_clothes': [('tshirt', 'plain t-shirt', 'áo phông'), ('jeans', 'jeans', 'quần jean'),
                     ('sneakers', 'sneakers', 'giày thể thao'), ('cap', 'baseball cap', 'mũ lưỡi trai'),
                     ('conical_hat', 'Vietnamese conical hat', 'nón lá'), ('sunglasses', 'sunglasses', 'kính râm'),
                     ('necktie', 'necktie', 'cà vạt'), ('raincoat', 'raincoat', 'áo mưa')],
    'prop_tools': [('broom', 'broom', 'chổi'), ('bucket', 'bucket', 'xô nước'), ('mop', 'mop', 'cây lau nhà'),
                   ('toolbox', 'toolbox', 'hộp đồ nghề'), ('ladder', 'ladder', 'thang'),
                   ('watering_can', 'watering can', 'bình tưới'), ('screwdriver', 'screwdriver', 'tua vít'),
                   ('flashlight', 'flashlight', 'đèn pin')],
    'prop_medical': [('pill_bottle', 'pill bottle', 'lọ thuốc'), ('pills', 'two pills', 'viên thuốc'),
                     ('thermometer', 'thermometer', 'nhiệt kế'), ('bandage', 'adhesive bandage', 'băng dán'),
                     ('face_mask', 'face mask', 'khẩu trang'), ('ice_pack', 'ice pack', 'túi chườm đá'),
                     ('crutches', 'pair of crutches', 'nạng'), ('wheelchair', 'wheelchair', 'xe lăn')],
    'prop_animals': [('dog', 'cute dog', 'con chó'), ('cat', 'cute cat', 'con mèo'), ('chicken', 'chicken', 'con gà'),
                     ('duck', 'duck', 'con vịt'), ('pig', 'pig', 'con lợn'), ('goldfish_bowl', 'goldfish in a round bowl', 'bể cá vàng'),
                     ('parrot', 'parrot', 'con vẹt'), ('buffalo', 'water buffalo', 'con trâu')],
    'prop_shopping': [('gold_coins', 'pile of gold coins', 'đống tiền vàng'), ('gold_bar', 'gold bar', 'thỏi vàng'),
                      ('piggy_bank', 'piggy bank', 'lợn đất tiết kiệm'), ('bank_card', 'blank bank card', 'thẻ ngân hàng'),
                      ('atm', 'ATM machine', 'cây ATM'), ('shopping_bag', 'shopping bag', 'túi mua sắm'),
                      ('shopping_cart', 'shopping cart', 'xe đẩy siêu thị'), ('price_tag', 'blank price tag', 'nhãn giá')],
    'prop_party': [('balloons', 'bunch of balloons', 'chùm bóng bay'), ('party_hat', 'party hat', 'mũ sinh nhật'),
                   ('party_popper', 'party popper with confetti', 'pháo giấy'), ('microphone', 'microphone', 'micro'),
                   ('guitar', 'acoustic guitar', 'đàn guitar'), ('speaker', 'loudspeaker box', 'loa thùng'),
                   ('wine_glass', 'wine glass', 'ly rượu'), ('beer_crate', 'crate of beer bottles', 'két bia')],
    'prop_school': [('calculator', 'calculator', 'máy tính bỏ túi'), ('test_paper', 'exam paper with red cross marks', 'bài kiểm tra bị gạch đỏ'),
                    ('ruler', 'ruler', 'thước kẻ'), ('eraser', 'eraser', 'tẩy'), ('globe', 'globe', 'quả địa cầu'),
                    ('school_bell', 'school drum', 'trống trường'), ('chalk', 'pieces of chalk', 'phấn'), ('abacus', 'abacus', 'bàn tính')],
    'fx_more': [('music_notes', 'music notes', 'nốt nhạc'), ('flames', 'fire flames', 'lửa cháy'),
                ('light_bulb', 'glowing idea light bulb', 'bóng đèn ý tưởng'), ('rain_cloud', 'small rain cloud', 'mây mưa trên đầu'),
                ('snowflake', 'snowflake', 'bông tuyết lạnh'), ('skull', 'cartoon skull', 'đầu lâu, chết rồi'),
                ('puddle_tears', 'puddle of tears', 'vũng nước mắt'), ('heart_eyes', 'pair of heart shapes', 'hai trái tim mê mẩn'),
                ('dizzy_birds', 'ring of little birds circling', 'chim bay vòng chóng mặt')],
}
for _name, _items in SHEET_ITEMS.items():
    _grid = '3 columns x 3 rows' if len(_items) == 9 else '2 columns x 4 rows'
    ASSETS.append((_name, sheet(', '.join(english for _, english, _ in _items), _grid)))



ROUND = 0  # bumped after a ChatGPT limit so a refused request is never re-sent under the same id


def task_id(name):
    return str(uuid.uuid5(NAMESPACE, 'meme-asset-v2:' + name + (':r%d' % ROUND if ROUND else '')))


def post(prompt, ident):
    data = json.dumps({'task_id': ident, 'prompt': prompt}).encode()
    request = urllib.request.Request(DAEMON + '/api/images/generate', data=data, method='POST',
                                     headers={'Content-Type': 'application/json', 'X-VS-Client': 'videostudio'})
    try:
        with urllib.request.urlopen(request, timeout=1200) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read())
        except ValueError:
            return {'ok': False, 'error': 'HTTP %s' % error.code}


def main():
    global ROUND
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--only')
    parser.add_argument('--patient', action='store_true', help='on a ChatGPT image limit wait 30 min and continue (max 12 waits)')
    args = parser.parse_args()
    for ROUND in range(13 if args.patient else 1):
        code = run_once(args)
        if code != 1 or not args.patient or ROUND == 12:
            return code
        with (OUT / '_log.txt').open('a', encoding='utf8') as f:
            f.write(time.strftime('%H:%M:%S ') + 'Cho 30 phut roi thu lai (lan %d/12)...\n' % (ROUND + 1))
        time.sleep(1800)
    return 1


def run_once(args):
    wanted = TEST if args.test else (args.only.split(',') if args.only else [n for n, _ in ASSETS])
    todo = [(n, p) for n, p in ASSETS if n in wanted]
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / '_log.txt'
    results_path = OUT / '_results.json'
    try:
        results = json.loads(results_path.read_text(encoding='utf8'))
    except (OSError, ValueError):
        results = {}

    def note(text):
        line = time.strftime('%H:%M:%S ') + text
        print(line, flush=True)
        with log.open('a', encoding='utf8') as f:
            f.write(line + '\n')

    failures = 0
    for i, (name, prompt) in enumerate(todo, 1):
        target = OUT / (name + '.png')
        if target.exists():
            note('[%d/%d] %s: da co, bo qua' % (i, len(todo), name))
            continue
        note('[%d/%d] %s: dang nho ChatGPT ve...' % (i, len(todo), name))
        started = time.time()
        try:
            body = post(prompt, task_id(name))
        except Exception as error:  # connection refused, timeout
            body = {'ok': False, 'error': '%s: %s' % (type(error).__name__, error)}
        data = body.get('data') if body.get('ok') else None
        if data and Path(data.get('file_path', '')).is_file():
            shutil.copyfile(data['file_path'], target)
            results[name] = {'task_id': task_id(name), 'sha256': data.get('sha256'),
                             'conversation_url': data.get('conversation_url'), 'seconds': round(time.time() - started)}
            results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf8')
            note('    xong sau %ds -> %s' % (time.time() - started, target.name))
            failures = 0
            continue
        failures += 1
        error = str(body.get('error') or body)[:400]
        note('    LOI: ' + error)
        results[name] = {'task_id': task_id(name), 'error': error}
        results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf8')
        if 'Connection refused' in error or 'WinError 10061' in error:
            note('VideoStudio chua bat. Chuot phai icon khay -> Mo he thong, roi chay lai.')
            return 2
        if any(k in error.lower() for k in ('sign in', 'verification')) or failures >= 3:
            note('Dung lai de tranh gui them. Xem loi o tren roi chay lai sau.')
            return 1
    note('Hoan tat. File nam trong ' + str(OUT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
