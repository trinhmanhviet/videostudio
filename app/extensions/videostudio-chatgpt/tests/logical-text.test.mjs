import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

const context = {};
runInNewContext(await readFile(new URL('../logical-text.js', import.meta.url), 'utf8'), context);
const { logicalText } = context.VideoStudioLogicalText;
const { receiptMatches } = context.VideoStudioLogicalText;

test('request correlation accepts the exact marker with collapsed or reflowed text',()=>{
  const prompt='YÊU CẦU STUDIO req-1\nLong complete prompt';
  assert.equal(receiptMatches('YÊU CẦU STUDIO req-1\n[collapsed]', 'req-1',prompt),true);
  assert.equal(receiptMatches('YÊU CẦU STUDIO req-1  Long\u00a0complete prompt','req-1',prompt),true);
  assert.equal(receiptMatches('YÊU CẦU STUDIO req-10\nDifferent request','req-1',prompt),false);
  assert.equal(receiptMatches(null,'req-1',prompt),false);
});

test('ProseMirror paragraphs round-trip a newline-delimited immutable prompt', () => {
  const prompt = 'YÊU CẦU STUDIO abc\nEngineering connection test only.\nRequest nonce: xyz';
  const paragraphs = prompt.split('\n').map(text => ({ tagName: 'P', innerText: text, textContent: text }));
  const editor = { tagName: 'DIV', innerText: prompt.replaceAll('\n', '\n\n'), children: paragraphs };
  assert.equal(logicalText(editor), prompt);
});

test('intentional blank paragraph is retained and unrelated content does not match', () => {
  const editor = { tagName: 'DIV', innerText: 'one\n\n\n\ntwo', children: [
    { tagName: 'P', innerText: 'one' }, { tagName: 'P', innerText: '' }, { tagName: 'P', innerText: 'two' },
  ] };
  assert.equal(logicalText(editor), 'one\n\ntwo');
  assert.notEqual(logicalText(editor), 'one\ntwo');
});
