"""Replay the same first, complete, late-intent exercise call on both code versions."""
import json, os, threading, time
from pathlib import Path
from http.server import ThreadingHTTPServer

folder=Path(__file__).parent
from http.server import BaseHTTPRequestHandler

class StreamHandler(BaseHTTPRequestHandler):
    def reply(self, payload, *, deltas=None, hold_seconds=.6):
        stream = payload.get("stream")
        model = payload.get("model", "deepseek-flash")
        self.send_response(200)
        if not stream:
            body = json.dumps({"id":"fixture","object":"chat.completion","created":int(time.time()),"model":model,
                               "choices":[{"index":0,"message":{"role":"assistant",**deltas[0]},
                                           "finish_reason":"stop"}]}).encode()
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for index, delta in enumerate([{"role":"assistant"}, *deltas, {}]):
            finish = None if index <= len(deltas) else "tool_calls" if "tool_calls" in deltas[0] else "stop"
            item = {"id":"fixture","object":"chat.completion.chunk","created":int(time.time()),
                    "model":model,"choices":[{"index":0,"delta":delta,"finish_reason":finish}]}
            self.wfile.write(("data: " + json.dumps(item,ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()
            if index == 1 and len(deltas) > 1:
                time.sleep(hold_seconds)
        self.wfile.write(b"data: [DONE]\n\n")

batch=json.loads((folder/'基线首次练习工具入参.json').read_bytes())

stems=[q['prompt'] for q in batch['questions']]
counts={}
lock=threading.Lock()
class Handler(StreamHandler):
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        mode=(folder/'case').read_text().strip()
        messages=data['messages']
        system=str(messages[0]['content'])
        tools={i['function']['name'] for i in data.get('tools',[])}
        print('fixture', mode, 'with tools' if tools else 'without tools', 'exercise tool available' if 'ask_user' in tools else '',flush=True)
        def reply(text):
            return self.reply(data,deltas=[{'content':text if isinstance(text,str) else json.dumps(text,ensure_ascii=False)}])
        if 'visual_intent' in system or '判断学生这一轮是否主动要求' in system:
            return reply({"choice":0,"required":False,"visual_intent":"none"})
        if '审图员' in system:
            inputs=json.loads(messages[-1]['content'])
            stem=inputs['drawing_task'];idx=next(i for i,q in enumerate(stems) if q in stem or stem in q)
            audit=inputs.get('figure',{})
            given=audit.get('givens',{}) if isinstance(audit,dict) else {}
            points=given.get('points',[])
            y=next((v[2] for v in points if v[0]=='A'),None)
            with lock:
                count=counts.setdefault(mode,[0]*3)
                count[idx]+=1
                fail=idx==1 and (mode=='always' or mode=='once' and y!=1)
                print('audit',idx+1,count[idx],not fail,'A_y',y,time.monotonic(),flush=True)
            time.sleep(1 if idx!=1 else 2)
            return reply({'approved':not fail,'issues':['A 在虚轴上的分量须为 1，请按已知值修复位置。'] if fail else [],'checks':['核对本题的点和已知条件']})
        if '画一张静态教学示意图' in system:
            if mode=='always':return reply({'unsupported':True})
            native=json.loads(batch['questions'][1]['diagram_specification'])
            return reply({'visualizer':'svg','title':'第二题的已知向量','description':'O 为原点，A 为已知点。','payload':native})
        if 'ask_user' in tools:
            history=[m for m in messages if m['role']=='tool']
            if not history or not any('答案' in str(m.get('content','')) and '收到' in str(m.get('content','')) for m in history):
                if history:
                    return reply('题卡已处理。')
                args=json.loads(json.dumps(batch))
                if mode in ('once','always'):
                    spec=json.loads(args['questions'][1]['diagram_specification']);spec['givens']['points'][1][2]=2
                    args['questions'][1]['diagram_specification']=json.dumps(spec,ensure_ascii=False)
                call={'index':0,'id':'qa-exercise-batch','type':'function','function':{'name':'ask_user','arguments':json.dumps(args,ensure_ascii=False)}}
                print('exercise call',flush=True)
                return self.reply(data,deltas=[{'tool_calls':[call]}])
        return reply('收到，已按学生提交的项目完成本次反馈。')

ThreadingHTTPServer(('127.0.0.1',int(os.environ['QA_PORT'])),Handler).serve_forever()
