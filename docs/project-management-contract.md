# Project management and deletion choices

Owner approved 2026-10-30: float × must ask keep-files vs delete-files; projects need delete/archive, archive view, search both views and page sizes10/20/30. Never delete files on initial × or archive.

Backend contract:
- GET `/api/projects?archived=false&q=&page=1&page_size=10`: items + legacy projects + page/page_size/total/total_pages. Allowed sizes10/20/30; legacy no page_size may retain old all-active return. Unicode casefold search project name/idea. Archived/deleted metadata must not reappear from jobs/default synthetic project.
- POST `/api/projects/archive` JSON `{name,archived:true|false}`: archive/restore persistent, no file/job cancellation. POST `/api/projects/delete` JSON `{name,delete_files:false|true,confirm:true}`: reject active main/image jobs; remove project from visible listings persistently, dismiss its terminal jobs; files only with explicit true+confirm. Keep audit/idempotency rows.
- Existing POST `/api/connector/bridges/{root}/jobs/{id}/dismiss` accepts optional JSON `{delete_files:true,confirm:true}`; absent body/false keeps files. Add `{files_deleted,files_preserved}` flags. GET bridge job still attests dismissed:true for worker cleanup.
- Validate ALL deletion targets as strict descendant directories of store.outputs; never delete root/shared runtimes/models/caches. Detect cross-job/scene-export checkpoint asset references outside deletion set and refuse with clear409; caller can choose keep-files. No live file deletions by agents. Avoid partial destructive batch failures; prevalidate and quarantine/rollback as appropriate.

Frontend gallery: main and archive view, matching search,10/20/30 selector,next/previous/page count, archive/restore/delete on cards. Stop click propagation for controls. Delete dialog defaults keep-files and explicitly confirms destructive file removal; backend errors stay visible. Keep existing video workspace behavior. Float dialog lives inside popup and has keep-files/delete-files/cancel choices; invoke worker dismissal only after backend success; preserve lost-response cleanup.

Workers/agents own disjoint source files and coordinate exact payloads. Existing commented prompt guards stay commented. True parallel video execution remains TODO.md.
