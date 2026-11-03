"""Compact terminal presentation of existing processing events."""
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys
import time
import unicodedata


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

    def event(self, item):
        if item.get('stage') != {'asr':'ASR','llm':'LLM','task':'TASK','tts':'TTS'}[self.group]:
            return
        data=item.get('data',{});event=item.get('event','');identity=item.get('trace','')
        if identity and identity != self.trace:
            self.__init__(self.group)
            self.trace=identity
        self.at=clock(item.get('at'))
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
                self.phase='规则解析' if result.get('parser')=='rule' else '完成'
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


def run(root, group, title, intro, yolo_reader):
    state=State(group) if group!='yolo' else None
    logs=Logs(root);last_screen='';last_poll=0;data={};recent=None
    tty=sys.stdout.isatty()
    if tty:sys.stdout.write('\033[?1049h\033[?25l');sys.stdout.flush()
    try:
        while True:
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
            else:
                for item in logs.read():state.event(item)
                lines=state.lines();stamp=state.at
            cols,rows=shutil.get_terminal_size((80,24))
            header=title.split(' ',1)[-1]+'  '+stamp
            body=[header,intro]
            for line in lines:body+=wrap(line,max(12,cols-1))
            if len(body)>rows:
                body=body[:max(1,rows)]
                body[-1]=wrap(body[-1],max(10,cols-3))[0]+' …'
            screen='\n'.join(text(x) for x in body)
            if screen!=last_screen:
                if tty:
                    colored='\033[1;36m'+text(body[0])+'\033[0m\n\033[38;5;250m'+text(body[1])+'\033[0m'
                    if len(body)>2:colored+='\n'+'\n'.join(text(x) for x in body[2:])
                    sys.stdout.write('\033[H'+colored+'\033[J');sys.stdout.flush()
                else:print(screen,flush=True)
                last_screen=screen
            time.sleep(.15)
    except KeyboardInterrupt:pass
    finally:
        logs.close()
        if tty:sys.stdout.write('\033[?25h\033[?1049l');sys.stdout.flush()
