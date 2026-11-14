"""Optimization of the guarded CPU array-region execution-plan profile."""

from .optimizer import optimize_region
from .selection import select_measured
from .hardware import bind_cpu_placement, propose_cpu_placements, validate_cpu_placement
from .schedule import (build_region_schedule, connect_materialization, schedule_document,
                       schedule_from_dict, validate_schedule)
from .resource_solver import hardware_model_skeleton, semantic_sha256, solve_resource_schedule

__all__ = ["optimize_region", "select_measured", "propose_cpu_placements",
           "bind_cpu_placement", "validate_cpu_placement", "build_region_schedule",
           "connect_materialization", "schedule_document", "schedule_from_dict",
           "validate_schedule", "solve_resource_schedule", "hardware_model_skeleton",
           "semantic_sha256"]
