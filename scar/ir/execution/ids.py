"""Typed identities for execution coordinates.

These identifiers name runtime entities and occurrences. They are distinct
from static program IDs and from legacy v2 evidence/value identifiers.
"""
from scar.ir.v2.ids import Identifier


class RunID(Identifier):
    prefix = "exec_run"


class ProcessInstanceID(Identifier):
    prefix = "exec_process_instance"


class HostThreadInstanceID(Identifier):
    prefix = "exec_host_thread_instance"


class RegionActivationID(Identifier):
    prefix = "exec_region_activation"


class ExecutionSegmentID(Identifier):
    prefix = "exec_execution_segment"


class BlockVisitID(Identifier):
    prefix = "exec_block_visit"


class OperationOccurrenceID(Identifier):
    prefix = "exec_operation_occurrence"


class ValueOccurrenceID(Identifier):
    prefix = "exec_value_occurrence"


class ResourceInstanceID(Identifier):
    prefix = "exec_resource_instance"


class ExternalRealmID(Identifier):
    prefix = "exec_external_realm"


class NativeHandleLifetimeID(Identifier):
    prefix = "exec_native_handle_lifetime"


class ResourceBindingID(Identifier):
    prefix = "exec_resource_binding"


class HandleBindingID(Identifier):
    prefix = "exec_handle_binding"


class ResourceAccessID(Identifier):
    prefix = "exec_resource_access"


class RealizationID(Identifier):
    prefix = "exec_realization"


class WorkTicketID(Identifier):
    prefix = "exec_work_ticket"


class WorkOutcomeID(Identifier):
    prefix = "exec_work_outcome"


class WorkQuiescenceID(Identifier):
    prefix = "exec_work_quiescence"


class WorkRetentionID(Identifier):
    prefix = "exec_work_retention"


class QueuePrefixID(Identifier):
    prefix = "exec_queue_prefix"


__all__ = [
    "RunID", "ProcessInstanceID", "HostThreadInstanceID", "RegionActivationID",
    "ExecutionSegmentID", "BlockVisitID", "OperationOccurrenceID",
    "ValueOccurrenceID", "ResourceInstanceID", "ExternalRealmID",
    "NativeHandleLifetimeID", "ResourceBindingID", "HandleBindingID",
    "ResourceAccessID", "RealizationID",
    "WorkTicketID", "WorkOutcomeID", "WorkQuiescenceID", "WorkRetentionID", "QueuePrefixID",
]
