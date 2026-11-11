from pathlib import Path
p=Path('scripts/test_scene_editor_layout.cjs');s=p.read_text(encoding='utf8');s=s.replace("assert.ok(await firstCard.locator('.se-thumbs-grid').isVisible(), 'Thumbnail grid visible');", "assert.equal(await firstCard.locator('.se-thumbs-grid').count(), 0, 'No thumbnail grid');\n      assert.ok(await firstCard.locator('.se-prompt-toggle').isVisible(), 'Prompt toggle below dropdown');")
p.write_text(s,encoding='utf8')
p=Path('scripts/test_scene_generation_ui.cjs');s=p.read_text(encoding='utf8');s=s.replace("if (u.pathname.includes('/image') || u.pathname === '/original' || u.pathname.startsWith('/candidate'))", "if (u.pathname.includes('/image') || u.pathname === '/original' || u.pathname === '/candidate')")
s=s.replace("      const candidateThumb = page.locator('.se-thumb-wrap', { hasText: 'Ứng viên mới' });\n      await candidateThumb.waitFor();", "      const candidateSelect = page.locator('.se-history-select');\n      await page.waitForFunction(() => !!document.querySelector('option[value=\"candidate:candidate-one\"]'));")
s=s.replace("      await candidateThumb.click();", "      await candidateSelect.selectOption('candidate:candidate-one');")
s=s.replace("            image_sha256: 'candidate'", "            image_sha256: 'candidate',\n            history: [{ id: 'generated-edit', provider: 'chatgpt', created: 1 }]")
p.write_text(s,encoding='utf8')
