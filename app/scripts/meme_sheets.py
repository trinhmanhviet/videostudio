"""Sticker sheets for the HyperFrames prop library: item order, names, Vietnamese tags and the ChatGPT prompt.

Draw the sheets in the ChatGPT desktop app (never in VideoStudio's own Chrome). Then:
    python scripts/meme_sheets.py              # writes tmp/prompt_chatgpt_sheets.txt (4 sheets per message)
    python scripts/ingest_asset_zips.py        # ZIPs from Downloads -> new/ (sheets) and memestudio backgrounds
    python scripts/import_meme_library.py      # cut sheets into catalog/library (read by HyperFrames)
"""
from pathlib import Path

STYLE = 'Style: very simple flat 2D cartoon, a bit ugly like a quickly drawn meme. EVERY object has a thin, clean, single continuous dark brown outline (not thick, not wobbly, not shaky). Flat fills only, in dull earthy muted colors: beige, cream, light brown, dull moss green, grey-blue; any sky is a flat pale grey-blue. Simple shapes, minimal detail. No painterly look, no shading, no shadows, no gradients, no glow, no reflections, no neon, no bright or saturated colors, no 3D, no modern glossy look. Absolutely no text, letters, numbers, signs with words or brand logos.'

# sheet -> [(item id, English for the prompt, Vietnamese tag)]; 8 items = 2x4 grid, 9 items = 3x3 grid
SHEET_ITEMS = {
    'prop_tet': [
        ('banh_chung', 'square banh chung rice cake wrapped in green leaves', 'bánh chưng'),
        ('red_envelope', 'blank red lucky money envelope', 'bao lì xì'),
        ('peach_blossom', 'peach blossom branch in a vase', 'cành đào'),
        ('kumquat_tree', 'small kumquat tree in a pot', 'cây quất'),
        ('red_lantern', 'red paper lantern', 'đèn lồng đỏ'),
        ('fruit_tray', 'tray of five fruits', 'mâm ngũ quả'),
        ('candy_box', 'round Tet candy box', 'hộp mứt Tết'),
        ('apricot_blossom', 'yellow apricot blossom branch in a vase', 'cành mai'),
    ],
    'prop_sports': [
        ('soccer_ball', 'soccer ball', 'quả bóng đá'),
        ('dumbbell', 'dumbbell', 'tạ tay'),
        ('badminton_racket', 'badminton racket with shuttlecock', 'vợt cầu lông'),
        ('running_shoes', 'pair of running shoes', 'giày chạy bộ'),
        ('jump_rope', 'jump rope', 'dây nhảy'),
        ('yoga_mat', 'rolled yoga mat', 'thảm tập'),
        ('whistle', 'sports whistle', 'còi'),
        ('basketball', 'basketball', 'quả bóng rổ'),
    ],
    'prop_clothes': [
        ('tshirt', 'plain t-shirt', 'áo phông'),
        ('jeans', 'jeans', 'quần jean'),
        ('sneakers', 'sneakers', 'giày thể thao'),
        ('cap', 'baseball cap', 'mũ lưỡi trai'),
        ('conical_hat', 'Vietnamese conical hat', 'nón lá'),
        ('sunglasses', 'sunglasses', 'kính râm'),
        ('necktie', 'necktie', 'cà vạt'),
        ('raincoat', 'raincoat', 'áo mưa'),
    ],
    'prop_tools': [
        ('broom', 'broom', 'chổi'),
        ('bucket', 'bucket', 'xô nước'),
        ('mop', 'mop', 'cây lau nhà'),
        ('toolbox', 'toolbox', 'hộp đồ nghề'),
        ('ladder', 'ladder', 'thang'),
        ('watering_can', 'watering can', 'bình tưới'),
        ('screwdriver', 'screwdriver', 'tua vít'),
        ('flashlight', 'flashlight', 'đèn pin'),
    ],
    'prop_medical': [
        ('pill_bottle', 'pill bottle', 'lọ thuốc'),
        ('pills', 'two pills', 'viên thuốc'),
        ('thermometer', 'thermometer', 'nhiệt kế'),
        ('bandage', 'adhesive bandage', 'băng dán'),
        ('face_mask', 'face mask', 'khẩu trang'),
        ('ice_pack', 'ice pack', 'túi chườm đá'),
        ('crutches', 'pair of crutches', 'nạng'),
        ('wheelchair', 'wheelchair', 'xe lăn'),
    ],
    'prop_animals': [
        ('dog', 'cute dog', 'con chó'),
        ('cat', 'cute cat', 'con mèo'),
        ('chicken', 'chicken', 'con gà'),
        ('duck', 'duck', 'con vịt'),
        ('pig', 'pig', 'con lợn'),
        ('goldfish_bowl', 'goldfish in a round bowl', 'bể cá vàng'),
        ('parrot', 'parrot', 'con vẹt'),
        ('buffalo', 'water buffalo', 'con trâu'),
    ],
    'prop_shopping': [
        ('gold_coins', 'pile of gold coins', 'đống tiền vàng'),
        ('gold_bar', 'gold bar', 'thỏi vàng'),
        ('piggy_bank', 'piggy bank', 'lợn đất tiết kiệm'),
        ('bank_card', 'blank bank card', 'thẻ ngân hàng'),
        ('atm', 'ATM machine', 'cây ATM'),
        ('shopping_bag', 'shopping bag', 'túi mua sắm'),
        ('shopping_cart', 'shopping cart', 'xe đẩy siêu thị'),
        ('price_tag', 'blank price tag', 'nhãn giá'),
    ],
    'prop_party': [
        ('balloons', 'bunch of balloons', 'chùm bóng bay'),
        ('party_hat', 'party hat', 'mũ sinh nhật'),
        ('party_popper', 'party popper with confetti', 'pháo giấy'),
        ('microphone', 'microphone', 'micro'),
        ('guitar', 'acoustic guitar', 'đàn guitar'),
        ('speaker', 'loudspeaker box', 'loa thùng'),
        ('wine_glass', 'wine glass', 'ly rượu'),
        ('beer_crate', 'crate of beer bottles', 'két bia'),
    ],
    'prop_school': [
        ('calculator', 'calculator', 'máy tính bỏ túi'),
        ('test_paper', 'exam paper with red cross marks', 'bài kiểm tra bị gạch đỏ'),
        ('ruler', 'ruler', 'thước kẻ'),
        ('eraser', 'eraser', 'tẩy'),
        ('globe', 'globe', 'quả địa cầu'),
        ('school_bell', 'school drum', 'trống trường'),
        ('chalk', 'pieces of chalk', 'phấn'),
        ('abacus', 'abacus', 'bàn tính'),
    ],
    'fx_more': [
        ('music_notes', 'music notes', 'nốt nhạc'),
        ('flames', 'fire flames', 'lửa cháy'),
        ('light_bulb', 'glowing idea light bulb', 'bóng đèn ý tưởng'),
        ('rain_cloud', 'small rain cloud', 'mây mưa trên đầu'),
        ('snowflake', 'snowflake', 'bông tuyết lạnh'),
        ('skull', 'cartoon skull', 'đầu lâu, chết rồi'),
        ('puddle_tears', 'puddle of tears', 'vũng nước mắt'),
        ('heart_eyes', 'pair of heart shapes', 'hai trái tim mê mẩn'),
        ('dizzy_birds', 'ring of little birds circling', 'chim bay vòng chóng mặt'),
    ],
    'prop_fruit': [
        ('banana', 'bunch of bananas', 'chuối'),
        ('apple', 'red apple', 'táo'),
        ('watermelon_slice', 'slice of watermelon', 'dưa hấu'),
        ('orange', 'orange fruit', 'cam'),
        ('mango', 'mango', 'xoài'),
        ('durian', 'durian', 'sầu riêng'),
        ('pineapple', 'pineapple', 'dứa, thơm'),
        ('grapes', 'bunch of grapes', 'nho'),
    ],
    'prop_street_food': [
        ('pho_bowl', 'bowl of pho noodle soup with herbs', 'phở'),
        ('instant_noodle_cup', 'instant noodle cup with a fork', 'mì gói, mì ly'),
        ('hot_pot', 'hot pot with steam', 'lẩu'),
        ('grilled_skewers', 'grilled meat skewers', 'nướng, xiên que'),
        ('ice_cream_cone', 'ice cream cone', 'kem'),
        ('hamburger', 'hamburger', 'hamburger'),
        ('pizza_slice', 'slice of pizza', 'pizza'),
        ('fried_chicken_bucket', 'bucket of fried chicken', 'gà rán'),
    ],
    'prop_kitchenware': [
        ('rice_cooker', 'electric rice cooker', 'nồi cơm điện'),
        ('electric_kettle', 'electric kettle', 'ấm siêu tốc'),
        ('tea_set', 'teapot with two small cups', 'ấm trà'),
        ('thermos_flask', 'old thermos flask', 'phích nước'),
        ('knife_cutting_board', 'kitchen knife on a cutting board', 'dao thớt'),
        ('bowl_chopsticks', 'rice bowl with chopsticks', 'bát đũa'),
        ('gas_stove', 'two-burner gas stove', 'bếp ga'),
        ('water_dispenser', 'water dispenser with a bottle on top', 'cây nước'),
    ],
    'prop_bathroom': [
        ('washing_machine', 'front-loading washing machine', 'máy giặt'),
        ('toilet', 'toilet', 'bồn cầu'),
        ('sink_faucet', 'sink with a faucet', 'bồn rửa, vòi nước'),
        ('shower_head', 'shower head with water drops', 'vòi sen, tắm'),
        ('towel', 'folded towel', 'khăn tắm'),
        ('soap_bar', 'bar of soap with bubbles', 'xà phòng'),
        ('mirror', 'standing mirror', 'gương'),
        ('trash_bin', 'small trash bin', 'thùng rác'),
    ],
    'prop_electronics': [
        ('tablet', 'tablet', 'máy tính bảng'),
        ('digital_camera', 'digital camera', 'máy ảnh'),
        ('smart_watch', 'smart watch', 'đồng hồ thông minh'),
        ('keyboard', 'computer keyboard without letters', 'bàn phím'),
        ('computer_mouse', 'computer mouse', 'chuột máy tính'),
        ('printer', 'office printer', 'máy in'),
        ('wifi_router', 'wifi router with antennas', 'bộ phát wifi'),
        ('power_bank', 'power bank', 'sạc dự phòng'),
    ],
    'prop_retro_90s': [
        ('rotary_phone', 'old rotary desk phone', 'điện thoại bàn cũ'),
        ('crt_tv', 'old CRT television with antenna', 'ti vi cũ'),
        ('cassette_player', 'cassette player', 'máy cassette'),
        ('old_radio', 'old radio', 'đài radio cũ'),
        ('desk_fan', 'small desk fan', 'quạt bàn'),
        ('wall_calendar_pad', 'tear-off wall calendar without numbers', 'lịch tờ'),
        ('kerosene_lamp', 'kerosene oil lamp', 'đèn dầu'),
        ('ceiling_fan', 'ceiling fan', 'quạt trần'),
    ],
    'prop_village': [
        ('bamboo_basket', 'round bamboo basket', 'thúng, rổ tre'),
        ('shoulder_pole_baskets', 'bamboo shoulder pole with two baskets', 'đòn gánh'),
        ('hoe', 'farming hoe', 'cuốc'),
        ('sickle', 'sickle', 'liềm'),
        ('clay_jar', 'clay water jar', 'chum, vại nước'),
        ('hammock', 'hammock between two posts', 'võng'),
        ('rice_sack', 'sack of rice', 'bao gạo'),
        ('wheelbarrow', 'wheelbarrow', 'xe cút kít'),
    ],
    'prop_animals2': [
        ('cockroach', 'cartoon cockroach', 'con gián'),
        ('mosquito', 'cartoon mosquito', 'con muỗi'),
        ('frog', 'frog', 'con ếch'),
        ('rabbit', 'rabbit', 'con thỏ'),
        ('cow', 'cow', 'con bò'),
        ('horse', 'horse', 'con ngựa'),
        ('mouse', 'mouse', 'con chuột'),
        ('pigeon', 'pigeon', 'con bồ câu'),
    ],
    'prop_nature': [
        ('tree_green', 'green leafy tree', 'cây xanh'),
        ('palm_tree', 'coconut palm tree', 'cây dừa'),
        ('bush', 'bush', 'bụi cây'),
        ('flower_bouquet', 'bouquet of flowers', 'bó hoa'),
        ('potted_plant', 'potted plant', 'chậu cây'),
        ('rock', 'grey rock', 'hòn đá'),
        ('bamboo_clump', 'clump of bamboo', 'bụi tre'),
        ('log_firewood', 'pile of firewood logs', 'củi'),
    ],
    'prop_street': [
        ('street_lamp', 'street lamp', 'đèn đường'),
        ('traffic_light', 'traffic light', 'đèn giao thông'),
        ('park_bench', 'park bench', 'ghế đá'),
        ('street_trash_bin', 'street trash bin', 'thùng rác đường phố'),
        ('power_pole', 'power pole with tangled wires', 'cột điện'),
        ('blank_road_sign', 'blank road sign without symbols', 'biển báo'),
        ('vendor_cart', 'street vendor cart with an umbrella', 'xe bán hàng rong'),
        ('traffic_cone', 'traffic cone', 'cọc tiêu'),
    ],
    'prop_office2': [
        ('stapler', 'stapler', 'dập ghim'),
        ('scissors', 'scissors', 'kéo'),
        ('tape_roll', 'roll of tape', 'băng dính'),
        ('file_folder', 'file folder', 'tập hồ sơ'),
        ('clipboard', 'clipboard with blank paper', 'bìa kẹp giấy'),
        ('name_badge', 'blank name badge on a lanyard', 'thẻ nhân viên'),
        ('desk_calendar', 'blank desk calendar', 'lịch để bàn'),
        ('trophy', 'gold trophy cup', 'cúp'),
    ],
    'prop_jobs': [
        ('hard_hat', 'yellow hard hat', 'mũ bảo hộ'),
        ('hammer', 'hammer', 'búa'),
        ('wrench', 'wrench', 'cờ lê'),
        ('drill', 'power drill', 'máy khoan'),
        ('chef_hat', 'chef hat', 'mũ đầu bếp'),
        ('stethoscope', 'stethoscope', 'ống nghe bác sĩ'),
        ('police_cap', 'police cap', 'mũ công an'),
        ('graduation_cap', 'graduation cap', 'mũ tốt nghiệp'),
    ],
    'prop_romance': [
        ('rose', 'single red rose', 'hoa hồng'),
        ('love_letter', 'love letter envelope with a heart seal', 'thư tình'),
        ('ring_box', 'open ring box with a ring', 'nhẫn cầu hôn'),
        ('chocolate_box', 'heart shaped chocolate box', 'hộp socola'),
        ('teddy_bear', 'teddy bear', 'gấu bông'),
        ('candle', 'lit candle', 'nến'),
        ('key', 'old key', 'chìa khóa'),
        ('padlock', 'padlock', 'ổ khóa'),
    ],
    'fx_weather': [
        ('sun', 'plain sun with rays', 'mặt trời, nắng'),
        ('moon', 'crescent moon', 'mặt trăng'),
        ('cloud', 'white cloud', 'đám mây'),
        ('rainbow', 'rainbow', 'cầu vồng'),
        ('raindrops', 'falling rain drops', 'mưa'),
        ('thunder_cloud', 'dark storm cloud with lightning', 'giông bão'),
        ('wind_swirl', 'wind swirl lines', 'gió'),
        ('snowman', 'snowman', 'người tuyết'),
        ('shooting_star', 'shooting star', 'sao băng'),
    ],
    'fx_marks': [
        ('red_arrow', 'big red arrow', 'mũi tên đỏ'),
        ('red_circle', 'red hand-drawn circle', 'khoanh tròn đỏ'),
        ('check_mark', 'green check mark', 'dấu tích đúng'),
        ('cross_mark', 'red cross mark', 'dấu x sai'),
        ('speech_bubble', 'blank speech bubble', 'bong bóng thoại'),
        ('thought_bubble', 'blank thought bubble', 'bong bóng suy nghĩ'),
        ('spotlight_beam', 'spotlight beam cone', 'đèn rọi'),
        ('crown', 'gold crown', 'vương miện'),
        ('angel_halo', 'angel halo', 'vòng hào quang'),
    ],
    'fx_emotion2': [
        ('tear_streams', 'two streams of tears', 'khóc ròng'),
        ('blush_marks', 'pair of blush marks', 'đỏ mặt, ngại'),
        ('shock_lines', 'radiating shock lines', 'giật mình'),
        ('dust_cloud', 'running dust cloud', 'bụi chạy'),
        ('anger_cloud', 'red angry steam puffs', 'tức giận bốc khói'),
        ('sparkles', 'group of sparkles', 'lấp lánh'),
        ('anger_vein', 'anger vein mark', 'nổi gân'),
        ('fireworks', 'fireworks burst', 'pháo hoa'),
        ('confetti_burst', 'confetti burst', 'tung hoa giấy'),
    ],
}


def grid(items):
    return '3 columns x 3 rows' if len(items) == 9 else '2 columns x 4 rows'


def message(sheets, number):
    text = ('Draw %d separate PNG images, one image per sheet, one after another. Each image is a sticker sheet of separate '
            'objects on a fully transparent background (if real transparency is impossible, use a solid flat #FF00FF magenta '
            'background instead, never a checkerboard). ' % len(sheets) + STYLE +
            ' For every sheet: front or 3/4 view, each object isolated with plenty of empty space around it, objects never touch '
            'or overlap, no ground shadows, same size feel for all objects, neat grid. Make every object a single connected piece '
            '(no floating parts).\n\n')
    for name in sheets:
        items = SHEET_ITEMS[name]
        text += 'File %s.png - grid %s, in this exact reading order (left to right, top to bottom): %s.\n' % (
            name, grid(items), '; '.join('%d) %s' % (i + 1, english) for i, (_, english, _) in enumerate(items)))
    return text + ('\nWhen all %d images are drawn, create ONE ZIP file named S%d_sheets.zip containing the PNGs named exactly '
                   'as above (keep full resolution, transparent background) and give me the download link right in your answer.'
                   % (len(sheets), number))


def main(names=None):
    names = names or list(SHEET_ITEMS)
    batches = [names[i:i + 4] for i in range(0, len(names), 4)]
    out = Path(__file__).resolve().parents[2] / 'data' / 'memestudio' / 'prompt_chatgpt_sheets.txt'
    out.parent.mkdir(exist_ok=True)
    out.write_text('\n\n=========\n\n'.join(message(b, n) for n, b in enumerate(batches, 1)), encoding='utf-8')
    print(out)


if __name__ == '__main__':
    import sys
    main(sys.argv[1:] or None)
