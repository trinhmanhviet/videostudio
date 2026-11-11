# Version 0.3.5

- Alarm inspects existing pending ChatGPT requests read-only every25seconds, with errors isolated per session. Prior auth/mode errors no longer suppress reading an already completed matching reply. No automatic resending, CAPTCHA/login automation or retry-budget reset is introduced by this inspection.
- Studio also checks failed textual stages. When the same response is recovered and successfully imported, it can resume a connector/network-failed textual stage once per request per page session. It does not retry GPU/content-quality failures based only on a timer.
- Requested seconds are a planning estimate. Measured narration drives fresh video, image/music timing, render and verification; existing verified soundtracks/revisions retain their effective timeline. Five-second and multi-minute deviations no longer cause automatic script rewrites or forced voice speed changes. Structural/finite/media validity checks remain.
- × on completed/failed sessions persistently dismisses exactly that bridge-owned job and releases its current/retained owned tabs and local waiting. Pending per-scene tasks are cancelled; completed media and immutable audit records remain on disk. Shared server/browser/GPU processes are not killed. Owner deletion preference was asked; default is keep files. A root connection test remains available after dismissal of a legacy root video.
- The earlier prompt verification/repair and pre-Send comparison guards remain COMMENTED per owner's request. This release does not reactivate them.

Update: idle-only backend restart, reload extension0.3.5 and F5 Studio. True parallel video execution remains open in TODO.md.
