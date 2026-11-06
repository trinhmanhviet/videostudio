import json, sys, tempfile, unittest, wave, struct, math
from pathlib import Path
from unittest.mock import patch, MagicMock

from videostudio.core import Store, digest
from videostudio.providers import Pipeline, split_caption_lines
from videostudio.captions import wrap_caption
from videostudio.scene_editor import SceneEditor

class MultiSentenceSceneTests(unittest.TestCase):
    def test_split_caption_lines_single_short_sentence(self):
        text = "Một buổi sáng bình yên ở làng chài ven biển."
        lines = split_caption_lines(text)
        self.assertEqual(lines, [text])
        self.assertIsNotNone(wrap_caption(lines[0]))

    def test_split_caption_lines_multi_sentence(self):
        text = "Mặt trời vừa ló rạng trên biển. Từng con sóng vỗ nhẹ vào mạn thuyền nan. Những người ngư dân chuẩn bị dong buồm ra khơi."
        lines = split_caption_lines(text)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "Mặt trời vừa ló rạng trên biển.")
        self.assertEqual(lines[1], "Từng con sóng vỗ nhẹ vào mạn thuyền nan.")
        self.assertEqual(lines[2], "Những người ngư dân chuẩn bị dong buồm ra khơi.")
        for line in lines:
            self.assertIsNotNone(wrap_caption(line))

    def test_split_caption_lines_long_sentence_with_commas(self):
        long_sentence = (
            "Tiếng gọi nhau í ới của những người làng chài xé tan màn sương sớm, "
            "tạo nên một khung cảnh lao động nhộn nhịp và tràn đầy sức sống của một ngày mới."
        )
        lines = split_caption_lines(long_sentence)
        self.assertGreater(len(lines), 1)
        for line in lines:
            # Must satisfy wrap_caption without raising ValueError
            wrapped = wrap_caption(line)
            self.assertLessEqual(len(wrapped.split('\n')), 3)

    def test_long_sentences_break_at_natural_points_not_mid_phrase(self):
        # Real narration from job b2bfd1e9: the old greedy split voiced "vấn." / "mình." / "hiểu ..." alone.
        cases = {
            'Một ngày tưởng như bình thường tại ngôi làng nhỏ bất ngờ bị phá vỡ bởi một cái chết đầy nghi vấn.': 'nghi vấn',
            'Theo thông tin được dẫn từ Tây An Vãn Báo, khoảng 12 giờ trưa hôm đó, cảnh sát nhận được tin báo về vụ việc.': 'tin báo',
            'Cảnh tượng trước mắt khiến mọi người nghĩ đến khả năng người phụ nữ đã tự kết liễu cuộc đời mình.': 'khả năng',
            'Với những vụ việc bất thường, điều quan trọng không chỉ là nhìn thấy gì, mà còn phải tìm hiểu vì sao mọi thứ lại xuất hiện ở đúng vị trí đó.': 'tìm hiểu',
        }
        for sentence, phrase in cases.items():
            lines = split_caption_lines(sentence)
            self.assertGreater(len(lines), 1, sentence)
            self.assertEqual(' '.join(lines), sentence)
            self.assertTrue(any(phrase in line for line in lines), lines)
            for line in lines:
                self.assertGreaterEqual(len(line.split()), 4, lines)
                wrap_caption(line)
        self.assertEqual(split_caption_lines(list(cases)[1])[0], 'Theo thông tin được dẫn từ Tây An Vãn Báo,')

    def test_speech_attempt_produces_scene_and_utterance_hierarchy(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t)
            script = {
                'scenes': [
                    {
                        'scene_id': 'scene-0',
                        'narration': 'Câu mở đầu cảnh 1. Câu tiếp theo cảnh 1.',
                        'narration_lines': ['Câu mở đầu cảnh 1.', 'Câu tiếp theo cảnh 1.'],
                        'music_prompt': 'Calm acoustic guitar',
                    },
                    {
                        'scene_id': 'scene-1',
                        'narration': 'Câu kết thúc ở cảnh 2.',
                        'narration_lines': ['Câu kết thúc ở cảnh 2.'],
                        'music_prompt': 'Triumphant orchestral strings',
                    }
                ]
            }

            p = Pipeline.__new__(Pipeline)
            p.voices = MagicMock()
            selected_voice = {'id': 'voice-1', 'reference_path': None}
            p.voices.selected.return_value = selected_voice
            p.voices.catalog.return_value = {'voices': [selected_voice]}
            p.speech_python = sys.executable
            p.speech_cache = out / 'speech_cache'
            p.ffmpeg = 'ffmpeg'
            p.ffprobe = 'ffprobe'

            # Pre-generate valid 1-second 16kHz sine wav files for the 3 utterances
            for i in range(3):
                part = out / f'speech-{i:04}.wav'
                with wave.open(str(part), 'wb') as w:
                    w.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                    # 16000 samples of 440Hz sine wave
                    frames = b''.join(struct.pack('<h', int(3000 * math.sin(2 * math.pi * 440 * s / 16000))) for s in range(16000))
                    w.writeframes(frames)
                receipt = part.with_suffix('.json')
                lines = ['Câu mở đầu cảnh 1.', 'Câu tiếp theo cảnh 1.', 'Câu kết thúc ở cảnh 2.']
                import hashlib
                identity = hashlib.sha256(json.dumps({'narration': lines[i], 'voice': selected_voice}, sort_keys=True).encode()).hexdigest()
                receipt.write_text(json.dumps({'identity': identity, 'sha256': digest(part)}))

            job = {
                'id': 'test-speech-job',
                'output': str(out),
                'request': {'voice_id': 'voice-1'},
                'checkpoints': {'script': script}
            }
            speech = p._speech_attempt(job, lambda: None, revision=out)

            # Check utterances: should be 3 total (2 in scene 0, 1 in scene 1)
            self.assertEqual(len(speech['utterances']), 3)
            self.assertEqual(speech['utterances'][0]['scene_index'], 0)
            self.assertEqual(speech['utterances'][1]['scene_index'], 0)
            self.assertEqual(speech['utterances'][2]['scene_index'], 1)

            # Check scenes timing: should be 2 scenes
            self.assertEqual(len(speech['scenes']), 2)
            # Scene 0 has 2 utterances of 1s each -> duration ~ 2.0s
            self.assertAlmostEqual(speech['scenes'][0]['duration'], 2.0, places=1)
            self.assertEqual(speech['scenes'][0]['start'], 0.0)
            self.assertAlmostEqual(speech['scenes'][0]['end'], 2.0, places=1)

            # Scene 1 has 1 utterance of 1s -> duration ~ 1.0s, start ~ 2.0s
            self.assertAlmostEqual(speech['scenes'][1]['duration'], 1.0, places=1)
            self.assertAlmostEqual(speech['scenes'][1]['start'], 2.0, places=1)
            self.assertAlmostEqual(speech['scenes'][1]['end'], 3.0, places=1)

            # Now test subtitles step generates valid subtitles
            job['checkpoints']['speech'] = speech
            subs_result = p.subtitles(job, lambda: None)
            self.assertTrue(Path(subs_result['path']).is_file())
            self.assertTrue(Path(subs_result['srt_path']).is_file())

    def test_scene_editor_layout_groups_multi_utterances_per_image(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            store = Store(p / 'jobs.db', p / 'out')
            job, _ = store.create({'idea': 'Editor multi-scene test', 'duration_seconds': 10, 'voice_id': 'preset:test'}, 'test-editor-key')
            jid = job['id']
            out_dir = Path(job['output'])

            images = [
                {'path': str(out_dir / 'images-0000.png'), 'scene_index': 0, 'duration': 5.0},
                {'path': str(out_dir / 'images-0001.png'), 'scene_index': 1, 'duration': 4.0},
            ]
            assets = []
            for im in images:
                p_im = Path(im['path'])
                p_im.write_text('dummy-img')
                h = digest(p_im)
                im['sha256'] = h
                assets.append({'path': str(p_im.resolve()), 'sha256': h})

            utterances = [
                {'index': 0, 'scene_index': 0, 'narration': 'Câu 1 cảnh 1', 'start': 0.0, 'end': 2.0, 'duration': 2.0, 'path': str(out_dir / 'speech-0000.wav')},
                {'index': 1, 'scene_index': 0, 'narration': 'Câu 2 cảnh 1', 'start': 2.0, 'end': 5.0, 'duration': 3.0, 'path': str(out_dir / 'speech-0001.wav')},
                {'index': 2, 'scene_index': 1, 'narration': 'Câu 1 cảnh 2', 'start': 5.0, 'end': 9.0, 'duration': 4.0, 'path': str(out_dir / 'speech-0002.wav')},
            ]
            for u in utterances:
                Path(u['path']).write_text('dummy-audio')

            with store.db() as c:
                c.execute("INSERT INTO checkpoints VALUES(?,?,?)", (
                    jid, 'script', json.dumps({
                        'scenes': [
                            {'narration': 'Câu 1 cảnh 1. Câu 2 cảnh 1.', 'visual_prompt': 'Prompt 1'},
                            {'narration': 'Câu 1 cảnh 2.', 'visual_prompt': 'Prompt 2'},
                        ]
                    })
                ))
                c.execute("INSERT INTO checkpoints VALUES(?,?,?)", (
                    jid, 'speech', json.dumps({
                        'utterances': utterances,
                        'scenes': [
                            {'scene_index': 0, 'start': 0.0, 'end': 5.0, 'duration': 5.0},
                            {'scene_index': 1, 'start': 5.0, 'end': 9.0, 'duration': 4.0},
                        ],
                        'duration_seconds': 9.0,
                        'assets': [{'path': u['path'], 'sha256': digest(Path(u['path']))} for u in utterances]
                    })
                ))
                c.execute("INSERT INTO checkpoints VALUES(?,?,?)", (
                    jid, 'images', json.dumps({
                        'scenes': images,
                        'assets': assets
                    })
                ))

            editor = SceneEditor(store)
            view_data = editor.view(jid)
            scenes = view_data['scenes']

            # Must have 2 scene cards matching the 2 images
            self.assertEqual(len(scenes), 2)
            self.assertEqual(scenes[0]['index'], 0)
            self.assertEqual(scenes[0]['duration'], 5.0)
            self.assertIn('Câu 1 cảnh 1', scenes[0]['narration'])
            self.assertIn('Câu 2 cảnh 1', scenes[0]['narration'])

            self.assertEqual(scenes[1]['index'], 1)
            self.assertEqual(scenes[1]['duration'], 4.0)
            self.assertIn('Câu 1 cảnh 2', scenes[1]['narration'])

            # Audio file for scene 0 resolves to speech-0000.wav
            af = editor.audio_file(jid, scenes[0]['scene_id'])
            self.assertTrue(af.is_file())
            self.assertEqual(af.name, 'speech-0000.wav')

if __name__ == '__main__':
    unittest.main()
