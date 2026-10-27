# Unique input geometry under an explicit static protocol

`query_native_input_allocation(..., derive_region=False)`默认保留原行为；`True`选择固定版本 `PINNED_TORCH_VALID_STRIDED_ALLOCATION_BOUNDS_V1`，不是用户声明pure/已证content/ready。只在原normal native-input/allocation checks通过后解几何约束。

实际同一CPU scalar端口：shape=[]、strides=[]、torch.float32的现有IR宽度4B、同provider allocation extent4B、storage_base_ptr=allocation.address=110368518774080。有效非空strided Tensor要求offset≥0和4*offset+4≤4，所以唯一offset=0。泛化规则用现有IR dtype-width表及 `span=width*(1+Σ(size−1)*stride)`，不按row/算子/业务名。仅span==extent且base匹配才返回现StorageRegion派生view；empty/未知dtype/非满span不推断，矛盾明确拒绝。该rule只支持非负int64 size/stride。

协议依据是原cf30153c4c131c8164ee7798e5022d810682e2cb provider的有效Tensor约束：`ATen/native/Resize.h:95 checkInBoundsForStorage` 和`:259 setStrided`（先检查offset/stride非负与范围）；它是版本化静态假设，不是本次观测到offset。原`storage_offset=None`/`not_exposed_by_installed_tensor_metadata_binding`保持。derive_region结果列明assumptions、span/extent/base约束、metadata和birth SourceFact，status=`DERIVED_UNIQUE_OFFSET_UNDER_VALID_TENSOR_PROTOCOL`。没有借另一marker时点。派生region ID限定原execution artifact+NativeInputRef+metadataSource+allocation+协议；`record_is_stored=False`，不可冒充原bundle中的RegionRef，不改旧规范artifact/ID。没有创建ProgramGraph或ValueGraph；返回一条派生StorageRegion view。

真实普通查询自持session75717 actual exit0，1.854456069s，RSS106,768KiB，stored23,524,721B/decoded43,885,446B/total67,410,167B。expected4B/offset0、原offset仍None已检查。QUERY20,758B/SHA585a11f3ba770d6e458f76c544bdf170201aa2918033edab8527e9fa97aaacf7。源SHA0f675ee3f2bfea82a26edb024c5fce459aa2f01ec9a89288aa58ace9e077e3c8。一次简单反例仅把本地数学输入extent设8B（不是原observed记录），0≤offset≤1，返回OPEN/regionNone，见NONUNIQUE.json；无额外端点矩阵。

原对象身份/分配关系保留；未生成DataIdentity、内容读版本、Materialization或actual write/ready资格。GPU未验证，模型仍OPEN。原attempt01–03和旧报告/source receipts保持不动；本目录是新增geometry版本证据。logical方案已另提交ee647545。

后继read版本应以本次真实read occurrence及原source/state support为identity锚；未知数值不妨碍符号版本。尚缺的是引用→内容读/具体state occurrence的协议关联，不是要求把Tensor数据实际读回。copy保版本还必须列明固定协议、有效read及normal/表示等guard；本轮未实现它。
