"""Compact terminal presentation of existing processing events."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import select
import signal
import shutil
import sys
import time
import unicodedata
import wave


def text(value):
    return re.sub(r'[\x00-\x09\x0b-\x1f\x7f]', '', str(value or '')).replace('\n', ' ')


def clock(stamp):
    try:return datetime.fromisoformat(str(stamp).replace('Z','+00:00')).astimezone().strftime('%H:%M:%S')
    except (ValueError,TypeError):return ''


def wrap(value, width):
    lines, line, used = [], '', 0
    for char in text(value):
        count = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in 'WF' else 1
        if used+count > width:
            lines.append(line);line='';used=0
        line += char;used += count
    return lines+[line] if line else lines or ['']


class State:
    def __init__(self, group):
        self.group=group;self.trace='';self.at='';self.phase='等待请求'
        self.input='';self.output='';self.intent='';self.elapsed=None;self.command=''
        self.model='';self.error='';self.detail=''
        self.model_elapsed=None
        self.debug={};self.raw_output='';self.steps=[]

    def remember(self, item):
        data=item.get('data',{});event=item.get('event','')
        def put(label,value):
            if value is not None and value!='':self.debug[label]=value
        put('请求编号',self.trace)
        put('最近方法',event)
        if not self.steps or self.steps[-1][1]!=event:
            self.steps.append((clock(item.get('at')),event));self.steps=self.steps[-8:]
        request=data.get('request') or {}
        for key,label in (('source','输入来源'),('confirmed','确认执行'),('pending_command_id','待确认编号')):
            put(label,request.get(key))
        for key,label in (('backend','后端'),('model','模型'),('record_seconds','录音秒数'),
                          ('audio_device','采集设备'),('pending_command_id','待确认编号'),
                          ('related_trace','原请求编号'),('packet_id','报文编号'),('usage','Token统计')):
            put(label,data.get(key))
        result=data.get('parsed') or data.get('bridge_response') or data.get('result') or {}
        if isinstance(result,dict) and isinstance(result.get('data'),dict):result=result['data']
        for key,label in (('backend','后端'),('parser','解析来源'),('llm_backend','推理后端'),
                          ('llm_model','模型'),('confidence','置信度'),('need_confirm','需要确认'),
                          ('payload','任务参数'),('pending_command_id','待确认编号'),
                          ('raw_text','识别原文'),('model_load_time_s','模型加载秒数'),
                          ('asr_time_s','识别处理秒数'),('audio_device','采集设备'),
                          ('accepted','受理结果'),('status','语音状态')):
            put(label,result.get(key))
        task=result.get('task_status') or {}
        for key,label in (('task_id','任务编号'),('state','任务状态'),('progress','任务进度'),
                          ('phase','任务阶段'),('current_waypoint_id','当前点位')):
            put(label,task.get(key))
        if data.get('payload') is not None:put('桥接参数',data['payload'])
        if data.get('packet') is not None:put('NV报文',data['packet'])
        if data.get('status') is not None:put('FPGA状态',data['status'])
        feedback=data.get('feedback') or {}
        if feedback.get('event'):put('任务事件',feedback['event'])
        if event in ('chat_json.end','chat_text.end'):
            self.raw_output=data.get('output') or ''
        audio_path=result.get('audio_path') or data.get('audio_path')
        if audio_path:
            put('音频文件',Path(audio_path).name)
            try:
                with wave.open(str(audio_path),'rb') as audio:
                    put('采样率Hz',audio.getframerate());put('声道数',audio.getnchannels())
                    put('音频秒数',round(audio.getnframes()/audio.getframerate(),3))
                    put('采样位数',audio.getsampwidth()*8)
            except (OSError,wave.Error,EOFError):pass

    def event(self, item):
        if item.get('stage') != {'asr':'ASR','llm':'LLM','task':'TASK','tts':'TTS'}[self.group]:
            return
        data=item.get('data',{});event=item.get('event','');identity=item.get('trace','')
        if identity and identity != self.trace:
            self.__init__(self.group)
            self.trace=identity
        self.at=clock(item.get('at'))
        self.remember(item)
        if self.group!='llm':self.elapsed=data.get('duration_ms',self.elapsed)
        if event.endswith('.error') or event=='nv.send.failed':
            self.error=data.get('error') or '处理失败';self.phase='失败';return
        if self.group=='asr':
            if event=='record.begin':self.phase='录音中'
            elif event=='transcribe_audio_file.begin':self.phase='识别中'
            elif event=='transcribe_audio_file.end':
                result=data.get('result') or {};self.output=result.get('recognized_text','')
                self.phase='完成' if result.get('success') else '识别失败'
                self.error=result.get('error') or ''
                if result.get('asr_time_s') is not None:self.elapsed=result['asr_time_s']*1000
        elif self.group=='llm':
            request=data.get('request') or {}
            if event=='handle.begin':self.input=request.get('text','');self.phase='理解中'
            if event=='parse.begin':self.input=data.get('text',self.input);self.phase='解析中'
            if event in ('chat_json.begin','chat_text.begin'):
                self.model=data.get('model','');self.phase='模型推理中'
                if not self.input:self.input=str(data.get('input','')).split('用户：')[-1]
            if event in ('chat_json.end','chat_text.end'):
                self.model_elapsed=data.get('duration_ms');self.elapsed=self.model_elapsed
                self.phase='模型已返回' if data.get('success') else '推理失败'
                self.output=data.get('output') or '';self.error=data.get('error') or ''
                try:
                    parsed=json.loads(self.output)
                    self.output=parsed.get('reply_text') or parsed.get('reason') or self.output
                    self.intent=parsed.get('intent','')
                except (ValueError,TypeError):pass
            if event in ('parse.end','handle.end'):
                if event=='parse.end' and self.model_elapsed is None:self.elapsed=data.get('duration_ms')
                result=data.get('parsed') or data.get('result') or {}
                self.output=result.get('reply_text') or result.get('detail') or self.output
                self.input=result.get('recognized_text') or self.input
                self.intent=result.get('intent') or self.intent
                self.phase={'rule':'规则解析','builtin':'内置回复','confirm':'确认处理','safety':'校验结果'}.get(result.get('parser'),'完成')
                if result.get('need_confirm'):self.phase='等待确认'
        elif self.group=='tts':
            if event in ('speak.begin','speak_with_policy.begin'):
                self.output=data.get('text','');self.phase='合成中'
            elif event in ('speak.end','speak_with_policy.end'):
                result=data.get('result') or {};self.output=result.get('text') or self.output
                self.phase={'generated':'音频已生成','skipped':'已跳过','failed':'合成失败'}.get(result.get('status'),'完成')
                self.error=result.get('error_reason') or ''
        else:
            request=data.get('request') or {}
            self.input=request.get('text') or self.input
            result=data.get('bridge_response') or data.get('result') or {}
            if isinstance(result,dict) and isinstance(result.get('data'),dict):result=result['data']
            if event=='bridge.request':
                payload=data.get('payload') or {};self.command=payload.get('command') or data.get('kind','')
                self.phase='桥接处理中'
            packet=data.get('packet') or {}
            if packet:
                self.command=packet.get('type') or self.command
                self.detail=', '.join(str(k)+'='+str(v) for k,v in packet.items() if k not in ('type','bytes'))
                self.phase={'nv.queued':'发送排队','nv.transport.sent':'报文已发送'}.get(event,self.phase)
            if event=='_create_pending.end':self.phase='等待确认'
            if result:
                self.command=result.get('command') or result.get('intent') or self.command
                self.detail=result.get('detail') or self.detail
                if result.get('need_confirm'):self.phase='等待确认'
                elif result.get('accepted') is True:self.phase='已受理'
                elif result.get('accepted') is False:self.phase='未执行'
                task=result.get('task_status') or {}
                if task.get('state') in ('completed','failed','cancelled'):
                    self.phase={'completed':'任务完成','failed':'任务失败','cancelled':'已取消'}[task['state']]
            if event=='task.feedback':
                feedback=data.get('feedback') or {};ev=feedback.get('event') or {}
                self.detail=ev.get('detail') or self.detail
                self.phase={'running':'执行中','completed':'任务完成','failed':'任务失败','cancelled':'已取消','paused':'已暂停'}.get(ev.get('task_state'),self.phase)
            if event=='fpga.status.observed':
                s=data.get('status') or {}
                self.detail=f'FPGA状态 {s.get("state")} | 速度 {s.get("vx_mmps")} mm/s'

    def lines(self):
        status='状态：'+self.phase
        if self.elapsed is not None:status+=f'  |  {self.elapsed/1000:.3f} s'
        result=[status]
        if self.group=='asr':result+=['识别：'+(self.output or '—')]
        elif self.group=='llm':
            if self.input:result+=['输入：'+self.input]
            if self.intent:result+=['意图：'+self.intent]
            if self.output:result+=['回复：'+self.output]
        elif self.group=='tts':result+=['播报：'+(self.output or '—')]
        else:
            if self.command:result+=['指令：'+self.command]
            if self.input:result+=['输入：'+self.input]
            if self.detail:result+=['反馈：'+self.detail]
        if self.error:result+=['错误：'+str(self.error)]
        return result

    def sections(self):
        def value(item):
            if isinstance(item,bool):return '是' if item else '否'
            if isinstance(item,(dict,list)):return json.dumps(item,ensure_ascii=False,separators=(',',':'))
            return str(item)
        summary=self.lines()
        priority={'asr':['后端','采集设备','录音秒数','识别处理秒数','模型加载秒数','识别原文'],
                  'llm':['模型','推理后端','解析来源','置信度','需要确认','任务参数','Token统计','输入来源'],
                  'task':['NV报文','FPGA状态','桥接参数','受理结果','任务状态','任务阶段','任务进度','当前点位','任务事件'],
                  'tts':['后端','语音状态','采样率Hz','声道数','采样位数','音频秒数','音频文件']}[self.group]
        keys=[k for k in priority if k in self.debug]+[k for k in self.debug if k not in priority]
        parameters=[str(k)+'：'+value(self.debug[k]) for k in keys]
        groups=[('结果',summary[1:]),('参数',parameters or ['等待参数。'])]
        if self.raw_output:groups.append(('模型输出',[self.raw_output]))
        groups.append(('步骤',[stamp+'  '+event for stamp,event in self.steps] or ['等待处理。']))
        return summary[0],groups


class Logs:
    def __init__(self, root):
        self.paths=[root/'logs'/f'processing_{name}.jsonl' for name in ('backend','bridge')]
        self.handles={}

    def read(self):
        events=[]
        for path in self.paths:
            try:stat=path.stat()
            except FileNotFoundError:continue
            identity=(stat.st_dev,stat.st_ino)
            previous=self.handles.get(path)
            if previous is None or previous[1]!=identity or stat.st_size<previous[0].tell():
                if previous:previous[0].close()
                f=path.open('rb')
                if previous is None and stat.st_size>128*1024:
                    f.seek(stat.st_size-128*1024);f.readline()
                self.handles[path]=(f,identity)
            f=self.handles[path][0]
            while True:
                at=f.tell();line=f.readline()
                if not line:break
                if not line.endswith(b'\n'):f.seek(at);break
                try:events.append(json.loads(line))
                except ValueError:pass
        return sorted(events,key=lambda e:e.get('at',''))

    def close(self):
        for f,_ in self.handles.values():f.close()


def yolo_lines(data, recent):
    phase={'ok':'识别中','stale':'结果过期','disabled':'已关闭','not_reported':'等待画面'}.get(data.get('status'),'连接中')
    result=[f'状态：{phase} | {data.get("detect_fps") or "—"} FPS | 更新 {data.get("detection_age_s")} s',
            '模型：'+str(data.get('model') or 'YOLO26')]
    objects=data.get('objects') or []
    result+=['当前目标：'+str(len(objects))]
    current=objects
    if not current and recent and time.monotonic()-recent[0]<=5:
        result+= [f'最近检测（{time.monotonic()-recent[0]:.1f} s前）：']
        current=recent[1]
    for obj in current:
        conf=obj.get('confidence');dist=obj.get('distance_m')
        score=f'{conf:.1%}' if isinstance(conf,(float,int)) else '—'
        distance=f'{dist:.3f} m' if isinstance(dist,(float,int)) else '—'
        result+=[f'#{obj.get("track_id")} {obj.get("class_name")} | {score} | 距离 {distance} | {obj.get("color") or "—"}',
                 f'  坐标 {obj.get("position_body_m") or "—"}  框 {obj.get("bbox_xyxy") or "—"}']
    if not current:result+=['等待目标进入画面。']
    return result


def pages_for(sections, columns, capacity):
    pages=[]
    for name,lines in sections:
        wrapped=[]
        for line in lines:wrapped+=wrap(line,max(12,columns-1))
        for offset in range(0,max(1,len(wrapped)),capacity):
            pages.append((name,wrapped[offset:offset+capacity] or ['等待数据。']))
    return pages


def run(root, group, title, intro, yolo_reader):
    state=State(group) if group!='yolo' else None
    logs=Logs(root);last_screen='';last_poll=0;data={};recent=None
    interactive=sys.stdout.isatty();keyboard=None;old_terminal=None
    old_signals={}
    def leave(_sig=None,_frame=None):raise KeyboardInterrupt
    for sig in (signal.SIGTERM,signal.SIGHUP):old_signals[sig]=signal.signal(sig,leave)
    page=0;automatic=True;last_flip=time.monotonic();last_anchor=None
    if os.name=='posix' and sys.stdin.isatty():
        import termios
        import tty
        keyboard=sys.stdin.fileno();old_terminal=termios.tcgetattr(keyboard)
        tty.setcbreak(keyboard)
    if interactive:sys.stdout.write('\033[?1049h\033[?25l');sys.stdout.flush()
    try:
        while True:
            key=b''
            if keyboard is not None and select.select([keyboard],[],[],0)[0]:
                key=os.read(keyboard,32)
                if not key:break
                if key.lower()==b'q':break
                if key==b' ':
                    automatic=not automatic;last_flip=time.monotonic()
                if key.lower() in (b'n',b'\t',b'\x1b[c',b'\x1b[6~'):
                    page+=1;automatic=False
                if key.lower() in (b'p',b'\x1b[d',b'\x1b[5~'):
                    page-=1;automatic=False
                if key.lower() in (b'r',b'\x1b[h'):
                    page=0;automatic=False
            if group=='yolo':
                if time.monotonic()-last_poll>=1:
                    last_poll=time.monotonic()
                    try:
                        data=yolo_reader(root)
                        if data.get('objects'):recent=(time.monotonic(),data['objects'])
                    except Exception as exc:data={'status':'unavailable','error':str(exc)}
                lines=yolo_lines(data,recent)
                if data.get('error'):lines=['状态：连接失败','错误：'+data['error']]
                stamp=clock(data.get('frame_timestamp'))
                status=lines[0]
                diagnostic=[]
                for key_name,label in (('source','检测来源'),('frame_id','相机坐标系'),('frame_timestamp','检测时间'),
                    ('camera_running','相机进程'),('image_age_s','图像年龄s'),('fresh','结果新鲜'),
                    ('detect_fps','检测FPS'),('target_task','任务检测模式'),('stream_frames','视频累计帧'),
                    ('stream_dropped','视频丢弃帧'),('last_reported_object_count','最近上报目标数')):
                    value=data.get(key_name)
                    if value is not None:diagnostic.append(label+'：'+('是' if value is True else '否' if value is False else str(value)))
                sections=[('目标',lines[1:]),('参数',diagnostic or ['等待检测参数。'])]
                anchor=None
            else:
                for item in logs.read():state.event(item)
                status,sections=state.sections();stamp=state.at
                anchor=(state.trace,state.output,state.error)
            if automatic and anchor!=last_anchor:
                page=0;last_flip=time.monotonic()
            last_anchor=anchor
            cols,rows=shutil.get_terminal_size((80,24))
            pages=pages_for(sections,cols,max(1,rows-4))
            if automatic and time.monotonic()-last_flip>=6:
                page+=1;last_flip=time.monotonic()
            page%=len(pages)
            name,content=pages[page]
            header=wrap(title.split(' ',1)[-1]+'  '+stamp,cols-1)[0]
            label=f'[{name} {page+1}/{len(pages)} '+('轮播' if automatic else '手动')+']'
            subtitle=wrap(label+' '+intro,cols-1)[0]
            footer='N/P 翻页  空格'+('暂停轮播' if automatic else '恢复轮播')+'  R返回'
            body=[header,subtitle,wrap(status,cols-1)[0]]+content
            body+=['']*max(0,rows-1-len(body))
            body+=[wrap(footer,cols-1)[0]]
            screen='\n'.join(text(x) for x in body)
            if screen!=last_screen:
                if interactive:
                    colored=['\033[1;36m'+text(body[0])+'\033[0m',
                             '\033[38;5;250m'+text(body[1])+'\033[0m']
                    colored += [text(x) for x in body[2:-1]]
                    colored += ['\033[38;5;250m'+text(body[-1])+'\033[0m']
                    sys.stdout.write('\033[H'+'\n'.join('\033[2K'+line for line in colored)+'\033[J');sys.stdout.flush()
                else:print(screen,flush=True)
                last_screen=screen
            time.sleep(.15)
    except KeyboardInterrupt:pass
    finally:
        logs.close()
        if old_terminal is not None:
            try:termios.tcsetattr(keyboard,termios.TCSADRAIN,old_terminal)
            except OSError:pass
        for sig,handler in old_signals.items():signal.signal(sig,handler)
        if interactive:sys.stdout.write('\033[?25h\033[?1049l');sys.stdout.flush()
