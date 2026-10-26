import io, sys

def run(path):
    memory = io.BytesIO(b"SCAR stream interface")
    memory.seek(0)
    payload = memory.read()
    target = open(path, "wb")
    target.write(payload)
    target.flush()
    target.close()
    memory.close()
    try:
        target.read()
    except (ValueError, OSError):
        pass
    return payload

if __name__ == "__main__":
    result = run(sys.argv[1])
    assert result == b"SCAR stream interface"
    print("STREAM_TARGET_RETURNED")
