"""Reconcile real frozen attempts before sealing; root-only, no target runs."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
assert not (HERE / 'checkpoint.json').exists()


def load(path):
    return json.loads(path.read_text())


def cases(folder):
    rows = tuple(ET.parse(folder / 'junit.xml').iter('testcase'))
    assert not any(row.find(tag) is not None for row in rows for tag in ('failure', 'error', 'skipped'))
    return {(row.get('classname'), row.get('name')) for row in rows}


new, old = (HERE / name for name in ('verified-new', 'verified-regression'))
nr, rr = load(new / 'result.json'), load(old / 'result.json')
assert nr['returncode'] == rr['returncode'] == 0
assert nr['source_sha256_after'] == rr['source_sha256_after']
new_cases, old_cases = cases(new), cases(old)
assert len(new_cases) == 30 and len(old_cases) == 302 and not new_cases & old_cases
prior = {tuple(row) for row in load(HERE.parent / 'model_value_source_consumers/case-catalog.json')['identities']}
current, catalog = new_cases | old_cases, prior | new_cases | old_cases
summary = {'new': len(new_cases), 'prior_affected': len(old_cases), 'current': len(current),
    'prior_catalog': len(prior), 'prior_retested': len(current & prior),
    'additional_preexisting': len(old_cases - prior), 'known_catalog': len(catalog),
    'source_files': nr['source_count'], 'source_sha256': nr['source_sha256_after'],
    'new_seconds': nr['duration_seconds'], 'regression_seconds': rr['duration_seconds']}
(HERE / 'results-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
sha = summary['source_sha256']
text = f'''# F19完整异步关闭链：限定结构验收

状态：**Verified，限定于所供模型结构**。root自主验收，无需用户逐门批准。
基线`c02e973`；最终922输入指纹`{sha}`，两次运行前后稳定。

## 实测与原单位

| 冻结运行 | 实际结果 | wrapper秒数 |
| --- | --- | --- |
| verified-new | 30 PASS，0失败/跳过 | {nr['duration_seconds']:.6f} |
| verified-regression | 26模块302 PASS，0失败/跳过 | {rr['duration_seconds']:.6f} |

这是两次同源码focused运行的332项并集，不是一次full suite或LeWM benchmark。

| 原F19完整单位 | 本次证据 |
| --- | --- |
| 真Return/Raise→F→新Throw/Close | 四格公开history、准确own N/R、caller当前state；删身份回到None；sameR retry独立 |
| graceful close | GE进入真实finally/C1→AWAIT/HOLD→同R/本次S恢复；Return/GE/普通异常三出口及两层回复 |
| illegal close-yield | 构造错误前R COMPLETE而B仍Suspend；六driver调用/三body段/五Create；sameR拒绝、新Close/Throw无Drive、同B NEXT恢复finally→真实F |
| 交叉义务 | 错HOLD/提前release拒绝；删adapter/绑定保原源分母；错matcher/bool、构造来源缺证；缺input/bool/packet/body outcome不借完整兄弟；tiny保hosts/ports/cursor |

每个actual stage额外核准确RequestCreate ownN→本call request；resume/NEXT送值核
当次caller sent→实际Drive输入。真正terminal后的窄release不宣称物理free。

## 模型改变

- Implemented：三处统一ASYNC_YIELD→COMPLETE；AWAIT仍HOLD，F仍仅由真Return/Raise。
- Implemented：原packet→matcher/bool/True边→fresh constructor/own N/R→packet/host的
  有界派生收据。每段copy独立核；新旧packet不union，旧CLOSE输入合同不变。
- Verified：公开静态`handled_completion`及既有dynamic drive查询接通准确原ports/
  actual occurrences；来源缺采、重复site、预算截断不升级True。
- Rejected：准备期免费另开百万预算、按操作名推异常类别、用fresh packet非copy
  直接判错、缺独立期望却伪造known contradiction、删denotation后仍要求终结证明。

所有新派生工作在query shared预算；INVOKE全槽、adapter、原route、绑定扫描计费。
不跨query缓存证明。已知False在缺constructor或截断后仍保留；未查部分不授True。

## 证据与版本边界

保留全部首败源码/JUnit/日志。独立审查见归档`independent-review.json`：A确认最后
槽扫描费用阻断关闭，以最终新/旧运行通过为接受条件；B/C原审查与修正逐项保留。
Program27/Execution8、原copy语义及所有既有tests/fixtures字节保持。

原已知focused目录{len(prior)}义务全部保留，本次重验其中{len(current & prior)}；
新增30项，另发现{len(old_cases - prior)}个既有目录外义务，当前已知目录{len(catalog)}。
未重跑整个目录或整个仓库。两次运行都不是P4组件/full或P5/M2验收。

Observed：本次是所供图与capture测试；旧CPython3.14.7固定源码、22调用和两编译
观察复用，本次native目标执行0次。初始S=None与未选ITER边界保持；不宣称完整
native driver。source/native/runtime identity、自动whole-LeWM恢复及变换权限未证。
没有新增detector/backend，没有新的LeWM优化或加速比。

## 合账与下一阶段

F19在上述条件下限定接受：原16行目前10接受、6开放；await A–H已有结论保持。
仍开放F20/F22/F24/X25/X26/X27、P4 component/frozen-full、P5，以及M2原113构造/
196字段。**整个第一阶段尚未完成。**

下一门按[M1_YIELD_FROM_INITIAL_PLAN.md](M1_YIELD_FROM_INITIAL_PLAN.md)先做F20同一
父实例首次委托的六路，复用现core、原InitialAdvance和consumer ledger；合法
完整图出现真实查询反例后才决定薄产品修正，不新增来源工具箱或优化后端。
'''
(ROOT / 'docs/M1_ASYNC_CLOSE_CHAINS_ACCEPTANCE.md').write_text(text)
updates = {
 'docs/MODEL.md': '''## Async close chains and handler-produced completions (2026-10-20)

Five canonical entities remain unchanged. A fresh handler packet has control
dependence on the original packet; it is not that packet's copy. The
[new public API](M1_ASYNC_CLOSE_CHAINS_API.md) separates original copy segments,
matcher own bool/selected edges, constructor own N/R and the current host packet.
Static and actual views share query budgets and keep native interpretation,
object identity and transformation authority separate.

[Conditional F19 acceptance](M1_ASYNC_CLOSE_CHAINS_ACCEPTANCE.md): 30 new and302
affected prior tests pass on the same922 inputs. All prior tests/fixtures,
original copy semantics and Program27/Execution8 stay unchanged. Original16
rows are now10 accepted/6 open; P4/full/P5/M2 original113/196 and complete M0–M2
remain open. [Next F20](M1_YIELD_FROM_INITIAL_PLAN.md) is a complete first
delegation inside one parent, not another source helper or optimization backend.
Automatic whole-LeWM recovery and new speedup remain unverified. Older entries
below preserve the history and are superseded by this status.

''',
 'docs/ROADMAP.md': '''> **F19 complete-chain conditional acceptance (2026-10-20):**
> [Report](M1_ASYNC_CLOSE_CHAINS_ACCEPTANCE.md):30 new+302 affected prior PASS,
> 922 stable inputs across two frozen runs. Terminal/new-request, graceful
> finally/AWAIT and illegal close-yield/retry/finalization chains are joined.
> Fresh reply construction is a guarded control dependency, not packet copy.
> Ten of the original16 rows are conditionally accepted; six remain open, plus
> P4 component/full/P5/M2 original113/196. Whole M0–M2 is incomplete. No new
> backend, automatic LeWM recovery or speedup. [Next F20 plan](M1_YIELD_FROM_INITIAL_PLAN.md).
> Earlier status entries below are retained as history.

''',
 'docs/FIRST_STAGE_COMPLETION_MATRIX.md': '''最新F19完整链（2026-10-20）：[限定验收](M1_ASYNC_CLOSE_CHAINS_ACCEPTANCE.md)
在相同922输入上通过30新项+302直接受影响既有项，两次冻结运行并集332。
原三完整单位和缺采/预算/release反例贯通，原copy、schema及旧tests/fixtures保持。
原16行现10限定接受/6开放；原F20/F22/F24/X25/X26/X27、P4 component/full、P5、
M2原113/196及完整第一阶段仍开放。没有自动LeWM恢复/变换或新加速结论。
[下一门F20](M1_YIELD_FROM_INITIAL_PLAN.md)已按完整父链规划，用户无需逐门验收。
以下旧状态条目保留为历史，以本条为当前状态。

''',
 'docs/WHOLE_PROGRAM_MODEL_PLAN.md': '''2026-10-20 当前状态：[F19完整链限定验收](M1_ASYNC_CLOSE_CHAINS_ACCEPTANCE.md)
在相同922输入上通过30新项+302受影响既有项；三完整单位及交叉反例已接通。
原16行现10限定接受/6开放；仍须F20/F22/F24/X25/X26/X27、P4 component/full、
P5与M2原113/196。M0–M2整阶段未完；自动whole-LeWM恢复/变换及加速未证。
下一门按[F20六路父链计划](M1_YIELD_FROM_INITIAL_PLAN.md)，先供合法完整图，
不新增detector/backend。以下更早进展保留为历史。

'''}
for filename, block in updates.items():
    path = ROOT / filename
    heading, body = path.read_text().split('\n\n', 1)
    path.write_text(heading + '\n\n' + block + body)
with (ROOT / 'docs/M1_ASYNC_CLOSE_CHAINS_PROGRESS.md').open('a') as out:
    out.write(f'\n最终旧回归已完成：302 PASS，570.71秒pytest /{rr["duration_seconds"]:.6f}秒wrapper，'
              f'同922/{sha}稳定。与新30共332项，实际合账/边界见限定验收报告；原阶段分母不缩减。\n')
(HERE / 'README.md').write_text(f'''# F19 async close chains

**Verified conditional supplied-model structure**, not automatic source/native
recovery or a performance result. Base c02e973; source `{sha}` (922 inputs).

- verified-new:30 PASS, {nr['duration_seconds']:.6f}s wrapper.
- verified-regression:302 PASS/26 modules, {rr['duration_seconds']:.6f}s wrapper.
- Union:332; retained prior catalog2325, current known catalog{len(catalog)}.
- Program27/Execution8 and all previous test/fixture bytes unchanged.
- Original16 rows:10 conditionally accepted,6 open. P4/full/P5/M2 and first stage open.

See docs/M1_ASYNC_CLOSE_CHAINS_ACCEPTANCE.md and API/plan/progress for exact scope.
All attempts include original commands, input hashes, changed source snapshots,
stdout/stderr and JUnit; failed evidence is immutable. Native target runs this
gate:0; old22-call probe/reference source reused. No new LeWM speedup.

Root-only seal/check after reports: `PYTHONPATH=. python {HERE.relative_to(ROOT)}/seal_gate.py`
and the same command with `--check`. No tests or target execution run by the seal.
''')
print(json.dumps(summary))
