# 精确资格检查的有限独立复核

2026-10-19；A、B、C只读/写指定新fixtures/tests，未执行Python、pytest、probe、
compile或commit。所有执行由root串行完成，执行期间所有源码作者冻结。
本记录只涵盖D3资格路径，不宣称完整await A–H或原16组通过。

## 合同判断

A `/root/cleanup_forward_review` 与B `/root/value_resource_review` 独立支持：
固定准确资格检查能使坏输入的接受腿在声明合同条件下不可行；静态有效性不应
随一次capture的分支选择改变。原CFG两腿必须保留；实际错误接受才报矛盾。
无检查、绕过或错bool不能因此豁免，未知来源不能推不可行。
该解释冲突及唯一旧测试输入迁移均已显式保存，不把旧oracle冲突冒作新图缺陷。

## B实际指出并收敛的风险

1. 无关检查的unknown输入先进入保护结论，可能把已知原错误洗成未证。
   新反例以完整、core有效且无调用关系的side region复现1F，未改原负图。
   修复先建立准确当前iterator的原路径骨架，排除无路径、已知不匹配及旁路，
   再求输入未知；最终该反例与全部受影响case通过。
2. 固定native predicate与自己的准确bool literal可能冲突。新core有效图复现
   1F，修复从已有LiteralEvaluation原结果端口读取自己的literal并检查polarity。
   不从无关literal、最终Drive或采样值猜检查结果。
3. 反复全图扫描可能绕过shared budget。原qualification parent/正常terminal/
   literal索引放入既有一次raw preparation；相关路径、candidate、terminal与
   CFG边核验按共享预算扣费，查询内缓存不泄漏为全局身份或优化证明。
4. 三值AND顺序：已知control False或copy False不能被另一input Unknown掩盖。
   最后修复先过滤这些路径，paths空立即continue，再读取candidate input；
   最终统一回归覆盖这次源码字节。

## 最终有限只读确认

B最终确认以上有限风险无剩余阻断，并继续冻结；没有再次执行或写入：

- `scar/ir/program/await_qualification.py`：
  `119225840de2abe49e98086f07c03d221bc7488c3d9e962d14764acf9bd7ec4e`
- `scar/ir/program/protocol_await.py`：
  `63d8d8bf1ae8f26eab0c8d7f37d4c27bf36e1ccfa5aaa3b1a68e4c779ac5fac4`

root随后接收最终统一结果：1454P，前后768源SHA相等。
该运行证据与独立源码意见分别保留；native/source/runtime/value verification和
transformation授权仍False。合法失败的完整packet/state/final consumer及原
预算1组合未因此宣布完成，原16组/P5/M2/M0–M2仍OPEN。
