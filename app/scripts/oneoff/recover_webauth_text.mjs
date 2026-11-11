// Read-only recovery of the exact synthetic WebAuth smoke response already visible in AICoworker.
// This is NOT a general job transport and does not write an acceptance receipt.
import { connect, evaluate, listTargets } from 'file:///C:/Users/leath/aicoworker/openclaw/skills/aicoworker-self-control/scripts/cdp.mjs';

const expectedPrompt = 'Return exactly one JSON object with these fields and no other fields: {"connection_test":"videostudio-webauth","ok":true}';
const expected = { connection_test: 'videostudio-webauth', ok: true };
const tabs = (await listTargets()).filter(t => t.type === 'page' && new URL(t.url).hostname === 'chatgpt.com');
const matches = [];
for (const tab of tabs) {
  const client = await connect(t => t.id === tab.id);
  try {
    const turns = await evaluate(client, () => Array.from(document.querySelectorAll('[data-content-search-unit-key]')).map(e => ({
      key: e.getAttribute('data-content-search-unit-key'),
      text: e.innerText,
    })));
    const prompt = turns.find(t => t.key?.endsWith(':user') && t.text.trim() === expectedPrompt);
    const reply = turns.find(t => t.key?.endsWith(':assistant') && turns.indexOf(t) === turns.indexOf(prompt) + 1);
    if (!prompt || !reply) continue;
    const text = reply.text.replace(/^ChatGPT said:\s*/u, '').trim();
    let value;
    try { value = JSON.parse(text); } catch { continue; }
    if (Object.keys(value).length === 2 && value.connection_test === expected.connection_test && value.ok === expected.ok) {
      matches.push({ conversation: new URL(tab.url).pathname, response: value });
    }
  } finally { await client.close(); }
}
const unique = new Map(matches.map(x => [x.conversation, x]));
if (unique.size !== 1) throw new Error(`Expected one exact conversation match; got ${unique.size}`);
console.log(JSON.stringify({ recovered: true, ...unique.values().next().value, source: 'visible WebAuth DOM only; production acceptance remains locked' }));
