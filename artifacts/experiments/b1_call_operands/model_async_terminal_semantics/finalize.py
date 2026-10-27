"""Bind completed root receipts to the original F18 verdict, no test execution."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
result = json.loads((HERE / 'verified-current/result.json').read_text())
sources = json.loads((HERE / 'verified-current/sources.after.json').read_text())
source_digest, current_sources = fingerprint()
assert result['returncode'] == 0 and result['source_unchanged']
assert result['source_sha256_before'] == result['source_sha256_after'] == source_digest
assert current_sources == sources and len(sources) == 899
cases = tuple(ET.parse(HERE / 'verified-current/junit.xml').iter('testcase'))
old = tuple(ET.parse(HERE.parent / 'model_async_initial_control/verified-final/junit.xml').iter('testcase'))
identities = {(row.get('classname'), row.get('name')) for row in cases}
prior = {(row.get('classname'), row.get('name')) for row in old}
assert len(identities) == len(cases) == 2104
assert len(prior) == 2058 and prior <= identities and len(identities - prior) == 46
assert not any(row.find(tag) is not None for row in cases for tag in ('failure', 'error', 'skipped'))
family = json.loads((HERE / 'family-baseline.json').read_text())
clauses = json.loads((HERE / 'f18-clause-map.json').read_text())['clauses']
review = {'status': 'CONDITIONAL_SUPPLIED_MODEL_ACCEPTANCE',
    'source_sha256': source_digest,
    'original_requirements': 'Original F18: natural completion versus active termination exception and consumers',
    'closed_before': family['closed'], 'newly_closed': ['F18'],
    'closed_after': sorted([*family['closed'], 'F18']),
    'remaining_families': family['remaining'].copy(),
    'clauses': clauses, 'acceptance_document': 'docs/M1_ASYNC_TERMINAL_ACCEPTANCE.md',
    'independent_review': 'independent-review.json',
    'original_A_H': family['original_A_H'], 'not_new_requirements': True,
    'automatic_source_recovery': False, 'source_runtime_verified': False,
    'transformation_authorized': False, 'p4_complete': False, 'p5_complete': False,
    'm0_m2_complete': False, 'tests_started': 0,
    'retained_unknown_boundaries': [
        'Supplied source/provider/native ports do not prove correspondence to real binary execution',
        'Compiler/source fingerprint diagnostics do not prove module purity or authorize imports/rewrites',
        'Unknown input/physical value identity and missing occurrence/state remain independent gaps',
        'OriginalF19 closed/athrow/aclose/failure continuations and six other original families remain open']}
review['remaining_families'].pop('F18')
assert len(review['closed_after']) == 9 and len(review['remaining_families']) == 7
review_path = HERE / 'f18-review.json'
assert not review_path.exists()
review_path.write_text(json.dumps(review, indent=2) + '\n')
expectations_path = HERE / 'gate-expectations.json'
expectations = json.loads(expectations_path.read_text())
expectations['attempts']['verified-current'] = [2104, 0, 0, 0, 899]
expectations_path.write_text(json.dumps(expectations, indent=2) + '\n')
acceptance = ROOT / 'docs/M1_ASYNC_TERMINAL_ACCEPTANCE.md'
text = acceptance.read_text()
text = text.replace('**待最终同源 affected 回归完成与 checkpoint 核验。**',
    '**最终同源 affected 回归通过；仅原 F18 supplied-model 条件性结构验收。**')
text = text.replace('最终新增46项已定向全部通过；原2058项的统一回归正在运行。最终数字、稳定\n指纹、持续时间和原身份对账以本报告收门更新及机器checkpoint为准。',
    f'最终 verified-current 实测 **2104 PASS，0 FAIL/ERROR/SKIP**：原2058精确身份全部\n保留，新46 = 7库存/来源 + 8静态 + 22源编译 + 9动态。899源前后稳定指纹\n`{source_digest}`。\npytest {ET.parse(HERE / "verified-current/junit.xml").find("testsuite").get("time")}s，wrapper {result["duration_seconds"]:.6f}s。\nProgram26/Execution8及所有旧test/fixture字节保持，无旧case身份迁移。\n机器归档 original-acceptance/checkpoint 逐条核原要求、所有实际尝试和独立审查。')
text = text.replace('F18 若最终同源验收通过，原九族条件性接受，', 'F18 最终同源验收通过，原九族条件性接受，')
text += ('\n源编译 query 未执行所分析目标模块；native-probe 的22次自建fixture实际调用\n单独归属。Observed 是本机返回/编译结果，Implemented 是本轮原端口连接，Verified\n仅限上述同源结构用例。Rejected 的建模前提和所有首败均保留；未提出新的优化结论。\n')
acceptance.write_text(text)
progress = ROOT / 'docs/M1_ASYNC_TERMINAL_PROGRESS.md'
text = progress.read_text()
text = text.replace('**新增46项定向已通过，最终同源 affected 回归运行中；尚不授 F18/F19 验收。**',
    '**最终2104项 affected 通过，原F18条件性结构接受；F19及完整阶段仍开放。**')
text = text.replace('| verified-current | 运行中 | 最终旧2058精确身份+新46；结果不得由前缀推断 |',
    '| verified-current | 2104 PASS / 0 FAIL/ERROR/SKIP，899源稳定 | 原2058精确身份全部保留，新46；这是affected门，非组件/冻结full |')
text += (f'\n## 最终收门\n\n最终 verified-current 2104项全部通过，wrapper {result["duration_seconds"]:.6f}s，\n'
    f'899稳定源 `{source_digest}`；无旧test/fixture字节修改或case迁移。\n'
    '原九族条件性接受，F19/F20/F22/F24/X25/X26/X27七族、P4 component/full、\n'
    'P5/M2原113/196和第一阶段仍开放。保护仓库由checkpoint复核，正常commit/push\n'
    '后核远端完整SHA、0/0和干净。LeWM自动建模/可信变换/加速比均未获得新证明。\n')
progress.write_text(text)
print(json.dumps({'status': review['status'], 'source_sha256': source_digest,
    'cases': len(cases), 'new_cases': 46, 'old_exact_retained': len(prior),
    'wrapper_seconds': result['duration_seconds'], 'tests_started': 0}, indent=2))
