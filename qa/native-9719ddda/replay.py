# Replay the exercise arguments captured from the real, synthetic attachment case.
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import sys

here=Path(__file__).resolve().parent
card=json.loads((here/'recorded-found-card.json').read_text())
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        messages=data['messages']
        system='\n'.join(m.get('content','') for m in messages if m['role']=='system' and isinstance(m.get('content'),str))
        names=[t['function']['name'] for t in data.get('tools',[])]
        marker=here/'grade-selected.txt'
        tool=None
        if marker.exists():
            text="你选 B 正确。56 g ÷ 70 cm³ = 0.8 g/cm³。"
        elif '判断学生这一轮是否主动要求' in system:
            sel={"action":"practice","source_mode":"selected","source_quote":"从这张纸上挑那道现成的液体密度四选一","topic":"液体密度","topic_quote":"液体密度","single_card":True,"strict_originals":True,"anchor":""}
            text=json.dumps({"choice":0,"required":False,"visual_intent":"none","experiment":0,"practice":sel} if '"choice"' in system or '"visual_intent"' in system else sel,ensure_ascii=False)
        elif 'ask_user' in names:
            text=""
            card_args=dict(card)
            params=next(t['function']['parameters'] for t in data['tools'] if t['function']['name']=='ask_user')
            if 'source_mode' in params.get('properties',{}):
                card_args.update(source_mode="selected", source_quote="从这张纸上挑那道现成的液体密度四选一", strict_originals=True)
            tool={"id":"qa-source-card","type":"function","function":{"name":"ask_user","arguments":json.dumps(card_args,ensure_ascii=False)}}
        elif '标题' in system or 'title' in system.lower(): text='液体密度'
        else: text="已读取附件中的液体密度练习，按原件交付。"
        result={"role":"assistant","content":text}
        if tool:result["tool_calls"]=[tool]
        common={"id":"local-replay","created":1,"model":data['model']}
        finish="tool_calls" if tool else "stop"
        if data.get('stream'):
            if tool:tool["index"]=0
            frames=[{**common,"object":"chat.completion.chunk","choices":[{"index":0,"delta":result,"finish_reason":None}]},
                    {**common,"object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":finish}]}]
            body=(''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode();mime='text/event-stream'
        else:
            body=json.dumps({**common,"object":"chat.completion","choices":[{"index":0,"message":result,"finish_reason":finish}]}).encode();mime='application/json'
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()

