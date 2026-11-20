"""Native DSH conversation/tool-call translation for official ChatGPT OAuth."""
import json
from .chatgpt_provider import ChatGPTProvider, completed_response
from .openai_http import API

def translate(messages):
    inputs=[]; instructions=[]
    for m in messages:
        role=m['role'];blocks=m.get('content',[])
        text='\n'.join(b.get('text','') for b in blocks if b.get('type')=='text')
        if role=='system': instructions.append(text)
        elif role=='tool':
            inputs.append({'type':'function_call_output','call_id':m['toolCallId'],'output':text})
        else:
            if text: inputs.append({'role':role if role in ('user','assistant','developer') else 'user','content':text})
            for b in blocks:
                if b.get('type')=='tool-call':
                    if not b['name'].startswith('mp_'):raise ValueError('non-MP tool call refused')
                    inputs.append({'type':'function_call','call_id':b['id'],'name':b['name'],'arguments':b['arguments']})
    return '\n'.join(instructions),inputs

def native_model(req):
    provider=ChatGPTProvider(model=req.get('model'))
    provider.resolve_model()
    instructions,inputs=translate(req['messages'])
    tools=[]
    for t in req.get('tools',[]):
        if not t['name'].startswith('mp_'):raise ValueError('unexpected tool in macro preset')
        tools.append({'type':'function','name':t['name'],'description':t.get('description',''),
                      'parameters':t['parameters'],'strict':False})
    body={'model':provider.model,'instructions':instructions,'input':inputs,'store':False,'stream':True}
    effort=req.get('reasoning_effort','xhigh')
    if effort not in ('low','medium','high','xhigh','max'):raise ValueError('unsupported reasoning effort')
    body['reasoning']={'effort':effort}
    if tools:body.update(tools=tools,parallel_tool_calls=False)
    with provider.http.open(API+'/responses',token=provider.auth.access_token(),body=body,stream=True) as stream:
        result=completed_response(stream)
    blocks=[]
    for item in result.get('output',[]):
        if item.get('type')=='function_call':
            if not item['name'].startswith('mp_'):raise ValueError('unexpected model tool')
            blocks.append({'type':'tool-call','id':item['call_id'],'name':item['name'],'arguments':item['arguments']})
        elif item.get('type')=='message':
            for content in item.get('content',[]):
                if content.get('type')=='output_text':blocks.append({'type':'text','text':content['text']})
                elif content.get('type')=='refusal':blocks.append({'type':'text','text':content.get('refusal','Request refused')})
    if not blocks:raise ValueError('empty completed response')
    return {'blocks':blocks,'usage':result.get('usage',{}),'model':result.get('model',provider.model),'reasoning_effort':effort}
