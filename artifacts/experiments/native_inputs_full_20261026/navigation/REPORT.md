# Scoped canonical endpoint navigation

All **65,130** associations now have exactly one original qualification denotation, **ProgramSnapshot + Execution artifact + DenotationID** context. Keys include the original source and local endpoint; bare IDs were never assumed globally unique. Source input qualification inventory has **65,211** ports: **81** lack retained metadata (162 other missing native paths lie outside canonical boundaries). No UseOccurrence ID was minted.

The navigation consumer read **1,094,910,171 stored+decoded bytes** of existing published qualification/association artifacts. It did not repeat the capture, original ETO, canonical import or all execution bodies. Original ProgramSnapshot and artifact receipts are unchanged. Navigation records use the existing gzip JSONL transport: **369,240,629 raw /20,525,822 stored bytes**.

First script actual exit1 came after successful navigation publication: the ordinary verification harness incorrectly accessed ValueOccurrence.visit. It is preserved. Corrected readback used the already published navigation, actual exit0, **1.690939s**: ordinary Program/Execution codecs, exact denotation/binding, original ValueOccurrence.origin, original UseOccurrence(operation,use,value), row and node query. This is receipt/record verification, not restored ownership or fresh producer qualification.

Public association queries require the navigation manifest. Raw metadata manifests continue to support row queries. Node+association mode is explicitly rejected: first select the node's original row, then request associations for that row. Reader now checks regular nonsymlink files before bounded reads, schema/version/profile, exact nonnegative integer selectors, and bounded gzip decoding. No private SQLite is consulted.

Attempt05's three expired private indices were removed after ordinary readback: **5,344,858,112 bytes**. Known owner scripts were terminal and accessible fd scans found no matches; seven protected same-UID process fd directories were unavailable, explicitly recorded. No complete global fd-absence claim is made. Original capture and formal graphs remain unchanged.

This sample mirror retains one compressed navigation chunk plus the complete manifest; all other chunks and canonical execution/program bodies remain at their original local URIs. No implicit URI relocation is claimed. Contents, alias/state, physical allocation ranges and value readiness remain OPEN.
