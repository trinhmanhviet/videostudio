"""Failing-first tests for the isolated Gemini text transport.

Covers: provider-qualified journal identity (legacy ChatGPT key preserved),
provider-scoped conversation registry, Gemini URL validation, Gemini turn
correlation (only a NEW completed reply counts, streaming/stale rejected),
and explicit transport routing that never falls back between providers.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio.cdp_requests import RequestJournal, valid_chat_url, valid_provider_url
from videostudio import cdp_gemini
from videostudio.cdp_gemini import correlate_gemini, valid_gemini_url


class JournalProviderIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = RequestJournal(Path(self.tmp.name) / 'requests.db')
        self.addCleanup(self.tmp.cleanup)

    def test_chatgpt_identity_is_unchanged_for_legacy_receipts(self):
        import hashlib
        prompt = 'legacy prompt'
        hashed = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        expected = hashlib.sha256(('job-1' + '\0' + hashed).encode()).hexdigest()
        self.assertEqual(self.journal.prepare('job-1', prompt)['id'], expected)
        self.assertEqual(self.journal.prepare('job-1', prompt, provider='chatgpt')['id'], expected)

    def test_same_job_and_prompt_do_not_collide_across_providers(self):
        chatgpt = self.journal.prepare('job-2', 'same prompt')['id']
        gemini = self.journal.prepare('job-2', 'same prompt', provider='gemini')['id']
        self.assertNotEqual(chatgpt, gemini)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            self.journal.prepare('job-3', 'prompt', provider='openai-web')

    def test_claimed_gemini_receipt_cannot_be_resubmitted(self):
        identifier = self.journal.prepare('job-4', 'prompt', provider='gemini')['id']
        self.journal.claim_send(identifier)
        with self.assertRaises(Exception):
            self.journal.claim_send(identifier)

    def test_conversations_are_scoped_per_provider(self):
        self.journal.set_conversation('job-5', 'https://chatgpt.com/c/abc', 'target-chat')
        self.journal.set_conversation('job-5', 'https://gemini.google.com/app', 'target-gem', provider='gemini')
        self.assertEqual(self.journal.conversation('job-5')['target'], 'target-chat')
        self.assertEqual(self.journal.conversation('job-5', provider='gemini')['target'], 'target-gem')

    def test_gemini_conversation_url_must_be_gemini(self):
        with self.assertRaises(ValueError):
            self.journal.set_conversation('job-6', 'https://chatgpt.com/c/abc', 't', provider='gemini')


class UrlValidationTests(unittest.TestCase):
    def test_provider_urls_are_not_interchangeable(self):
        self.assertTrue(valid_chat_url('https://chatgpt.com/c/1'))
        self.assertFalse(valid_chat_url('https://gemini.google.com/app'))
        self.assertTrue(valid_gemini_url('https://gemini.google.com/app'))
        self.assertFalse(valid_gemini_url('https://chatgpt.com/c/1'))
        self.assertFalse(valid_gemini_url('https://gemini.google.com.evil.test/app'))
        self.assertFalse(valid_gemini_url('http://gemini.google.com/app'))

    def test_valid_provider_url_dispatches_by_provider(self):
        self.assertTrue(valid_provider_url('chatgpt', 'https://chatgpt.com/c/1'))
        self.assertTrue(valid_provider_url('gemini', 'https://gemini.google.com/app'))
        self.assertFalse(valid_provider_url('gemini', 'https://chatgpt.com/c/1'))
        with self.assertRaises(ValueError):
            valid_provider_url('unknown', 'https://chatgpt.com/c/1')


class GeminiCorrelationTests(unittest.TestCase):
    def test_completed_new_reply_matching_marker_is_accepted(self):
        state = {'url': 'https://gemini.google.com/app/abc', 'login': False, 'challenge': False,
                 'generating': False, 'turns': [
                     {'role': 'user', 'text': 'older question [VideoStudio request old]'},
                     {'role': 'assistant', 'text': 'older answer'},
                     {'role': 'user', 'text': 'do the thing [VideoStudio request req-9]'},
                     {'role': 'assistant', 'text': '{"request_id":"req-9","result":{"ok":true}}'}]}
        out = correlate_gemini(state, 'req-9')
        self.assertTrue(out['matched'])
        self.assertEqual(json.loads(out['text'])['request_id'], 'req-9')

    def test_streaming_reply_is_not_accepted(self):
        state = {'url': 'https://gemini.google.com/app/abc', 'login': False, 'challenge': False,
                 'generating': True, 'turns': [
                     {'role': 'user', 'text': 'q [VideoStudio request req-9]'},
                     {'role': 'assistant', 'text': '{"request_id":"req-9","res'}]}
        self.assertIsNone(correlate_gemini(state, 'req-9'))

    def test_stale_reply_before_the_marker_is_never_used(self):
        state = {'url': 'https://gemini.google.com/app/abc', 'login': False, 'challenge': False,
                 'generating': False, 'turns': [
                     {'role': 'assistant', 'text': '{"request_id":"req-9","result":{"ok":true}}'},
                     {'role': 'user', 'text': 'q [VideoStudio request req-9]'}]}
        self.assertIsNone(correlate_gemini(state, 'req-9'))

    def test_marker_in_composer_only_is_not_a_reply(self):
        state = {'url': 'https://gemini.google.com/app', 'login': False, 'challenge': False,
                 'generating': False, 'draft': 'q [VideoStudio request req-9]', 'turns': []}
        self.assertIsNone(correlate_gemini(state, 'req-9'))

    def test_duplicate_marker_is_ambiguous(self):
        state = {'url': 'https://gemini.google.com/app/abc', 'login': False, 'challenge': False,
                 'generating': False, 'turns': [
                     {'role': 'user', 'text': 'q [VideoStudio request req-9]'},
                     {'role': 'assistant', 'text': 'a'},
                     {'role': 'user', 'text': 'q again [VideoStudio request req-9]'},
                     {'role': 'assistant', 'text': 'b'}]}
        with self.assertRaises(ValueError):
            correlate_gemini(state, 'req-9')

    def test_snapshot_expression_carries_marker_and_reads_turns(self):
        expression = cdp_gemini.gemini_snapshot_expression('req-9')
        self.assertIn('model-response', expression)
        self.assertIn('user-query', expression)
        self.assertIn('contenteditable', expression)


class GeminiTransportRoutingTests(unittest.TestCase):
    def _pipeline(self):
        from videostudio.providers import Pipeline
        with patch.dict('os.environ', {}, clear=False):
            import inspect
            sig = inspect.signature(Pipeline.__init__)
            self.assertIn('self', sig.parameters)
        return Pipeline

    def test_gemini_transport_posts_to_gemini_route_and_requires_job_context(self):
        import inspect
        from videostudio import providers
        source = inspect.getsource(providers.Pipeline.llm_json)
        self.assertIn("'gemini'", source, 'llm_json must handle VS_LLM_TRANSPORT=gemini explicitly')
        self.assertIn('/api/gemini', source, 'gemini transport must call the daemon gemini route')

    def test_daemon_exposes_gemini_route_and_adapter(self):
        from videostudio import cdp_daemon
        self.assertTrue(hasattr(cdp_daemon.ChromeChatGPTBridge, 'ask_gemini'))
        source = inspect_source = None
        import inspect as _inspect
        source = _inspect.getsource(cdp_daemon)
        self.assertIn("/api/gemini", source)
        self.assertIsNone(inspect_source)


class GeminiTextFallbackTests(unittest.TestCase):
    """Builds without user-query/model-response elements fall back to ordered chat text."""

    def state(self, chat, generating=False):
        return {'url': 'https://gemini.google.com/app', 'login': False, 'challenge': False,
                'generating': generating, 'composer': True, 'draft': '', 'turns': [], 'chatText': chat}

    def test_reply_json_after_marker_with_placeholder_echo_is_ignored(self):
        chat = ('[VideoStudio request r1]\n'
                'Return exactly one JSON object with this envelope: '
                '{"request_id": "r1", "result": {"your_response": "replace with the requested JSON object"}}\n'
                '{"request_id":"r1","result":{"smoke":"abc","ok":true}}')
        out = correlate_gemini(self.state(chat), '[VideoStudio request r1]', 'r1')
        self.assertTrue(out['matched'])
        self.assertEqual(json.loads(out['text'])['result']['smoke'], 'abc')

    def test_no_reply_yet_returns_none(self):
        chat = '[VideoStudio request r1]\nReturn exactly one JSON object with this envelope: ' \
               '{"request_id": "r1", "result": {"your_response": "replace with the requested JSON object"}}'
        self.assertIsNone(correlate_gemini(self.state(chat), '[VideoStudio request r1]', 'r1'))

    def test_generating_blocks_acceptance(self):
        chat = '[VideoStudio request r1]\n{"request_id":"r1","result":{"ok":true}}'
        self.assertIsNone(correlate_gemini(self.state(chat, generating=True), '[VideoStudio request r1]', 'r1'))

    def test_reply_with_a_different_request_id_is_ignored(self):
        chat = '[VideoStudio request r1]\n{"request_id":"other","result":{"ok":true}}'
        self.assertIsNone(correlate_gemini(self.state(chat), '[VideoStudio request r1]', 'r1'))

    def test_duplicate_marker_in_chat_text_is_ambiguous(self):
        chat = ('[VideoStudio request r1]\n{"request_id":"r1","result":{"ok":true}}\n'
                '[VideoStudio request r1]\n{"request_id":"r1","result":{"ok":false}}')
        with self.assertRaises(ValueError):
            correlate_gemini(self.state(chat), '[VideoStudio request r1]', 'r1')


class GeminiSendControlTests(unittest.TestCase):
    def test_send_expression_is_scoped_to_the_input_area_and_exact_labels(self):
        expression = cdp_gemini.gemini_send_button_expression()
        self.assertIn('input-area-v2', expression, 'send control must be scoped to the composer input area')
        self.assertIn('send message', expression.lower())
        self.assertNotIn('/gửi/i.test', expression, 'a bare /gửi/ match hits feedback buttons, not send')


class GeminiRenderedReplyTests(unittest.TestCase):
    """The real Gemini build renders a 'JSON' chip and copy chrome around the object."""

    def test_turn_whose_text_wraps_the_json_is_accepted(self):
        state = {'url': 'https://gemini.google.com/app/x', 'login': False, 'challenge': False,
                 'generating': False, 'turns': [
                     {'role': 'user', 'text': '[VideoStudio request r2] do it'},
                     {'role': 'assistant', 'text': 'JSON\n{"request_id": "r2", "result": {"your_response": {"smoke": "t", "ok": true}}}\nCopy code'}]}
        out = correlate_gemini(state, '[VideoStudio request r2]', 'r2')
        self.assertTrue(out['matched'])
        self.assertEqual(json.loads(out['text'])['request_id'], 'r2')

    def test_turn_without_the_embedded_object_is_not_accepted(self):
        state = {'url': 'https://gemini.google.com/app/x', 'login': False, 'challenge': False,
                 'generating': False, 'turns': [
                     {'role': 'user', 'text': '[VideoStudio request r2] do it'},
                     {'role': 'assistant', 'text': 'Sure! Here is the JSON you asked for.'}]}
        self.assertIsNone(correlate_gemini(state, '[VideoStudio request r2]', 'r2'))



class JobTextProviderRoutingTests(unittest.TestCase):
    def _pipeline(self, provider):
        from types import SimpleNamespace
        from videostudio.providers import Pipeline
        p = Pipeline.__new__(Pipeline)
        p.context = SimpleNamespace(job='job-1', text_provider=provider)
        return p

    def _call(self, provider, env_transport):
        from types import SimpleNamespace
        from unittest.mock import patch
        import httpx
        seen = {}

        class FakeResponse:
            status_code = 200
            def raise_for_status(self):
                return None
            def json(self):
                return {'ok': True, 'data': {'your_response': {'routed': seen['path']}}}

        def fake_post(url, **kwargs):
            seen['path'] = url
            return FakeResponse()

        p = self._pipeline(provider)
        with patch.dict('os.environ', {'VS_CDP_DAEMON_URL': 'http://127.0.0.1:8879', 'VS_LLM_TRANSPORT': env_transport}), \
             patch('videostudio.providers.httpx.post', side_effect=fake_post):
            result = p.llm_json('prompt', lambda: None)
        return result, seen['path']

    def test_job_provider_gemini_routes_to_gemini_even_when_env_is_cdp(self):
        result, path = self._call('gemini', 'cdp')
        self.assertEqual(path, 'http://127.0.0.1:8879/api/gemini')
        self.assertEqual(result, {'routed': path})

    def test_job_provider_chatgpt_keeps_chat_route_even_when_env_is_gemini(self):
        result, path = self._call('chatgpt', 'gemini')
        self.assertEqual(path, 'http://127.0.0.1:8879/api/chat')

    def test_request_accepts_text_provider_and_rejects_unknown_values(self):
        from videostudio.core import validate_request
        base = {'idea': 'topic', 'voice_id': 'preset:test', 'duration_seconds': 30}
        self.assertEqual(validate_request({**base, 'text_provider': 'gemini'})['text_provider'], 'gemini')
        self.assertEqual(validate_request(base)['text_provider'], 'chatgpt')
        with self.assertRaises(ValueError):
            validate_request({**base, 'text_provider': 'claude'})

class GeminiSmokeReceiptTests(unittest.TestCase):
    def test_normalize_accepts_flat_and_enveloped_replies(self):
        from videostudio.gemini_smoke import normalize
        self.assertEqual(normalize({'connection_test': 'videostudio', 'ok': True})['ok'], True)
        self.assertEqual(normalize({'your_response': {'connection_test': 'videostudio', 'ok': True}}),
                         {'connection_test': 'videostudio', 'ok': True})

    def test_receipt_round_trip_and_rejection(self):
        import tempfile, os
        from unittest.mock import patch
        from videostudio import gemini_smoke
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'gemini-smoke.json')
            with patch.dict('os.environ', {'VS_GEMINI_SMOKE': path}):
                self.assertFalse(gemini_smoke.accepted_gemini_smoke())
                with self.assertRaises(ValueError):
                    gemini_smoke.record_gemini_smoke({'connection_test': 'videostudio', 'ok': False})
                gemini_smoke.record_gemini_smoke({'your_response': {'connection_test': 'videostudio', 'ok': True}})
                self.assertTrue(gemini_smoke.accepted_gemini_smoke())


if __name__ == '__main__':
    unittest.main()
