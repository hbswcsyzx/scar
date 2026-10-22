# 第一阶段下一资源连接：profiler allocation 生命周期

2026-10-22。设计已按本机原档审计；**尚未实施导入**。

## 实际断口

`native_import.chrome_events()` 当前对 `ph != X` 只保留原档 locator。
真实LeWM Kineto中的 **70872条[memory]** 因而尚无allocation/lifetime模型。
独立标准库重计：35598正Bytes、35274负Bytes、0零值；CPU11198、CUDA59674；
本档全在host TID452006，Ev Idx均为唯一整数，JSON内按它非递减。
重计产物见statement-blockers实验中的native-memory-audit.json；原档位于本worktree
`artifacts/experiments/first_stage_lewm_capture_20261020_bpf/trace/kineto.*.json.gz`。

## 接入既有模型

在已有native importer已经读取的Kineto文档上增加有界适配，不再读ETO或造资源图：

- `ValueGraph.StorageAllocation`：一次profiler报告的分配；没有Tensor内容或版本。
- `AllocationTarget`：引用原allocation作为resource target，不另复制ResourceInstance。
- `EvidencePoint/ProviderFactReference`：精确原档位置和已核验provider合同。
- `TargetLifetimeEvent`：只在原生合同及顺序被现有validator认可时建立LIVE/RETIRED；
  未满足的义务保留具体缺口，不填写状态后就宣布寿命已证明。

地址槽key含capture hash、进程实例、DeviceType/Id及Addr。一次分配ID另含正事件
的精确locator，地址复用必须产生新ID。negative只匹配同槽唯一未结束且大小吻合
的分配；无前史free、重复free、大小冲突或重叠positive均单列，不用计数差叫泄漏。

## 顺序与事实边界

固定provider来源见已保存torch-collection.cpp的线程allocation队列、results→Ev Idx
及timestamp adjustment实现。当前输入的单线程、唯一/有序Ev Idx是已观测前提；
provider合同、配置及跨线程顺序仍须逐输入核验，不能普遍按JSON位置/近邻时间配对。

此模型描述PyTorch profiler allocation/free；不是cudaMalloc/cudaFree或缓存池物理
归还。没有准确pool身份就不造pool。ETO storage token不是Addr，不按shape/指针
拼Tensor consumer。stream ready、kernel completion、逻辑内容和物化仍分别验收。

## 紧接的实施与验收

1. 在原import-native入口自动接入原档memory记录，保存allocation身份、事件定位、
   已连接/未连接free和具体原因；不加backend或新资源framework。
2. 对本70872条记录实际导入；独立原档重计核分母、代次和地址复用，保留未配对。
3. 将现有lifetime验证器不能认可的项落为具体obligation，不通过降低mandatory通过。

与JoinedStr/Dict/解构等源码断口并行推进；仍是第一阶段S3，不进入优化。
