"""Offline: cut named Panda sprites out of the production sheets into a catalog.

Run once after the sheets change (needs opencv-python + numpy, not needed at runtime):
    python scripts/build_meme_catalog.py
Writes assets/Meme_Animation_Asset_Pack/catalog/panda/<id>.png and catalog/panda.json.
Only pixels of connected components whose centre lies inside the item box are kept,
so neighbouring sprites on the sheet never bleed into a crop.
"""
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

PACK = Path(__file__).resolve().parents[1] / 'assets' / 'Meme_Animation_Asset_Pack'
SHEETS = {
    'actions': PACK / 'Panda/production_sheets/panda_actions_props_sheet.png',
    'faces': PACK / 'Panda/production_sheets/panda_expression_asset_sheet.png',
    'rig': PACK / 'Panda/production_sheets/panda_rig_sprite_sheet.png',
}
# Pixels per 'panda unit': the rig sheet is drawn ~25% larger than the others.
SHEET_SCALE = {'actions': 1.0, 'faces': 1.0, 'rig': 0.78}
# id, sheet, bbox [x0,y0,x1,y1], kind, Vietnamese/English tags for the script writer
ITEMS = [
    # --- full-body poses (actions sheet) ---
    ('sit_phone', 'actions', [38, 33, 181, 235], 'pose', 'ngồi bấm điện thoại, lướt mạng, nhắn tin'),
    ('laptop', 'actions', [199, 36, 412, 214], 'pose', 'ngồi gõ laptop, làm việc, chơi máy tính'),
    ('gaming', 'actions', [420, 35, 578, 237], 'pose', 'ngồi cầm tay cầm chơi game'),
    ('drink_hot', 'actions', [596, 34, 778, 236], 'pose', 'phì phèo tẩu thuốc bốc khói, thư thái, ra vẻ'),
    ('megaphone', 'actions', [778, 36, 944, 247], 'pose', 'cầm loa hét to, thông báo, quảng cáo'),
    ('stand', 'actions', [963, 50, 1102, 247], 'pose', 'đứng bình thường, nói chuyện'),
    ('clipboard', 'actions', [1129, 47, 1280, 251], 'pose', 'cầm bảng ghi chép, kiểm tra, ghi sổ'),
    ('hammer', 'actions', [1284, 9, 1445, 253], 'pose', 'giơ búa tức giận, đòi đánh, quyết tâm'),
    ('umbrella', 'actions', [22, 241, 209, 469], 'pose', 'che ô dưới mưa, buồn, ướt'),
    ('camera', 'actions', [225, 260, 383, 470], 'pose', 'cầm máy ảnh chụp hình, quay lén'),
    ('money_fan', 'actions', [399, 262, 565, 468], 'pose', 'cầm xấp tiền, giàu, khoe tiền, nhận lương'),
    ('gift', 'actions', [577, 270, 735, 468], 'pose', 'ôm hộp quà, tặng quà, sinh nhật'),
    ('lean_table', 'actions', [744, 281, 919, 445], 'pose', 'chống cằm bên bàn, chán nản, suy nghĩ'),
    ('sleep_table', 'actions', [916, 265, 1119, 445], 'pose', 'gục đầu xuống bàn ngủ, kiệt sức'),
    ('overwork', 'actions', [1117, 257, 1437, 459], 'pose', 'ngồi bàn chất đống giấy tờ, toát mồ hôi, tăng ca'),
    ('stop_hand', 'actions', [21, 485, 184, 651], 'half', 'giơ tay chặn lại, từ chối, dừng lại'),
    ('phone_call', 'actions', [206, 487, 353, 653], 'half', 'nghe điện thoại, gọi điện'),
    ('clap', 'actions', [389, 486, 520, 651], 'half', 'vỗ tay, khen ngợi'),
    ('trophy', 'actions', [559, 483, 758, 651], 'half', 'đeo huy chương cầm cúp, chiến thắng'),
    ('selfie', 'actions', [782, 485, 978, 651], 'half', 'chụp ảnh tự sướng bằng gậy, sống ảo'),
    ('beg', 'actions', [1003, 470, 1142, 658], 'pose', 'quỳ chắp tay van xin, cầu nguyện'),
    ('crawl', 'actions', [1187, 501, 1427, 653], 'pose', 'bò lết dưới đất, mệt lả, lén lút'),
    ('peek', 'actions', [16, 660, 152, 844], 'pose', 'nấp sau tường nhìn trộm'),
    ('facepalm', 'actions', [159, 666, 306, 854], 'pose', 'tay đặt lên trán, bất lực, đau đầu'),
    ('laugh_floor', 'actions', [339, 670, 517, 855], 'pose', 'ngồi cười lăn cười bò'),
    ('scream', 'actions', [535, 668, 664, 854], 'pose', 'ôm má hét lên, hoảng sợ, sốc'),
    ('whisper', 'actions', [675, 671, 930, 839], 'half', 'hai con gấu thì thầm, buôn chuyện, mách lẻo'),
    ('shrug', 'actions', [934, 673, 1157, 854], 'pose', 'nhún vai, không biết, kệ'),
    ('run', 'actions', [1164, 668, 1420, 853], 'pose', 'chạy vội, chạy trốn, trễ giờ'),
    # --- rig sheet: standing turnarounds and upper-body gestures ---
    ('stand_talk', 'rig', [228, 14, 390, 270], 'pose', 'đứng thẳng nói chuyện, chính diện'),
    ('stand_side', 'rig', [671, 9, 807, 270], 'pose', 'đứng nghiêng nhìn sang bên'),
    ('stand_back', 'rig', [1055, 14, 1217, 270], 'pose', 'quay lưng lại, bỏ đi, giận dỗi'),
    ('open_arms', 'rig', [110, 667, 421, 835], 'half', 'nửa người dang tay, giải thích, thế đấy'),
    ('clap_half', 'rig', [511, 666, 679, 834], 'half', 'nửa người vỗ tay đắc ý'),
    ('pray_half', 'rig', [807, 665, 953, 834], 'half', 'nửa người chắp tay xin xỏ'),
    ('arms_crossed', 'rig', [1087, 666, 1241, 829], 'half', 'nửa người khoanh tay, nghiêm, không chịu'),
    # --- expression heads (faces sheet row 2) ---
    ('talk', 'faces', [19, 193, 168, 321], 'face', 'nói bình thường'),
    ('worried', 'faces', [167, 195, 312, 323], 'face', 'lo lắng, buồn, ngán ngẩm'),
    ('angry', 'faces', [312, 197, 458, 324], 'face', 'tức giận, cáu'),
    ('shock', 'faces', [454, 198, 599, 324], 'face', 'sốc, há hốc, mắt tròn'),
    ('suspicious', 'faces', [596, 198, 739, 324], 'face', 'nghi ngờ, khó chịu, cau mày'),
    ('cry', 'faces', [739, 198, 882, 324], 'face', 'khóc, nước mắt chảy dài'),
    ('laugh', 'faces', [879, 200, 1024, 324], 'face', 'cười to, sung sướng'),
    ('smug', 'faces', [1023, 201, 1166, 324], 'face', 'cười đểu, gian xảo, đắc ý'),
    ('sleepy', 'faces', [1163, 203, 1300, 323], 'face', 'lim dim, chán, ngáp'),
    ('pout', 'faces', [1297, 204, 1435, 324], 'face', 'chu mỏ, làm nũng, giả vờ ngây thơ'),
    # --- effects ---
    ('question', 'faces', [34, 651, 97, 741], 'fx', 'dấu hỏi, thắc mắc'),
    ('exclaim', 'faces', [168, 650, 244, 742], 'fx', 'dấu chấm than, giật mình'),
    ('emphasis', 'faces', [439, 651, 558, 730], 'fx', 'vạch nhấn mạnh, chú ý'),
    ('burst', 'faces', [592, 637, 752, 764], 'fx', 'khung nổ, bùng lên, hét'),
    ('burst2', 'faces', [787, 632, 938, 765], 'fx', 'khung nổ lớn'),
    ('thought', 'faces', [969, 645, 1116, 754], 'fx', 'bong bóng suy nghĩ'),
    ('sparkle', 'faces', [1164, 651, 1235, 735], 'fx', 'lấp lánh'),
    ('sparkles', 'faces', [1283, 646, 1406, 736], 'fx', 'nhiều lấp lánh, sáng ý tưởng'),
    ('drop', 'faces', [41, 548, 86, 625], 'fx', 'giọt mồ hôi'),
    ('sweat', 'faces', [137, 539, 214, 629], 'fx', 'nhiều giọt mồ hôi, căng thẳng'),
    ('anger', 'faces', [522, 539, 612, 623], 'fx', 'dấu gân tức giận'),
    ('tears', 'faces', [868, 547, 988, 634], 'fx', 'dòng nước mắt'),
    ('steam', 'faces', [1153, 547, 1249, 634], 'fx', 'xì khói, bực bội'),
    ('rage_puff', 'faces', [1282, 556, 1426, 632], 'fx', 'bốc khói giận dữ hai bên'),
    ('dizzy', 'faces', [938, 763, 1048, 852], 'fx', 'chóng mặt, xoáy'),
    ('smoke', 'faces', [1071, 747, 1237, 849], 'fx', 'đám khói lớn, biến mất'),
    ('boom', 'faces', [1274, 754, 1426, 847], 'fx', 'nổ tung, va chạm'),
    # --- props ---
    ('phone', 'actions', [29, 867, 107, 958], 'prop', 'điện thoại'),
    ('laptop_prop', 'actions', [106, 867, 261, 954], 'prop', 'laptop'),
    ('gamepad', 'actions', [276, 884, 389, 958], 'prop', 'tay cầm game'),
    ('mug', 'actions', [399, 894, 479, 963], 'prop', 'cốc nóng'),
    ('megaphone_prop', 'actions', [574, 876, 661, 967], 'prop', 'cái loa'),
    ('clipboard_prop', 'actions', [685, 863, 777, 968], 'prop', 'bảng kẹp giấy'),
    ('hammer_prop', 'actions', [789, 861, 872, 972], 'prop', 'cái búa'),
    ('umbrella_prop', 'actions', [873, 849, 1021, 972], 'prop', 'cái ô'),
    ('camera_prop', 'actions', [1033, 881, 1136, 957], 'prop', 'máy ảnh'),
    ('money', 'actions', [1158, 875, 1280, 965], 'prop', 'xấp tiền'),
    ('gift_prop', 'actions', [1295, 866, 1406, 968], 'prop', 'hộp quà'),
    ('trophy_prop', 'actions', [15, 974, 119, 1073], 'prop', 'cúp vàng'),
    ('medal', 'actions', [124, 976, 196, 1074], 'prop', 'huy chương'),
    ('door', 'actions', [294, 967, 367, 1078], 'prop', 'cánh cửa'),
    ('table', 'actions', [374, 989, 536, 1075], 'prop', 'cái bàn'),
    ('lamp', 'actions', [542, 972, 636, 1075], 'prop', 'đèn bàn'),
    ('papers', 'actions', [637, 993, 725, 1075], 'prop', 'chồng giấy tờ'),
]


def components(path):
    image = Image.open(path).convert('RGBA')
    array = np.array(image)
    mask = (array[:, :, 3] > 8).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    return image, array, labels, stats, centroids


def main():
    out = PACK / 'catalog' / 'panda'
    out.mkdir(parents=True, exist_ok=True)
    loaded = {name: components(path) for name, path in SHEETS.items()}
    entries = []
    for ident, sheet, box, kind, tags in ITEMS:
        image, array, labels, stats, centroids = loaded[sheet]
        x0, y0, x1, y1 = box
        keep = [i for i in range(1, len(stats)) if stats[i][4] >= 12 and x0 <= centroids[i][0] <= x1 and y0 <= centroids[i][1] <= y1]
        region = labels[y0:y1, x0:x1]
        mask = np.isin(region, keep)
        crop = array[y0:y1, x0:x1].copy()
        crop[:, :, 3] = np.where(mask, crop[:, :, 3], 0)
        ys, xs = np.nonzero(crop[:, :, 3] > 8)
        if not len(xs):
            raise SystemExit('empty item ' + ident)
        crop = crop[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        file = out / (kind + '_' + ident + '.png')
        Image.fromarray(crop).save(file, optimize=True)
        entries.append({'id': ident, 'kind': kind, 'tags': tags, 'file': 'panda/' + file.name,
                        'size': [int(crop.shape[1]), int(crop.shape[0])], 'scale': SHEET_SCALE[sheet]})
    (PACK / 'catalog' / 'panda.json').write_text(json.dumps({'version': 1, 'character': 'panda', 'items': entries},
                                                             ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(entries), 'items ->', out)


if __name__ == '__main__':
    main()
