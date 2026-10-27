# Driver建模复审与C2F首outcome查询证据

日期2026-10-18；研究基线`012db08`。**完整C2D字段审查仍REVISE；不是driver发布。**
查询实现提交：`9f3d7e796f2fb975528b123d009f1dacb84602ba`。

## 分开的证据分母

1. `review/lifecycle-witness.py/.json/.log`：8组首次stdlib断言通过，CPython3.14.7，
   未import Torch/SCAR，不保留frame/object/exception作为结果。回收策略及未覆盖的
   resurrection/线程/信号等限制写在language report，不按Closed推断所有对象已死。
2. `review/claim-lifecycle-probe.py`和两份日志：首批两个观测组，后补raw THROW为
   三个组；保留两次实际exit 0。它们是观测脚本，不冒称三项pytest或driver测试。
3. `review/body-outcome-probe.py/.json/.initial.log`：8个既有合法IR入口/无完成检查，
   加1个仅signature的extra-driver-domain设计检查。不是9个产品driver测试。
4. `frontier/`：新API的定向记录，initial手工fixture漏world被core正确拒绝；补正及
   最后规范UseSite identity断言的运行分开保留。最终新增7项通过。
5. `component/final.json`：C2F完整517项 / 7.384s，9项标准全PASS，406源文件指纹
   前后相同。包含旧body/wire/ordinary-native-query回归，不是517个新driver功能。
6. `full/`：冻结实现单次全仓的精确命令、环境、JUnit、case、时间/内存和前后指纹。
   单次终态为3,549项PASS / 433.223s / 1,030,428KiB，零失败/错误/跳过，三条
   既有warnings；前后HEAD/clean/406源文件/26份fixture相同，自建basetemp已清理。
   只关闭C2F静态查询组件，完整C2D/第一阶段仍开放。

## 具体决定及权限

独立core、claim/lifecycle与language review，以及root复审/收敛记录在`review/`。
原raw THROW→packet、混合permit/session和region-wide outcomes假设需要修订。
Create映射收敛为既有entry ValueID与owned UseID；默认/pack/环境缺实际producer是
前端恢复缺口，不需要再造一套目标类型。完整gate/admission/owner/session/commit/
no-body-close/release规则尚未冻结；不因本轮查询验收给它们PASS。

实际产品仅新增当前entry/真实landing到首Suspend/Return/Raise的共享派生查询，
返回规范UseSite且排除saved私有值，不新增wire/第二套图或driver执行。
空frontier不证无副作用或dead，非空不证必终止/运行时真的走该路。

完成归档后只读核验：

```bash
conda activate lewm
python artifacts/experiments/b1_call_operands/model_driver_interfaces/check_evidence.py
```

该核验不重跑语言探针/pytest/LeWM/GPU。第一阶段M0–M2、自动LeWM建图及可信
变换/clean A-B加速比仍未完成。新档案保留所有初始结果，旧C2B档案不改写。
