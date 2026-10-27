import io
import os
from pathlib import Path
import textwrap

def transform(text):
    value = textwrap.dedent(text).encode('utf-8')
    path = Path(__file__).parent / 'sample.bin'
    with io.FileIO(path, 'w') as stream:
        stream.write(value)
    stream = io.FileIO(path, 'r')
    retained = stream.read()
    stream.close()
    try:
        stream.read()
    except ValueError:
        pass
    read_fd, write_fd = os.pipe()
    with io.FileIO(read_fd, 'r') as reader, io.FileIO(write_fd, 'w') as writer:
        writer.write(value)
        piped = reader.read(len(value))
    return retained == piped
