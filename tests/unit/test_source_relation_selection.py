"""Selected witnesses retain original ordinals and the complete parent receipt."""
import gzip
from hashlib import sha256

import pytest

from scar.analysis.normal_output import write_table
from scar.analysis.source_relation_selection import select_relation_rows


def test_selected_rows_require_unselected_parent_content_to_match(tmp_path):
    path=tmp_path/'rows.jsonl.gz'
    receipt=write_table(path,[dict(value=i,keep=i in (1,3)) for i in range(5)])
    assert select_relation_rows(tmp_path,receipt,lambda r:r['keep'])==(
        (1,dict(value=1,keep=True)),(3,dict(value=3,keep=True)))
    raw=gzip.decompress(path.read_bytes()).replace(b'"value":0',b'"value":9')
    changed=gzip.compress(raw,mtime=0);path.write_bytes(changed)
    compressed_updated={**receipt,'bytes':len(changed),'sha256':sha256(changed).hexdigest()}
    with pytest.raises(ValueError,match='decoded receipt'):
        select_relation_rows(tmp_path,compressed_updated,lambda r:r['keep'])
