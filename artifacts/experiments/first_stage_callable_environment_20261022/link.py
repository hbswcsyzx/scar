import json
from pathlib import Path
from scar.analysis.program_inventory import inventory_program
from scar.analysis.call_operands import link_call_operands
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.record_codec import encode

out=Path(__file__).resolve().parent
inventory=inventory_program(out/'probe.py',project_root=out,calls_trace=out/'trace',body_profile=BodyLoweringProfile.STRUCTURED_ENV)
(out/'inventory.json').write_text(json.dumps(inventory.to_dict(),separators=(',',':'))+'\n')
report=link_call_operands(out/'trace',out,inventory,include_environments=True)
(out/'operand-links.json').write_text(json.dumps(report.to_dict(),separators=(',',':'))+'\n')
(out/'environment-bindings.json').write_text(json.dumps(report.environments,indent=2)+'\n')
print(json.dumps({'inventory':inventory.summary(),'routing':report.routing.summary(),'environments':report.environments['summary']}))
