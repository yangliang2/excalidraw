#!/usr/bin/env python3
"""Explicit fault injection: no model/network/tool execution. Never a fake success."""
import json
import time
print(json.dumps({'type': 'error', 'message': 'Selected model is at capacity. Please try a different model.',
                  'fault_injection': 'capacity-fixture; no model call'}), flush=True)
time.sleep(600)
