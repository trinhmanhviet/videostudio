// Read ProseMirror's logical paragraphs without innerText's extra layout newlines.
(function (root) {
  function logicalText(node) {
    if (!node) return '';
    if (node.tagName === 'TEXTAREA') return node.value || '';
    const children = Array.from(node.children || []);
    if (children.length && children.every(child => child.tagName === 'P')) {
      return children.map(child => child.innerText ?? child.textContent ?? '').join('\n');
    }
    return node.innerText ?? node.textContent ?? '';
  }
  root.VideoStudioLogicalText = { logicalText };
})(globalThis);
