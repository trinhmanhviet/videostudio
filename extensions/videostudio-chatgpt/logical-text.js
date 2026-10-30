// Read ProseMirror's logical paragraphs without innerText's extra layout newlines.
(function (root) {
  function paragraphText(node) {
    // ProseMirror's text is in DOM text nodes. innerText also serialises CSS
    // layout (for example block-styled links), which is not part of the prompt.
    if (!node.childNodes) return node.textContent ?? node.innerText ?? '';
    if (node.nodeType === 3) return node.nodeValue ?? '';
    if (node.tagName === 'BR') {
      const filler = node.classList?.contains('ProseMirror-trailingBreak') ||
        (node.parentNode?.tagName === 'P' && node.parentNode.childNodes.length === 1);
      return filler ? '' : '\n';
    }
    return Array.from(node.childNodes, paragraphText).join('');
  }
  function logicalText(node) {
    if (!node) return '';
    if (node.tagName === 'TEXTAREA') return node.value || '';
    const children = Array.from(node.children || []);
    if (children.length && children.every(child => child.tagName === 'P')) {
      return children.map(paragraphText).join('\n');
    }
    return node.innerText ?? node.textContent ?? '';
  }
  const normalise = value => String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const requestMarker = id => `YÊU CẦU STUDIO ${id}`;
  function receiptMatches(value, id, prompt) {
    if (typeof value !== 'string' || typeof id !== 'string' || !id || typeof prompt !== 'string') return false;
    const actual = normalise(value), expected = normalise(prompt), marker = requestMarker(id);
    if (actual === expected) return true;
    const index = actual.indexOf(marker), end = index + marker.length;
    return index >= 0 && (index === 0 || /\s/.test(actual[index - 1])) &&
      (end === actual.length || /\s/.test(actual[end]));
  }
  root.VideoStudioLogicalText = { logicalText, normalise, requestMarker, receiptMatches };
})(globalThis);
