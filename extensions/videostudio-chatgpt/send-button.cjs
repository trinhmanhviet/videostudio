// Shared predicate for the visible ChatGPT composer button. No broad substring match.
(function(root) {
  function isSendButton(label, testId) {
    return testId === 'send-button' || /^(send|send prompt|send message|gửi)$/i.test(String(label || '').trim());
  }
  root.VideoStudioSendButton = { isSendButton };
  if (typeof module !== 'undefined' && module.exports) module.exports = { isSendButton };
})(globalThis);
