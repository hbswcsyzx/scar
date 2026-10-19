# D4冻结前的有限只读审查

基线69ed9e3。沿原完整A–H/16组，三路只读复核记录于
docs/M1_AWAIT_OUTCOME_CONTINUATION.md。本轮B具体复核D4草稿，未执行或写入。

冻结前指出且root补齐的两项：

- source自身失败不能依赖展开stage或成功advance。parent Get own RAISE及native
  wrapper constructor own RAISE须从原scope subject/控制边保留；failure key改为
  原scope/source operation/stage operation/edge，可选acquisition ref只作属性。
- 不能假定每个操作都有N/R两腿。保原operation实际存在的全部completion legs，
  ordinary/onlyRAISE不补假腿。

B确认上述修订后可冻结；这不是完整A–H/16组验收。D4_SHA为
2dd28790c51e33219750a5cbf22943100cd47bcce0bc1b914445431bd03ec273。

原may库存后必须逐case must/correlate；Value→Use索引按每个consumer位置fresh
membership筛，不能用全位置并集。跨region保原actual边界，再准确formal展开；
unknown may不是空集合。budget1的关联总数若未枚举完必须None/cursor，而原
Drive successor总数单列。所有native/runtime/value/变换权限仍False。

后续新源码的有限复核和运行结果另记，不把本审查当成尚未执行的测试结果。
