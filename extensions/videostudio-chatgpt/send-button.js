// Shared predicate for the visible ChatGPT composer button. No broad substring match.
(function(root) {
  function isSendButton(label, testId) {
    return testId === 'send-button' || /^(send|send prompt|send message|gửi)$/i.test(String(label || '').trim());
  }
  // Called after the first click. Retry only a continuously owned, unsent draft;
  // once submission evidence appears, never click again for this request.
  async function confirmSend({received,canRetry,click,wait}) {
    let retryable=true;
    for(let tick=1;tick<=80;tick++) {
      await wait(250);
      if(received())return true;
      if(!canRetry())retryable=false;
      if(retryable&&(tick===20||tick===40))click();
    }
    return received();
  }
  root.VideoStudioSendButton = { isSendButton, confirmSend };
  if (typeof module !== 'undefined' && module.exports) module.exports = { isSendButton, confirmSend };
})(globalThis);
