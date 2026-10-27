# D2.1 publication：独立只读集成复审

2026-10-18；结论：**本轮有限范围通过，未发现需阻断 D2.1 的实质错放、错拒或 metadata 崩溃。**
没有修改跟踪文件/旧证据；没有运行 pytest、full、LeWM 模型、GPU、git 或网络操作。
只运行两次下述 conda lewm 小脚本：首跑九项中的八项完成，另一次仅补首跑构造失败的一项。
这不是完整 D2 签核，也不代表自动导入/真实 source/runtime 对应已成立。

## 1. 实际审查快照

以下均为本轮实际读取及探针记录的 SHA256；不是仅引用父任务测试数量。

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/program/lifecycle_validation.py` | `219f68e0a0de9ef136166dad69303387349c6527da67331c50cdcd3fb692cae8` |
| `scar/ir/program/lifecycle.py` | `a4f514f2bd7481a0f5a674cda0c82112a505b0ecde9a4baae501c6019daf044c` |
| `scar/ir/program/validation.py` | `12c05a4abd25f99b6506a10941c3f0d6a94c637d508d37c61ed6490b189c745a` |
| `scar/ir/program/model.py` | `a79394bcfbc012edde27b0e7c42c744f3bee010a1ce54351cf2a4f71ad11db01` |
| `tests/fixtures/program_publication_graphs.py` | `5d476228103db4246652443999edcb94e53dbfa1d16ed4c496bb397f620640b0` |
| `tests/unit/test_program_publication_graph.py` | `13a13691c86cb3b01df2f043351f49ffd08199362e6c2c380bc005a0889d9a7b` |

比较合同为 `docs/M1_DRIVER_LIFECYCLE_CONTRACT.md` 的 D2.1 部分，未修改它。
其 F/P/T 设计不属于本轮产品代码所实现的能力，不从先前 owner_flow 设计探针授产品完成结论。

## 2. 接线及机械关系

- `validation.py:653–681`：先通过 C0/C1/body/D1，再运行 publication；schema/core/D1 的错误不会进入
  publication 内部的直接 lookup。`validate()` 的公开路径先做递归 schema 检查；该 helper 自身不是绕过前置门的独立校验 API。
- `lifecycle.py:24–57`：三种 frozen/slots records，exact IDs；嵌套 `DriveOutcomeRef` 重验；没有可写 phase、session 或“已验证”位。
  `model.py:809–834`：两表 exact records/tuple、唯一键及跨现有动作角色冲突检查。
- `lifecycle_validation.py:31–72,119–124`：scope 必须有 DriverInterface；每个 `(drive,source)` 必须对应该
  driver 的实际 Drive successor，其私有 landing 首操作恰是一个 commit。覆盖按实际边派生，不接受闲置 source 名单。
- `:74–86`：owner 是 commit 自有 Reference Use，必须为 Drive.instance 原 Value，或该 source 边的独立
  owned forward Use→formal；produced payload 不作同身份。两份 same-owner formal 不被强制合成唯一 carrier。
- `:88–117`：无 callback 的声明 shape，纯普通 CONTROL/READ/WRITE、complete，无 call/term/completion。
  StateAccess 只在 L 内、WHOLE READ/RW、非 overwrite，至少一个真实写；结果与真实 after 集合相等，owned Uses 无隐藏项。
  未访问 L 域不必添加假 READ 或 after；W 可严格小于 L，L 可严格小于 D。精确 reference 若提供仍受 core alias 检查；coarse 不被捏造精化。
- `validation.py:453–515`：当前 state、location 对应、重复访问、after producer 与完整 alias 仍由 core 检查。
  Publication 并不仅因有一个新 StateVersion 就证明 native body 字段确实更新。

终结/暂停来自已验证真实 source 的类型，不需要可写 phase。该模块没有实现 F/P/T 数据流，
也没有 CreatedCloseTest、NoBodyFinish、SessionUpdate 或 TerminalFrameRelease 的产品表/资格判定。

## 3. 有理由的有限反例与合法组合

命令均在 `/tmp/scar-structured-model-280qf4mi`，明确执行 `source /home/zyf/miniconda3/etc/profile.d/conda.sh`
及 `conda activate lewm`，`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`；实际解释器为
`/home/zyf/miniconda3/envs/lewm/bin/python`，Python 3.14.7。
精确命令分别保存在同目录 `.command.txt`，原始 stdout/stderr、JSON、时间全部保留。

| 风险/机制 | 实际结果 |
| --- | --- |
| C1 cleanup+INVOKE 的 Return/Raise 两个实际 source，各自首 commit | issues 空 |
| 两个 source 的 commit.outcome 对调，数量与 source 集合仍一致 | 拒绝 `publication_landing`、`publication_owner`；不靠单纯集合覆盖放过 |
| 同一个 owner 沿两个独立 owned Uses 送入两个 Reference formals，commit 消费第二个，首个不用 | issues 空；没有误加唯一 owner carrier 要求 |
| commit metadata.instance 引用另一个操作（Drive）自有 UseID | 拒绝 `publication_owner`、`publication_uses`，无 lookup 崩溃 |
| commit.operation 是不存在的 OperationID | 拒绝 `publication_operation` 与 `publication_coverage` |
| 绕构造器篡改 nested outcome.source 为字符串 | 返回 `schema`，无异常 |
| 绕构造器篡改 scope.region 为字符串 | 返回 `schema`，无异常 |
| 绕构造器重复两条 commit metadata | 返回 `schema`，无异常 |
| 三个 L 域，仅一个实际 RW；移除另两个 READ access 及其 owned Uses，保留正常当前 state 转发 | 补跑 issues 空；W⊊L 合法 |

没有把校验器在公开输入上未出现的崩溃说成已复现问题。
跨 source 对调后的附加 owner 错误来自它已不在所引用 landing；首 landing 错误已足以拒绝。

## 4. 首败记录与补跑界限

首脚本 `integration_review_probe.py`：SHA256
`41c744de3a77dde9a0ba7f9daf1c79b7d54d143e756f5fa973703d871f6912aa`。
首跑 exit 1、0.42 秒：八项得到预期结果；省略 READ 的工厂误写 `write, read = commit.accesses`，
fixture 实为三域，先抛 `ValueError: too many values to unpack (expected 2, got 3)`，没有调用到 validate。
这是**审查脚本错误**，不是产品失败；原脚本、JSON、log 不覆盖。
首 log/JSON SHA256：`a056a335a07c27aba8331dd68265d40a5de5f8bfa87d9d7d07fa2dc1be84852c`。

补跑 `unaccessed_domain_attempt2.py` 只按实际 AccessMode 修正这一构造，未重跑已完成的八项：
SHA256 `4a0ea36806c512be1c1b779b850a32d18ed219b1561cd3cc6bfcb043dfef089f`；
exit 0、0.36 秒，L=3、W=1、移除 READ=2，issues 空；validator SHA 与首跑一致。
补跑 log/JSON SHA256：`eca7bf19136c958b406c46df22b92e7077db694b7e281874c20717706a3cbb05`。
不能把首跑说成九项全通过，也不将修正工厂当作产品修复。

## 5. fixture、声明与 source/runtime 的界限

`test_program_publication_graph.py:30–58` 覆盖 direct/forward、Suspend/Return/Raise、coarse、W⊊L、L⊊D；
`:61–93` 包含多 source、空/混合发散 frontier、D1 opt-in 与缺覆盖。上述是本轮读到的冻结测试设计，
未在本轮重跑；本轮额外执行的具体情形仅§3所列，不拿父任务 suite 数当模型覆盖率。
空 frontier 的声明义务确实按实际 successor 枚举为零；不推出 dead、total 或实际执行结束。

这些 fixtures 是手写 IR，用来检查 canonical source/Use/CFG/state 的声明关系，不是 Python 自动导入产物。
当前代码不证明实际 native owner 的身份/lifetime、publication 对应真实字段/selector、无 callback 事实、
source/profile 适用、运行期 admission、session occupancy、frame references held/free 或任何优化权限。
F/P/T 的未来求解、no-body/family/drop/source-runtime 验收仍独立；本复审只通过所读 D2.1 接线范围。
