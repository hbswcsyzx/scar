"""Classify the first frozen finite attempt; no reruns."""
from pathlib import Path
import xml.etree.ElementTree as ET

path = Path(__file__).resolve().parent / 'finite36-first/junit.xml'
for case in ET.parse(path).iter('testcase'):
    failure = case.find('failure')
    if failure is None:
        continue
    print(case.get('name'))
    lines = (failure.text or '').splitlines()
    for line in lines:
        if line.startswith(('E ', 'tests/unit/')):
            print(line[:700])
    print()
