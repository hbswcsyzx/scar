# Source inventory 实施报告（有限范围）

Implemented；专属 CPU tests Verified。不是全 writer 捕获、runtime/source 认证或完整P/V/M0–M2验收。

## 修改与接口

仅 owned 四文件：execution/inventory.py、trace/normalize_v2.py（io import + normalize_bytes入口 + export，原 normalize_trace/normalize_records 行为保持）、tests/unit/test_execution_inventory.py、tests/fixtures/execution_inventory_sources.py。

- InventoryResolver(ExternalSnapshots, max_bytes=67108864,max_lines=1000000,max_line_bytes=4194304,max_artifacts=256).resolve(manifest,index)。InventoryResolution exact frozen fields sources/gaps/format_replayed；原 ResolvedSource/RawInventoryRecord 字段按 root 合同；不新增 producer/state/writer表。
- CaptureManifest/NormalizationIndex封闭schema和tagged projection、ProviderArtifact plain四字段、SourceVersion和tagged ProviderRunScope/missing 编码按 design/inventory-api.md。
- manifest先枚举原stream key/rawArtifact，index恰好对应；缺index/原bytes/预算时仍输出所有已知 source placeholders，pending source不会因执行表删行消失。根manifest不可读或超预算时无法知道未知key，只报明确root gap，绝不当empty world。
- source artifact只走root提供的 snapshots.payload；输入hash/size/wrongtype由shared snapshot检验；URI不读。metadata/source/index/schema/FK/投影已知矛盾ValueError；missing/unsupportedrecipe/budget保留gap。
- implementation fingerprint只读固定已安装normalize_v2.__file__，已由root明确授权；从不读取/执行recipe.path。unknown fingerprint/profile/version是gap，不执行任意历史/provider代码。
- normalize_bytes是纯offline数据投影，BytesIO.readline只按LF，预算前读有界行；保留blank、invalid JSON、末行无LF及原bytes hashes；不经normalize_records重新dump。
- 严格解码现IRBundle，重放完整bundle与coverage的canonical内容比较；不只比较counts/coverage.normalized refs。三个component artifacts由原strict bundle派生。
- build_inventory仅封存调用者实际提供raw bytes；不从work/contribution生成sources、不认证完整run。每源label/namespace为inventory:+key；原metadata.scar_native_result保留在detached RawInventoryRecord.payload。
- collector已报告drop/error/io_failed、缺loss字段、未封窗口、未知scope和foreign alias写完整性都保留gap。format_replayed可True但capture仍unverified，source_runtime_verified/transformation_authorized恒False。

## 实际定向测试

均source conda.sh + conda activate lewm；PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.。命令 python -m pytest -q tests/unit/test_execution_inventory.py；每attempt保存argv/cwd/env/stdout/stderr/result和source before/after hashes。

- attempt001：25 passed / 0.66s / exit0，source前后hash一致；有1个测试bytes字面量未转义\u的SyntaxWarning。原始输出保留。
- 修为raw bytes literal，不改其bytes语义；有界自查补positive recipe version与metadata type/window/loss字段规则，并加三个对应negative cases。
- attempt002：28 passed / 0.57s / exit0，无warning；source前后hash一致；最终版本。

覆盖原始非canonical/LF物理行、原native_result metadata、derived component hashes、closed schemas、删/重复/错stream、改完整projection、缺raw/bundle/coverage/index、累积lines/bytes/artifact预算、unsupportedrecipe、显式unresolved、collector缺采、known process冲突、presentNone/digest错、duplicateJSON/NaN、禁止caller writer tuple及strict normalize_bytes limits。

未跑full/GPU/LeWM/target capture；未安装、提交或修改其它owner文件。root负责source→D/production组合、snapshot.include、全门回归；本报告不引用这些尚未收到的结果。

## 最终SHA256

- `scar/ir/execution/inventory.py`: `c3595f92a5b4bd6813e032219f85f0ccbbaaa83703f23712be5b44b9d12a0511`
- `scar/trace/normalize_v2.py`: `e9a2987481911a1cf51dc3d793d3a49d1e07740a4304967c8618d9e302c8bffb`
- `tests/unit/test_execution_inventory.py`: `7eaad265f7224385d22c5fd698abcd4972859cae30453fc99e03b3664f5dfcd9`
- `tests/fixtures/execution_inventory_sources.py`: `0796c3fcc9764960964859b4d4eae316a51a93c66a85009344cd8c4d49ca3423`
