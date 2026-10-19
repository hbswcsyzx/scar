# Program25 的旧测试精确迁移

基线 `51a6eb3354eb05f7c02c9ff189239166f2cd4081`；本合同在代码写入前冻结。
新增 `call_effect_expansions` 为新表，旧 1–24 wire 不添加空字段。

## 允许的 24 处字面量替换

1. 旧 14 个 reader 最大版本断言从 24 改 25，文件与上门 reader 列表相同。
   document 原 schema version 的断言保持原值；隔离旧 encoder 的 `==23` 不改。
2. `test_program_session_occupancy_codec.py` 的 reader 最大版本断言从 24 改 25，
   document 仍 24；合计 15 个 reader 迁移。
3. 原四个未来不支持版本参数从 25 改 26，新增上一门 occupancy codec 的未来参数
   同样 25→26；合计 5 项，实际 testcase ID `[25]`→`[26]`，不伪装旧 ID。
4. 四个旧 wire 的 all-current-fields 断言明确排除新表：
   `test_program_exception_match_codec.py`、`test_program_lookup_fallback_codec.py`、
   `test_program_await_acquisition_codec.py`、`test_program_session_occupancy_codec.py`。
   原字段集不变，只将当前 dataclass 新字段从旧 wire 期望中减去。

只允许上述 16 个旧文件共 24 处精确字符串替换。机器账本逐文件保存 before/after，
checker 从该基线的实际 Git 字节重放全部替换；不豁免整文件，不改 fixture 或旧 wire。
原 1956 项义务由 1951 个精确原身份与 5 个明确迁移共同保留。

Program25 新测试独立核新表非空/严格 tag、精确 callee、旧版本字段拒绝，
并由隔离基线 encoder 生成 Program24 原字节 oracle，避免当前 encoder 自证。
Execution8 schema 与字节不变。迁移不代表 F16/P4/P5/M2 完成或优化授权。
