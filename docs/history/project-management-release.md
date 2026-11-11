# Project management 0.3.6

Implemented owner-approved delete choices in the float, project delete/archive/restore, search in active/archive views, and pagination10/20/30. Deletion defaults keep-files and final confirmation is required. File removal only targets validated dedicated output directories; symlinks/junctions, output aliases and external job/scene references refuse with409 so the owner can keep files. Quarantine staging rolls back on transaction/staging failure. Purge failure reports cleanup_pending visibly; automatic quarantine cleanup is not claimed.

Separate lifecycle metadata preserves old projects table shape and immutable job receipts. Deleted names cannot be recreated/resumed via old tabs; Store, derived jobs, retries/resume, scene exports and scene-image start/resume/recovery have guards. Archive is reversible and changes visibility only. Root bridge smoke survives dismissal/deletion of its legacy video.

Evidence: full Python385 tests OK (`data/projects-python-tests.txt`); Node82 tests OK (`data/projects-node-tests.txt`); project UI tests320/1280 and job recovery390/1280 pass; float manager27 fixtures and VM4 pass. Independent review found stale-editor retirement holes; those were fixed and tested. No real project or media deletion was performed by the agent.

Owner explicitly chose stopping video42416ac4-0877-4c9d-9a13-7d7f00435d3d and updating immediately. Cancel was requested through API; job settled failed at images with cancel=1 and no active jobs remained. Plan/research/script/speech checkpoints and all output files were kept. Idle-only server restart completed (PID4560), and live GET active/archive pages verified new pagination metadata at10/20 items. No real files/projects were deleted by the agent. Reload extension0.3.6 and Studio to use the deployed features.

Commented prompt guards remain commented; true parallel video execution remains TODO.md.
