# Stat identity detail and archive file budget

A single stat-format probe actually exited0 in 0.051197913s. Its19,974B trace contains full st_dev major/minor and st_ino matching the live os.fstat result. execve environment stays pointer/count abbreviated and the synthetic environment sentinel is absent. This is one bounded format test, not a LeWM episode or full collector qualification. Original capture/failures/receipts were not modified.

Only explicit process-image V2 capture adds `-e abbrev=!stat,lstat,fstat,newfstatat,statx`. `-v` is not used. Ordinary selection validation accepts precisely this representation expression while still requiring its existing explicit all/control selection. A stat-only trace cannot gain that qualification. Old captures without the option still read normally and gain no missing fields retroactively.

`OSCaptureBudgets.max_files` defaults4096; public trace `--max-archive-files` defaults4096 and can be set explicitly. This transport count includes OS per-TID files, native chunks and collector members. Raw/OS/stored-byte/line/metadata limits are unchanged. Actual original1935members (1585OS) fit4096; original1024 failure remains. Other budgets can still reject independently; file count is not observation completeness.

CLI patch is limited to _trace budget construction and trace-parser argument. Root main's query entrypoints and environment-clearing hunks must be kept by semantic merge; do not replace main cli.py wholesale. Full stat fields enable later exact filesystem association but do not qualify shared FD-table continuity, file contents, physical block IO, device media or ready. No performance sampling/observer expansion was added.
