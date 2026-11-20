import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import nullcontext

spec = importlib.util.spec_from_file_location('silicon_api', Path(__file__).parents[1] / 'api_provider.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

class Store:
    def __init__(self, config): self.config = config
    def lock(self): return nullcontext()
    def load(self): return {'api': self.config}

class ProviderTests(unittest.TestCase):
    def config(self, protocol='responses'):
        return {'base_url':'http://127.0.0.1:1234/v1','protocol':protocol,'key':'','models':['fixture-model']}

    def test_config_rejects_insecure_remote_urls_and_never_returns_key(self):
        for url in ['http://remote.example/v1','https://name:secret@example.com/v1','https://example.com/v1?key=secret','file:///tmp']:
            with self.assertRaises(ValueError): api.validate_config({**self.config(),'base_url':url})
        result=api.metadata(api.validate_config(self.config()))
        self.assertNotIn('key',result)

    def test_responses_preserves_function_calls_and_effort(self):
        completed={'type':'response.completed','response':{'status':'completed','output':[{'type':'function_call','call_id':'call-1','name':'mp_task_observe','arguments':'{}'}]}}
        stream=io.BytesIO(('data: '+json.dumps(completed)+'\n\n').encode())
        with patch.object(api,'store',return_value=Store(self.config())),patch.object(api,'request',return_value=stream) as request:
            value=api.main({'mode':'infer','model':'fixture-model','effort':'high','messages':[{'role':'user','content':[{'type':'text','text':'observe'}]}],'tools':[]})
        self.assertEqual(value['blocks'][0]['name'],'mp_task_observe')
        self.assertEqual(request.call_args.args[2]['reasoning'],{'effort':'high'})

    def test_chat_completion_can_omit_effort_and_preserves_tools(self):
        result={'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'c1','function':{'name':'mp_task_start','arguments':'{"case_id":"sky130_gcd"}'}}]}}]}
        with patch.object(api,'store',return_value=Store(self.config('chat_completions'))),patch.object(api,'request',return_value=io.BytesIO(json.dumps(result).encode())) as request:
            value=api.main({'mode':'infer','model':'fixture-model','effort':'none','messages':[],'tools':[]})
        self.assertEqual(value['blocks'][0]['id'],'c1')
        self.assertNotIn('reasoning_effort',request.call_args.args[2])

if __name__=='__main__': unittest.main()
