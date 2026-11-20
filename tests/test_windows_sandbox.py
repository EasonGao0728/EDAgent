import json
import os
from pathlib import Path
import unittest

from macro_agent.adapters.toy import load_case
from macro_agent.windows_sandbox import WindowsSandbox

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows AppContainer boundary tests")
class SandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = WindowsSandbox(ROOT, timeout=15)

    def test_actual_worker_runs_generated_logic(self):
        result = self.sandbox.run({"case": load_case(ROOT / "cases/toy/connected_groups.json"),
            "source": "def propose_moves(context, budget, rng):\n    m=context.macros(['a'])[0]\n    return [{'moves':[{'macro_id':m['id'],'x':m['x']+1,'y':m['y']}]}]\n",
            "budget": {"max_candidates": 1}, "seed": 7})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["candidates"][0]["moves"][0]["x"], 9)

    def test_worker_reports_syntax_and_nonfinite_failures(self):
        for source in ("def broken(:", "def propose_moves(context,budget,rng):\n    return [{'moves':[{'macro_id':'a','x':float('nan'),'y':0}]}]\n"):
            result = self.sandbox.run({"case": load_case(ROOT / "cases/toy/connected_groups.json"),
                                      "source": source, "budget": {"max_candidates": 1}, "seed": 1})
            self.assertFalse(result["ok"], result)

    def test_infinite_program_is_terminated(self):
        sandbox = WindowsSandbox(ROOT, timeout=1)
        result = sandbox.probe("while True:\n    pass\n")
        self.assertFalse(result["ok"], result)
        self.assertLess(result["elapsed_seconds"], 8)

    def test_os_token_files_network_children_and_environment(self):
        canary = ROOT / ".cache/macro-agent/test-canary.txt"
        canary.write_text("host canary", encoding="utf-8")
        previous = os.environ.get("MACRO_AGENT_TEST_SECRET")
        os.environ["MACRO_AGENT_TEST_SECRET"] = "must-not-be-inherited"
        source = '''import json,sys,os,socket,subprocess,ctypes
from ctypes import wintypes as W
from pathlib import Path
r={}
k=ctypes.WinDLL('kernel32',use_last_error=True)
a=ctypes.WinDLL('advapi32',use_last_error=True)
k.GetCurrentProcess.restype=W.HANDLE
a.OpenProcessToken.argtypes=[W.HANDLE,W.DWORD,ctypes.POINTER(W.HANDLE)]
a.GetTokenInformation.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD)]
token=W.HANDLE();size=W.DWORD();value=W.DWORD()
assert a.OpenProcessToken(k.GetCurrentProcess(),8,ctypes.byref(token))
assert a.GetTokenInformation(token,29,ctypes.byref(value),4,ctypes.byref(size))
r['is_appcontainer']=value.value
for name,operation in [('read',lambda:Path(CANARY).read_text()),('write',lambda:Path(CANARY).write_text('tampered')),('network',lambda:socket.create_connection(('127.0.0.1',11434),timeout=1)),('child',lambda:subprocess.Popen([sys.executable,'-c','pass']))]:
    try:
        operation();r[name]='allowed'
    except OSError:
        r[name]='blocked'
r['secret_present']='MACRO_AGENT_TEST_SECRET' in os.environ
Path(sys.argv[1]).write_text(json.dumps({'ok':True,**r}))
'''.replace('CANARY', repr(str(canary)))
        try:
            result = self.sandbox.probe(source)
        finally:
            if previous is None:
                os.environ.pop("MACRO_AGENT_TEST_SECRET", None)
            else:
                os.environ["MACRO_AGENT_TEST_SECRET"] = previous
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["is_appcontainer"], 1)
        for key in ("read", "write", "network", "child"):
            self.assertEqual(result[key], "blocked", result)
        self.assertFalse(result["secret_present"])
        self.assertEqual(canary.read_text(), "host canary")


if __name__ == "__main__":
    unittest.main()
