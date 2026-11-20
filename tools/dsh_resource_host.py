"""DSH transport for the single approved Core resource continuation.

Retains the existing host error handling, task controller and Agent loop.
"""
import io
import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    request = json.load(sys.stdin)
    from tools.core_resource_extension import install_for_request
    try:
        install_for_request(request)
    except Exception as exc:
        print(json.dumps({'ok': False, 'code': 'RESOURCE_EXTENSION_INVALID',
                          'error': type(exc).__name__ + ': ' + str(exc)}))
        return
    sys.stdin = io.StringIO(json.dumps(request))
    runpy.run_module('macro_agent.dsh_host', run_name='__main__')


if __name__ == '__main__':
    main()
