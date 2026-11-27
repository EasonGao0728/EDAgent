import io,json,unittest
from unittest.mock import patch
from macro_agent.dsh_native import native_model
from macro_agent.openai_http import OpenAIError


class Provider:
    posts=[]
    def __init__(self,model=None):self.model=model;self.http=self;self.auth=self
    def access_token(self):return 'fixture-only'
    def resolve_model(self):
        if self.model is not None:raise OpenAIError('network_error')
        self.model='catalog-default'
    def open(self,url,**kw):
        self.posts.append(kw['body'])
        if kw['body']['model']=='not-visible':raise OpenAIError('model_not_found',404)
        event={'type':'response.completed','response':{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}]}}
        return io.BytesIO(('data: '+json.dumps(event)+'\n\n').encode())


class SelectionTests(unittest.TestCase):
    def run_request(self,model):
        with patch('macro_agent.dsh_native.ChatGPTProvider',Provider):
            return native_model({'model':model,'messages':[],'tools':[],'reasoning_effort':'xhigh'})
    def setUp(self):Provider.posts=[]
    def test_explicit_choice_avoids_failing_catalog_but_authenticates_post(self):
        self.assertEqual(self.run_request('gpt-6.1-sol')['blocks'][0]['text'],'ok')
        self.assertEqual(Provider.posts[0]['model'],'gpt-6.1-sol')
        self.assertEqual(Provider.posts[0]['reasoning']['effort'],'xhigh')
    def test_actual_model_access_failure_propagates_without_substitution(self):
        with self.assertRaisesRegex(OpenAIError,'model_not_found'):self.run_request('not-visible')
        self.assertEqual(len(Provider.posts),1)
    def test_default_discovers_and_malformed_identifier_never_posts(self):
        self.run_request(None);self.assertEqual(Provider.posts[0]['model'],'catalog-default')
        with self.assertRaisesRegex(ValueError,'identifier'):self.run_request('../file')
        self.assertEqual(len(Provider.posts),1)


if __name__=='__main__':unittest.main()
