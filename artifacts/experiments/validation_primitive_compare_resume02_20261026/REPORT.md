Root确认49842实际exit0。同SP5输出hash/structure全相同；clean各n=1，仅见约5.5% wall减少，不报median或稳健加速，尚不足证明全26可完成。原9750为observer类型错误，已保留。

- old clean：wall21.448650235s，CPU21.413580152s。
- new clean：wall20.279057084s，CPU20.244948605s。
- new cProfile：wall73.709249415s，128,574,104calls；原profile79.986234797s、145,879,372calls，仅作调用统计参照。
- is_dataclass：11,792,964→6,005,426；_record_errors递归仍14,483,654次。
- whole119.443142550s；GNU119.54s/peak225,208KiB；IO144,038,850B/pending0。
- normalized codec output：21,830,385B，SHA23ca0c6df9924b0ed5466e462c7dff13504e6d4cec5971b04acd9077942b6d0d。

cProfile含额外开销、嵌套累计不可相加；SHA observer成本各约0.140s已计入，未额外to_dict。ROOT_RESULT原字节不改，无新模型/CodeWitness/runtime/publication资格。
