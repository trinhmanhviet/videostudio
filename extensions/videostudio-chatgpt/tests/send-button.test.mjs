import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { isSendButton } = require('../send-button.cjs');

test('accepts the current ChatGPT Send button without test id', () => {
  assert.equal(isSendButton('Send', null), true);
  assert.equal(isSendButton('Send prompt', null), true);
  assert.equal(isSendButton('Gửi', null), true);
});

test('rejects unrelated buttons and permits the explicit send-button test id', () => {
  assert.equal(isSendButton('Send feedback', null), false);
  assert.equal(isSendButton('Expand', null), false);
  assert.equal(isSendButton(null, 'send-button'), true);
});
