import sitecustomize
import time
sitecustomize._scar_evidence.close_at_exit()
print('MANUAL_CLOSE_DID_NOT_EXIT_APPLICATION', flush=True)
time.sleep(6)
