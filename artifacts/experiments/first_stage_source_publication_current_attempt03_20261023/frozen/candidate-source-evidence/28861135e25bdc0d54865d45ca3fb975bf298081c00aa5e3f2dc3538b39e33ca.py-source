"""Paid optional evidence over the existing continuation worklist states.

These receipts reference canonical ports and query-local states. They do not
create a second producer graph or enumerate complete control paths.
"""
from .protocols import HostTerminal


class ContinuationReceipts:
    def __init__(self, ctx, source):
        self.ctx, self.source = ctx, source
        self.context = None
        self.transitions, self.terminals = [], []

    def fields(self, expected, choices, crossed):
        return {'root_source': self.source, 'current_source': expected,
                'choices': choices, 'context': self.context,
                'crossed_suspend': crossed}

    def transition(self, following, operation):
        if not self.ctx.spend('completion_receipt_transitions'):
            return False
        self.transitions.append({'source': self.context, 'target': following,
                                 'operation': operation.id})
        return True

    def terminal(self, expected, role, actual, choices, crossed, binding):
        if not self.ctx.spend('completion_receipt_terminals'):
            return
        root = (binding if expected == self.source else
                self.ctx.bind(self.source, actual, choices=choices))
        gaps = tuple(dict.fromkeys((*binding.get('gaps', ()), *root.get('gaps', ()))))
        self.terminals.append({**self.fields(expected, choices, crossed),
            'terminal': HostTerminal(actual.operation), 'actual': actual, 'role': role,
            'binding': binding, 'root_binding': root, 'root_preserved': root['match'],
            'status': 'CONTRADICTED' if binding['match'] is False else
                      'PARTIAL' if binding['match'] is None or gaps else 'DECLARED',
            'gaps': gaps, 'source_runtime_verified': False,
            'runtime_identity_verified': False, 'value_identity_verified': False,
            'transformation_authorized': False})
