"""LLMの呼び出しごとの送受信を、認証値を除外して保管する。"""
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import uuid


def save(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def begin(root,provider,stage,model,prompt,redact=lambda value:value):
    if root is None:return None
    identifier=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'-'+provider+'-'+uuid.uuid4().hex[:8]
    folder=Path(root)/'calls'/identifier;folder.mkdir(parents=True)
    metadata={'id':identifier,'provider':provider,'stage':stage,'model':model,'status':'running',
              'started_at':datetime.now(timezone.utc).isoformat(timespec='milliseconds'),'request_kind':'actual_prompt' if prompt is not None else 'not_sent'}
    if prompt is not None:
        prompt=redact(prompt)
        metadata.update(prompt_characters=len(prompt),prompt_utf8_bytes=len(prompt.encode('utf-8')))
        (folder/'request.txt').write_text(prompt,encoding='utf-8',newline='\n')
    save(folder/'metadata.json',redact(metadata))
    return folder


def finish(folder,status,response=None,response_kind='raw_text',model=None,error_type=None,http_status=None,redact=lambda value:value):
    if folder is None:return
    metadata=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
    metadata.update(status=status,response_kind=response_kind,finished_at=datetime.now(timezone.utc).isoformat(timespec='milliseconds'))
    if model:metadata['model']=model
    if error_type:metadata['error_type']=error_type
    if http_status is not None:metadata['http_status']=http_status
    if response is not None:
        value=response if isinstance(response,str) else json.dumps(response,ensure_ascii=False,indent=2)
        (folder/'response.txt').write_text(redact(value),encoding='utf-8',newline='\n')
    save(folder/'metadata.json',redact(metadata))


def archive_primary(root,stage,model,prompt_path,response_path,redact):
    if not prompt_path.is_file() or not response_path.is_file():return
    for metadata in (root/'calls').glob('*/metadata.json'):
        value=json.loads(metadata.read_text(encoding='utf-8'))
        if value.get('provider')=='primary' and value.get('stage')==stage:return
    record=begin(root,'primary',stage,model,read_text(prompt_path),redact)
    finish(record,'saved',read_text(response_path),redact=redact)
    value=json.loads((record/'metadata.json').read_text(encoding='utf-8'))
    value.update(request_kind='saved_prompt',started_at=None,finished_at=None)
    save(record/'metadata.json',value)


def read_text(path):
    if not path.is_file() or path.is_symlink():return ''
    if path.stat().st_size>4*1024*1024:return '表示上限4MiBを超えるため、本文は表示していません。'
    return path.read_text(encoding='utf-8-sig')


def read(folder,primary_model=''):
    root=folder/'llm';calls=[];recorded_stages=set()
    for path in sorted((root/'calls').glob('*'),reverse=True):
        if path.is_symlink() or not path.is_dir() or not re.fullmatch(r'\d{8}T\d{12}-[a-z]+-[a-f0-9]{8}',path.name):continue
        metadata=path/'metadata.json'
        if not metadata.is_file() or metadata.is_symlink():continue
        value=json.loads(metadata.read_text(encoding='utf-8'))
        value.update(request=read_text(path/'request.txt'),response='' if value.get('status')=='running' else read_text(path/'response.txt'))
        calls.append(value);recorded_stages.add((value['provider'],value['stage']))
    # 旧記録も表示するが、当時の完全な送受信と復元情報を区別する。
    for path in sorted(root.glob('*.prompt.txt')):
        stem=path.name.removesuffix('.prompt.txt')
        if not re.fullmatch(r'(reference(?:-adopted|-final)?|comparison-(?:1-2|1-3|adopted-before|final-before|final-after)|registration-plan)',stem):continue
        stage='reference-1' if stem=='reference' else stem
        if ('primary',stage) in recorded_stages:continue
        calls.append({'id':'legacy-'+stem,'provider':'primary','stage':stage,'model':primary_model,'status':'saved',
                      'request_kind':'saved_prompt','response_kind':'raw_text','request':read_text(path),'response':read_text(root/(stem+'.raw.txt'))})
    for name in ('secondary-review','post-secondary-review'):
        path=folder/(name+'.json')
        if not path.is_file():continue
        review=json.loads(path.read_text(encoding='utf-8-sig'))
        for provider in review.get('providers',[]):
            if (provider['provider'],name) in recorded_stages:continue
            calls.append({'id':'legacy-'+name+'-'+provider['provider'],'provider':provider['provider'],'stage':name,
                'model':provider.get('model',review.get('configuration',{}).get(provider['provider'],{}).get('model','未記録')),
                'status':provider['status'],'request_kind':'reconstructed_payload','response_kind':'validated_result',
                'request':'当時のプロンプト本文は未保存です。保存済み入力JSON：\n'+json.dumps(review.get('independent_payload',{}),ensure_ascii=False,indent=2),
                'response':json.dumps(provider,ensure_ascii=False,indent=2)})
    return {'calls':calls}
