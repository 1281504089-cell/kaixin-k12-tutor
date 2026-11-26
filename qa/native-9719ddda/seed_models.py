from deeptutor.services.config.model_catalog import get_model_catalog_service
from deeptutor.capabilities.setup.binding import mark_intro_shown
import json,os
from pathlib import Path
s=get_model_catalog_service()
c=s.load()
port=os.environ['QA_PORT']
for key,binding,model,suffix,extra in [('llm','deepseek','deepseek-flash','/v1',{'reasoning_effort':'high','context_window':'96000'}),('imagegen','dashscope','qwen-image-2.1-pro','/api/v1',{'size':'1024x1024'})]:
 ident=key+'-local-test'
 record=dict(id=ident,name='本机验收',binding=binding,api_key='isolated-local-test',base_url='http://127.0.0.1:'+port+suffix,models=[dict(id=model,name=model,model=model,**extra)])
 c['services'][key]=dict(active_profile_id=ident,active_model_id=model,profiles=[record])
s.save(c)
settings=Path(os.environ['DEEPTUTOR_HOME'])/'data/user/settings'
(settings/'interface.json').write_text(json.dumps(dict(language='zh',enabled_optional_tools=['imagegen'],theme='light',learning_habits_enabled=False)))
mark_intro_shown()
