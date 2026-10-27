# VideoStudio ChatGPT Bridge (isolated, text only)

This unpacked Chrome MV3 extension is **separate from StoryForge**. It uses a normally launched Chrome profile, not `--remote-debugging-port` or `--enable-automation`. It never reads cookies or calls ChatGPT private APIs. The person signs in and handles any login/verification in Chrome. Flow/Comfy image generation remains separate.

## Start after installing in Chrome

1. Ensure no VideoStudio job is queued/running. Start VideoStudio with `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -TextTransport extension` from `D:\Projects\videostudio`. This does not start the CDP daemon. If port 8877 is already occupied by the old server, stop/restart only the owned idle server with the script's `-RestartOwnServer` switch; never kill all Chrome processes.
2. In the **same ordinary Chrome profile where ChatGPT is signed in**, open `chrome://extensions`, enable Developer mode and choose **Load unpacked** for `D:\Projects\videostudio\extensions\videostudio-chatgpt`. Do not install the StoryForge extension into the same Studio tab.
3. Open `http://localhost:8877/` (not 127.0.0.1). In the bottom-right VideoStudio bridge panel click **Start**. The page creates a new local connector scope and navigates to its production URL. Click **Start** again on that production page. The bridge opens an owned ChatGPT tab; do not use that tab for other conversations.
4. Click **Kiểm tra chữ** exactly once. The extension sends one synthetic JSON question and imports its exact receipt. Wait for `Imported ...`, then click **Kiểm tra lại** in VideoStudio. Only if all preflight checks pass should you create a video in this production tab. Other local requirements (voices, Comfy, music) still apply.

The bridge polls for text exchanges in the scoped Studio tab, records dispatch intent before sending, verifies an exact visible user-turn marker, and imports a versioned immutable response. A tab reload, changed DOM, timeout or uncertain delivery **does not automatically resend**. Stop disables polling; it does not close the ChatGPT tab. If an exchange is uncertain, inspect it before doing anything else; do not click Start to create a new session to force a retry. A completed receipt unlocks the next exchange in the same session. Keep the production Studio tab open during the job.

## Limits and verification

`node --test tests/*.test.mjs` runs fixture-only tests. The current ChatGPT DOM is volatile, so **live end-to-end operation is not yet verified** until the owner loads the extension and supervises the one-question smoke. This bridge does not attest ChatGPT High or live Web Search; factual content needs separate verification. It does not create images itself. There is no headless/unattended/tab-close guarantee.
