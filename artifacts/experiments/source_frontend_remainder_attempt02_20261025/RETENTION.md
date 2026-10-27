# Retention

全部65 actual terminal/results、返回metadata、完整plan、65-row accounting及原失败均保留。
Git小文件建议清单在stage-small-files.txt/.json；每项<=1MB，没有Git操作。
12个source-program5.json.gz全部local-only，包含一个不足1MB的图也不自动发布；
原URI及完整physical/decoded SHA/bytes在successful-programs.json。stored SHA已核，未解图。
大attempts.jsonl完整local-only且有SHA；65份actual result.json逐份保留可版本化，
started/ready等重复metadata仍本机保留。runtime payload没有vendor副本，保freeze receipts。
本报告和存储清单不增加准入资格，12图待以846严格parent批量ADD及公共reader；
当前runtime843、全phase1 OPEN、总decoded+stored I/O计费OPEN。
