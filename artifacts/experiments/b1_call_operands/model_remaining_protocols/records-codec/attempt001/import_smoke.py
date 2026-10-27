from typing import get_type_hints
from scar.ir.program import ProgramGraph
from scar.ir.program.protocol_connections import (
    RequestAssociation, RequestStateCondition, TaskStatusRead,
    ProtocolCallInputs, ProtocolResultConsumers,
)
from scar.ir.program.protocols import ProtocolOperation, AdmissionPredicate
print("ProgramGraph fields:", tuple(get_type_hints(ProgramGraph)))
print("ProtocolOperation.contract:", get_type_hints(ProtocolOperation)["contract"])
print("AdmissionPredicate.subject:", get_type_hints(AdmissionPredicate)["subject"])
print("RequestAssociation:", get_type_hints(RequestAssociation))
print("TaskStatusRead:", get_type_hints(TaskStatusRead))
