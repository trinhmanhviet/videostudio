import hashlib
import json
import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock

from videostudio.captions import split_caption_scenes, wrap_caption
from videostudio.core import digest
from videostudio.providers import Pipeline
from videostudio.providers import split_caption_lines, validate_flow_character_manifest
from videostudio.storyboard import group_supplied_scenes


class VisualSceneGroupingTests(unittest.TestCase):
    lines = [
        'Người thợ đặt thanh sắt nóng lên chiếc đe trong góc xưởng.',
        'Ông nâng chiếc búa nặng rồi giáng xuống thanh sắt đỏ rực.',
        'Những tia lửa nhỏ bắn lên và tan dần trong không khí lạnh.',
    ]

    def job(self, folder, duration=600, grouped=True):
        return {'id': '00000000-0000-4000-8000-000000000001', 'output': str(folder),
                'request': {'idea': 'Người thợ rèn', 'duration_seconds': duration,
                            'image_provider': 'chatgpt', 'voice_id': 'fixture'},
                'checkpoints': {'plan': {'title': 'Xưởng rèn', 'music_prompt': 'instrumental',
                                         **({'visual_grouping_version': 1} if grouped else {})},
                                'research': {'sources': []}}}

    def chapter(self, prompt='A blacksmith in a workshop'):
        return {'narration': ' '.join(self.lines), 'source_paths': [],
                'scenes': [{'narration': ' '.join(self.lines), 'narration_lines': self.lines,
                            'visual_prompt': prompt, 'character_ids': []}]}

    def test_new_production_plan_enables_grouping(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.preflight = Mock(return_value={'ready': True})
        pipeline.voices = Mock()
        pipeline.llm_json = Mock(return_value={'title': 'Xưởng rèn', 'visual_style': 'documentary',
                                              'music_prompt': 'instrumental', 'characters': []})
        job = self.job('.', duration=45)
        job['request']['workflow_mode'] = 'provided_narration'
        plan = pipeline.plan(job, lambda: None)
        self.assertEqual(plan.get('visual_grouping_version'), 1)

    def test_chapters_keep_visual_scenes_independent_of_caption_length_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            pipeline = Pipeline.__new__(Pipeline)
            pipeline.llm_json = Mock(side_effect=[{'chapters': [{'index': 1}, {'index': 2}]},
                                                  self.chapter(), self.chapter('A forge at night')])
            job = self.job(folder)
            result = pipeline._script_draft(job, lambda: None, [])
            self.assertEqual(len(result['scenes']), 2)
            self.assertEqual([s['narration_lines'] for s in result['scenes']], [self.lines, self.lines])
            self.assertEqual(result['narration'], ' '.join(self.lines * 2))
            self.assertEqual([s['scene_id'] for s in result['scenes']], ['scene-0000', 'scene-0001'])
            pipeline.llm_json.assert_called()
            self.assertEqual(pipeline.llm_json.call_count, 3)
            before = {p.name: p.read_bytes() for p in Path(folder).glob('*.json')}
            pipeline.llm_json = Mock(side_effect=AssertionError('Cached chapters must not call ChatGPT'))
            resumed = pipeline._script_draft(job, lambda: None, [])
            self.assertEqual(resumed, result)
            self.assertEqual(before, {p.name: p.read_bytes() for p in Path(folder).glob('*.json')})

    def test_legacy_chapter_cache_and_ids_are_not_regrouped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'chapters.json').write_text(json.dumps({'chapters': [{'index': 1}, {'index': 2}]}))
            for index in (1, 2):
                (root / f'chapter-{index:02}.json').write_text(json.dumps(self.chapter()))
            before = {p.name: p.read_bytes() for p in root.glob('*.json')}
            pipeline = Pipeline.__new__(Pipeline)
            pipeline.llm_json = Mock(side_effect=AssertionError('Legacy cache must be preserved'))
            result = pipeline._script_draft(self.job(folder), lambda: None, [])
            expected = split_caption_scenes(self.chapter()['scenes']) * 2
            self.assertEqual(len(result['scenes']), len(expected))
            self.assertEqual([s['narration'] for s in result['scenes']], [s['narration'] for s in expected])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.glob('*.json')})

    def test_bad_optional_caption_metadata_cannot_drop_or_add_narration(self):
        for raw_lines in ([self.lines[0]], ['A different invented sentence.'], 'not a list', [123]):
            with self.subTest(raw_lines=raw_lines), tempfile.TemporaryDirectory() as folder:
                pipeline = Pipeline.__new__(Pipeline)
                draft = self.chapter()
                draft['scenes'][0]['narration_lines'] = raw_lines
                pipeline.llm_json = Mock(return_value=draft)
                result = pipeline._script_draft(self.job(folder, duration=45), lambda: None, [])
                self.assertEqual(result['narration'], ' '.join(self.lines))
                self.assertEqual(len(result['scenes']), 1)
                self.assertEqual(' '.join(result['scenes'][0]['narration_lines']), result['narration'])
                for line in result['scenes'][0]['narration_lines']:
                    wrap_caption(line)
                pipeline.llm_json.assert_called_once()

    def test_sentence_count_and_duplicate_model_ids_do_not_define_image_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            lines = self.lines + self.lines[:2]
            first = {'scene_id': 'duplicate', 'narration': self.lines[0], 'visual_prompt': 'Outside the forge'}
            second = {'scene_id': 'duplicate', 'narration': ' '.join(lines),
                      'narration_lines': lines, 'visual_prompt': 'Inside the forge'}
            pipeline = Pipeline.__new__(Pipeline)
            pipeline.llm_json = Mock(return_value={'narration': first['narration'] + ' ' + second['narration'],
                                                  'source_paths': [], 'scenes': [first, second]})
            result = pipeline._script_draft(self.job(folder, duration=45), lambda: None, [])
            self.assertEqual([len(s['narration_lines']) for s in result['scenes']], [1, 5])
            self.assertEqual([s['scene_id'] for s in result['scenes']], ['scene-0000', 'scene-0001'])

    def test_new_flow_chapters_keep_character_conditioning(self):
        with tempfile.TemporaryDirectory() as folder:
            chapter = self.chapter('An East Asian blacksmith with short black hair')
            chapter['scenes'][0]['character_ids'] = ['smith']
            chapter['characters'] = [{'character_id': 'smith', 'name': 'Thợ rèn',
                                       'appearance_evidence': ['short black hair']}]
            pipeline = Pipeline.__new__(Pipeline)
            pipeline.llm_json = Mock(side_effect=[{'chapters': [{'index': 1}, {'index': 2}]},
                                                  chapter, json.loads(json.dumps(chapter))])
            job = self.job(folder)
            job['request']['image_provider'] = 'flow'
            result = pipeline._script_draft(job, lambda: None, [])
            validate_flow_character_manifest(result)
            self.assertEqual(len(result['scenes']), 2)
            self.assertEqual([s['character_ids'] for s in result['scenes']], [['smith'], ['smith']])
            self.assertEqual(len(result['characters']), 1)
            self.assertEqual(pipeline.llm_json.call_count, 3)

    def test_targeted_factual_repair_updates_spoken_lines_and_keeps_scene_identity(self):
        for corrected in ('Thông tin đúng đã được đối chiếu.', ' '.join(self.lines)):
            with self.subTest(corrected=corrected):
                self.assert_repaired_narration(corrected)

    def assert_repaired_narration(self, corrected):
        with tempfile.TemporaryDirectory() as folder:
            original = 'Thông tin cũ cần được sửa.'
            pipeline = Pipeline.__new__(Pipeline)
            pipeline.llm_json = Mock(side_effect=[
                {'narration': original, 'source_paths': [], 'scenes': [
                    {'scene_id': 'original-id', 'narration': original, 'narration_lines': [original],
                     'visual_prompt': 'A historical workshop'}]},
                {'accepted': False, 'blocking_issues': [{'scene_index': 0, 'reason': 'Incorrect fact'}], 'claims': []},
                {'changes': [{'index': 0, 'scene_id': 'replacement-id', 'narration': corrected,
                             'visual_prompt': 'A corrected historical workshop'}]},
                {'accepted': True, 'blocking_issues': [], 'claims': []},
            ])
            result = pipeline.script(self.job(folder, duration=45), lambda: None)
            scene = result['scenes'][0]
            self.assertEqual(scene['narration'], corrected)
            self.assertEqual(scene['narration_lines'], split_caption_lines(corrected))
            self.assertEqual(scene['scene_id'], 'scene-0000')

    def test_supplied_group_labels_cannot_merge_different_or_nonadjacent_visuals(self):
        for middle_prompt, middle_characters, expected in [('A room', ['other'], 3),
                                                          ('A different location', [], 3),
                                                          ('A room', [], 1)]:
            with self.subTest(middle_prompt=middle_prompt, middle_characters=middle_characters):
                scenes = [{'scene_id': f'line-{i}', 'narration': line, 'visual_group_id': 'same',
                           'visual_prompt': 'A room', 'character_ids': []} for i, line in enumerate(self.lines)]
                scenes[1].update(visual_prompt=middle_prompt, character_ids=middle_characters)
                result = group_supplied_scenes(scenes, split_caption_lines)
                self.assertEqual(len(result), expected)
                self.assertEqual(' '.join(s['narration'] for s in result), ' '.join(self.lines))

    def supplied_job(self, folder):
        job = self.job(folder, duration=45)
        job['request'].update(workflow_mode='provided_narration', idea='\n'.join(self.lines))
        job['checkpoints']['plan'].update(visual_style='documentary', characters=[])
        return job

    def supplied_metadata(self):
        return {'characters': [], 'scenes': [
            {'line_id': 'line-0001', 'visual_group_id': 'forge', 'visual_prompt': 'A forge', 'character_ids': []},
            {'line_id': 'line-0002', 'visual_group_id': 'forge', 'visual_prompt': 'A forge', 'character_ids': []},
            {'line_id': 'line-0003', 'visual_group_id': 'sparks', 'visual_prompt': 'Flying sparks', 'character_ids': []},
        ]}

    def test_supplied_lines_group_automatically_without_changing_original_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            pipeline = Pipeline.__new__(Pipeline)
            pipeline.llm_json = Mock(return_value=self.supplied_metadata())
            result = pipeline._provided_script_draft(self.supplied_job(folder), lambda: None)
            self.assertEqual(len(result['scenes']), 2)
            self.assertEqual(result['scenes'][0]['narration_lines'], self.lines[:2])
            self.assertEqual(result['narration'], ' '.join(self.lines))
            manifest = json.loads((Path(folder) / 'user-narration.json').read_text(encoding='utf8'))
            self.assertEqual([line['narration'] for line in manifest['lines']], self.lines)
            self.assertEqual([line['line_id'] for line in manifest['lines']],
                             ['line-0001', 'line-0002', 'line-0003'])
            pipeline.llm_json.assert_called_once()

    def test_bad_or_absent_supplied_group_metadata_falls_back_without_extra_model_calls(self):
        for group in (None, [], {'invalid': 'group'}):
            with self.subTest(group=group), tempfile.TemporaryDirectory() as folder:
                pipeline = Pipeline.__new__(Pipeline)
                metadata = self.supplied_metadata()
                for scene in metadata['scenes']:
                    scene['visual_group_id'] = group
                pipeline.llm_json = Mock(return_value=metadata)
                result = pipeline._provided_script_draft(self.supplied_job(folder), lambda: None)
                self.assertEqual(len(result['scenes']), 3)
                self.assertEqual(result['narration'], ' '.join(self.lines))
                pipeline.llm_json.assert_called_once()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_grouped_script_drives_measured_caption_and_image_timeline(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pipeline = Pipeline.__new__(Pipeline)
            pipeline.llm_json = Mock(return_value=self.supplied_metadata())
            job = self.supplied_job(folder)
            job['checkpoints']['script'] = pipeline._provided_script_draft(job, lambda: None)
            voice = {'id': 'fixture', 'reference_path': None}
            pipeline.voices = Mock()
            pipeline.voices.selected.return_value = voice
            pipeline.ffmpeg = 'ffmpeg'
            pipeline.ffprobe = 'ffprobe'
            for index, line in enumerate(self.lines):
                path = root / f'speech-{index:04}.wav'
                with wave.open(str(path), 'wb') as wav:
                    wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                    wav.writeframes(b''.join(struct.pack('<h', int(3000 * math.sin(2 * math.pi * 440 * i / 16000)))
                                             for i in range(3200)))
                identity = hashlib.sha256(json.dumps({'narration': line, 'voice': voice}, sort_keys=True).encode()).hexdigest()
                path.with_suffix('.json').write_text(json.dumps({'identity': identity, 'sha256': digest(path)}))
            job['checkpoints']['speech'] = pipeline._speech_attempt(job, lambda: None, root)
            def image_result(provider, job, index, prompt, path, check, **kwargs):
                Image.effect_noise((512, 512), 30).convert('RGB').save(path)
                return {'task_id': f'fixture-{index}', 'request_id': f'fixture-{index}', 'width': 512, 'height': 512}
            pipeline._browser_scene_image = Mock(side_effect=image_result)
            images = pipeline._images(job, lambda: None)
            captions = pipeline.subtitles(job, lambda: None)
            speech = job['checkpoints']['speech']
            self.assertEqual(len(speech['utterances']), 3)
            self.assertEqual([u['scene_index'] for u in speech['utterances']], [0, 0, 1])
            self.assertEqual(pipeline._browser_scene_image.call_count, 2)
            self.assertEqual(len(images['scenes']), 2)
            self.assertAlmostEqual(images['scenes'][0]['duration'], .4)
            self.assertAlmostEqual(images['scenes'][1]['duration'], .2)
            self.assertAlmostEqual(sum(s['duration'] for s in images['scenes']), speech['duration_seconds'])
            self.assertEqual(Path(captions['srt_path']).read_text(encoding='utf8').count('-->'), 3)
            from videostudio import media
            music = root / 'fixture-music.wav'
            media.run(['ffmpeg', '-v', 'error', '-y', '-stream_loop', '1', '-i', speech['path'], music], lambda: None)
            rendered = media.render(images['scenes'], speech['path'], music, captions['ass_path'],
                                    root / 'fixture-video.mp4', speech['duration_seconds'], lambda: None)
            report = media.verify(rendered['video'], speech['duration_seconds'])
            self.assertTrue(report['verified'])
            media.run(['ffmpeg', '-v', 'error', '-i', rendered['video'], '-f', 'null', '-'], lambda: None)


if __name__ == '__main__':
    unittest.main()
