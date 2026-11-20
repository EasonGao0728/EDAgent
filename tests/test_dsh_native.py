import unittest
from unittest.mock import patch, MagicMock
from macro_agent.dsh_native import translate

class NativeMessageTests(unittest.TestCase):
    def test_default_and_custom_effort_reach_wire_without_downgrade(self):
        from macro_agent.dsh_native import native_model
        for selected,expected in [(None,'xhigh'),('medium','medium'),('max','max')]:
            provider=MagicMock();provider.model='gpt-6.1-sol'
            completed={'output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}]}
            req={'model':'gpt-6.1-sol','messages':[{'role':'user','content':[{'type':'text','text':'test'}]}]}
            if selected:req['reasoning_effort']=selected
            with patch('macro_agent.dsh_native.ChatGPTProvider',return_value=provider),patch('macro_agent.dsh_native.completed_response',return_value=completed):
                result=native_model(req)
            self.assertEqual(provider.http.open.call_args.kwargs['body']['reasoning']['effort'],expected)
            self.assertEqual(result['reasoning_effort'],expected)
    def test_tool_roundtrip_identity(self):
        instructions, items=translate([
            {'role':'system','content':[{'type':'text','text':'rules'}]},
            {'role':'user','content':[{'type':'text','text':'place'}]},
            {'role':'assistant','content':[{'type':'tool-call','id':'c1','name':'mp_start','arguments':'{}'}]},
            {'role':'tool','toolCallId':'c1','content':[{'type':'text','text':'{"ok":true}'}]},
        ])
        self.assertEqual(instructions,'rules')
        self.assertEqual(items[1]['call_id'],items[2]['call_id'])
        self.assertEqual(items[2]['type'],'function_call_output')
    def test_unrelated_tool_rejected(self):
        with self.assertRaises(ValueError):
            translate([{'role':'assistant','content':[{'type':'tool-call','id':'x','name':'shell','arguments':'{}'}]}])
