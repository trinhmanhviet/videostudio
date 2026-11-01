from pathlib import Path
p=Path('static/scene-editor.js')
s=p.read_text(encoding='utf8')
# Keep visual primitives; replace orchestration and old thumbnail UI.
prefix=s[:s.index('  let state = null;')]
prefix=prefix.replace("  document.head.append(style);", """  style.textContent += `
  body.scene-editor-active main{width:80vw;max-width:none;margin-inline:auto;padding-inline:0}
  #viewSceneEditor{max-width:none;width:100%}
  .se-grid{grid-template-columns:repeat(4,minmax(0,1fr));align-items:start}
  .se-card{min-width:0;padding:12px;box-shadow:none}
  .se-card-top{grid-template-columns:minmax(0,1fr) minmax(82px,34%);gap:10px}
  .se-card-img-wrap{min-width:0}.se-provider-radios{padding:8px}
  .se-btn-green{font-size:13px;padding:8px;min-height:40px}
  .se-prompt-input{min-height:100px;box-sizing:border-box;font-size:13px}
  .se-prompt-toggle{min-height:32px}.se-pager{display:flex;justify-content:center;gap:12px;align-items:center;flex-wrap:wrap;margin:18px 0}
  .se-narration{min-height:0}.se-card-status:empty{display:none}
  .se-page-header{z-index:10}.se-history-select{min-width:0}
  @media(max-width:1100px){body.scene-editor-active main{width:94vw}.se-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:600px){body.scene-editor-active main{width:calc(100% - 24px)}.se-grid{grid-template-columns:minmax(0,1fr)}}
  `;
  document.head.append(style);""")
p.write_text(prefix+Path('tmp/editor-paging-tail.js').read_text(encoding='utf8'),encoding='utf8')
p=Path('static/index.html');s=p.read_text(encoding='utf8').replace('20261026-pageview1','20261026-paging2');p.write_text(s,encoding='utf8')
