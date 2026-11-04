"""新方式だけを実照会し、旧方式はローカル生成で送信量を比較するCLI。"""
import argparse
import ast
from dataclasses import replace
from html import escape
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'backend'))
import lab
from adjudication import canonical,candidates,decide
from reading_input import ReadingInput,review_payload
from reviewers import Config,ReviewClients,PROMPT
import llm_records

BASE=[('雨衣','ウイ'),('値','アタイ'),('HTTPover','エイチティーティーピーオーバー'),('①','マルイチ'),('③','マルサン'),('１～３','イチカラサン')]
CASES=[
 {'id':'locked','text':'雨衣、値、HTTPover、①、③、１～３。','reading':'ウイアタイエイチティーティーピーオーバーマルイチマルサンイチカラサン','targets':dict(BASE)},
 {'id':'stage','text':'雨衣で舞台の上手に立つ。','reading':'ウイデブタイノカミテニタツ','targets':{'上手':'カミテ'}},
 {'id':'skill','text':'彼は歌が上手です。','reading':'カレワウタガジョーズデス','targets':{'上手':'ジョーズ'}},
 {'id':'phrase','text':'舞台の上手に立つ。彼は歌が上手です。','reading':'ブタイノカミテニタツカレワウタガジョーズデス','targets':{'立つ':'タツ'},'entries':[('舞台の上手','ブタイノカミテ'),('上手','ジョウズ')]},
 {'id':'multiline','text':'雨衣を着る。\n\n値を確認する。','reading':'ウイオキルアタイオカクニンスル','targets':{'確認する':'カクニンスル'}},
 {'id':'ambiguous','text':'舞台の上手に立つ。彼は歌が上手です。','reading':'ブタイノカミテニタツカレワウタガジョーズデス','targets':{'上手':None}},
]


def size(text):return len(text.encode('utf-8'))
def same(a,b):return canonical(lab.normalize_kana(a).replace('ヲ','オ'))==canonical(lab.normalize_kana(b).replace('ヲ','オ'))


def constants(ref,file):
    source=subprocess.check_output(['git','-C',str(ROOT),'show',ref+':backend/'+file],text=True,encoding='utf-8')
    result={}
    for node in ast.parse(source).body:
        if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
            for target in node.targets:
                if isinstance(target,ast.Name):result[target.id]=node.value.value
    return result


def legacy_prompt(original,table,old):
    hints=[];seen=set()
    for row in table['rows']:
        key=lab.width_key(row[1])
        if key in lab.width_key(original) and key not in seen:
            hints.append({'surface':row[1],'reading':lab.kana(row[2])});seen.add(key)
    return old['RULES']+'\n'+old['DICTIONARY_INSTRUCTION']+'\n'+old['REFERENCE_INSTRUCTION']+'\n登録済みユーザー辞書テーブル（JSON）:\n'+json.dumps(table,ensure_ascii=False)+'\n入力JSON:\n'+json.dumps({'original':original,'known_readings':hints},ensure_ascii=False)


def measure(case,table,old,old_review):
    original=case['text'];plan=ReadingInput(original,table)
    primary=lab.Llm(ROOT,'measurement-only',Path('.'),table)
    prepared=plan.request()
    new_primary=primary.build_prompt(lab.REFERENCE_INSTRUCTION,prepared) if plan.queries else ''
    payload,resolved=review_payload(original,table,list(case['targets']))
    new_review=PROMPT+'\n入力JSON:\n'+json.dumps(payload,ensure_ascii=False) if payload['targets'] else ''
    old_primary=legacy_prompt(original,table,old)
    old_secondary=old_review+'\n入力JSON:\n'+json.dumps({'original':original,'registered_user_dictionary':table,'surfaces':list(case['targets'])},ensure_ascii=False)
    before=size(old_primary)+2*size(old_secondary);after=size(new_primary)+2*size(new_review)
    return {'dictionary_rows':len(table['rows']),'old_prompt_utf8_bytes':before,'new_prompt_utf8_bytes':after,
            'reduction_percent':round((1-after/before)*100,3),'old_requests':3,
            'new_requests':int(bool(new_primary))+2*int(bool(new_review)),
            'unknown_segments':len(plan.queries),'unknown_targets':payload['targets'],'prepared_text':plan.prepared(),
            'local_readings':resolved},new_primary,new_review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--compare-asr',action='store_true',help='固定した誤読・一致の文字起こしを実LLMで比較する（実音声認識ではない）')
    parser.add_argument('--filler-entries',type=int,default=3000)
    parser.add_argument('--baseline-ref',default='v0.0.2')
    parser.add_argument('--primary-model',default='gpt-5.6-luna')
    parser.add_argument('--reviewer-env',type=Path,default=Path('C:/AI/env/ReadingRepair/reviewers.env'))
    parser.add_argument('--dictionary-file',type=Path)
    parser.add_argument('--case',action='append')
    args=parser.parse_args()
    if not 0<=args.filler_entries<=20000:parser.error('filler-entriesは0～20000')
    if args.compare_asr and not args.live:parser.error('compare-asrにはliveが必要です。')
    output=args.output.resolve()
    if output.exists():parser.error('既存記録を上書きしません。新しい出力先を指定してください。')
    if 'logs' not in output.parts or 'history' not in output.parts:parser.error('出力は版別historyのlogs内へ指定してください。')
    output.mkdir(parents=True)
    old=constants(args.baseline_ref,'lab.py');old_review=constants(args.baseline_ref,'reviewers.py')['PROMPT']
    cfg=replace(Config.load(args.reviewer_env),gemini_transport='api',timeout=60) if args.live else None
    records=[]
    for case in CASES:
        if args.case and case['id'] not in args.case:continue
        folder=output/case['id'];folder.mkdir()
        entries=BASE+case.get('entries',[])+[(f'検証専用未出現語{i:05d}','ミシュツゲンゴ') for i in range(args.filler_entries)]
        table={'columns':['優先順位','表記','読み','アクセント核'],'rows':[[i+1,s,r,0] for i,(s,r) in enumerate(entries)]}
        stats,primary_prompt,secondary_prompt=measure(case,table,old,old_review)
        # 送信予定の本文を先に検査する。無関係な辞書項目は一件も含めない。
        if '検証専用未出現語' in primary_prompt+secondary_prompt:raise ValueError('無関係な辞書項目が送信候補に混入しています。')
        (folder/'primary-proposed.txt').write_text(primary_prompt,encoding='utf-8')
        (folder/'secondary-proposed.txt').write_text(secondary_prompt,encoding='utf-8')
        row={'id':case['id'],'original':case['text'],'gold_reading':case['reading'],'measurement':stats,'live':args.live}
        print(json.dumps({'case':case['id'],'stage':'measurement','old_bytes':stats['old_prompt_utf8_bytes'],'new_bytes':stats['new_prompt_utf8_bytes']},ensure_ascii=False),flush=True)
        if args.live:
            print(json.dumps({'case':case['id'],'stage':'primary-started'},ensure_ascii=False),flush=True)
            client=lab.Llm(ROOT,args.primary_model,folder,table);client.record_redact=cfg.redact
            try:
                value=lab.reference_checked(case['text'],client.ask('reference',lab.REFERENCE_INSTRUCTION,{'original':case['text']}))
                row['primary']={'result':value,'correct':same(value['reading'],case['reading'])}
            except Exception as error:row['primary']={'correct':False,'error_type':type(error).__name__}
            print(json.dumps({'case':case['id'],'stage':'secondary-started','primary_correct':row['primary']['correct']},ensure_ascii=False),flush=True)
            review=ReviewClients(cfg,folder/'llm').review(case['text'],table,list(case['targets']))
            row['secondary']=review
            checks=[]
            for provider in review['providers']:
                opinions={op['surface']:op for op in provider['opinions']}
                correct=provider['status']=='ok'
                for surface in stats['unknown_targets']:
                    opinion=opinions.get(surface);gold=case['targets'][surface]
                    correct=correct and opinion is not None and (opinion['uncertain'] if gold is None else not opinion['uncertain'] and same(opinion['reading'],gold))
                checks.append({'provider':provider['provider'],'correct':bool(correct),'status':provider['status'],'expected_abstention':any(v is None for v in case['targets'].values())})
            row['secondary_checks']=checks
            # 合格条件は全APIの稼働ではなく、実装と同じ二票一致／曖昧語保留で判定する。
            decision_checks=[]
            reference=row['primary'].get('result',{'words':[]})
            for surface in stats['unknown_targets']:
                gold=case['targets'][surface]
                choices=[w['reading'] for w in reference['words'] if w['surface']==surface]
                comparison={'errors':[{'surface':surface,'expected_reading':choices[0] if choices else '',
                                       'observed_reading':'イチジテキナヒカクヨウノヨミ','evidence':'音声ではない判定ロジック試験入力'}]}
                items=[i for i in candidates(case['text'],reference,comparison,{'supported':False}) if i['surface']==surface]
                result=decide(items,review,{})
                correct=bool(items) and (result['status']=='pending_confirmation' if gold is None else
                    result['status']=='resolved' and all(d['status']=='accepted' and same(d['accepted_reading'],gold) and len(d['votes'])>=2 for d in result['decisions']))
                decision_checks.append({'surface':surface,'correct':correct,'expected':'pending_confirmation' if gold is None else gold,'result':result})
            row['decision_checks']=decision_checks
            calls=llm_records.read(folder)['calls']
            row['actual_prompt_utf8_bytes']=sum(c.get('prompt_utf8_bytes',0) for c in calls if c['request_kind']=='actual_prompt')
            row['actual_requests']=sum(c['request_kind']=='actual_prompt' for c in calls)
            row['passed']=row['primary']['correct'] and all(c['correct'] for c in decision_checks)
            row=cfg.redact(row)
        records.append(row)
        (folder/'result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'case':case['id'],'stage':'complete','passed':row.get('passed'),'reduction_percent':stats['reduction_percent']},ensure_ascii=False),flush=True)
    if not records:parser.error('対象ケースがありません。')
    before=sum(r['measurement']['old_prompt_utf8_bytes'] for r in records)
    after=sum(r['measurement']['new_prompt_utf8_bytes'] for r in records)
    report={'contract':lab.PROMPT_CONTRACT,'baseline_ref':args.baseline_ref,'live':args.live,
            'measurement_scope':'基準生成と二次2モデル。UTF-8プロンプト本文。旧方式はローカル生成のみ。',
            'old_prompt_utf8_bytes':before,'new_prompt_utf8_bytes':after,'reduction_percent':round((1-after/before)*100,3),
            'old_requests':sum(r['measurement']['old_requests'] for r in records),'new_requests':sum(r['measurement']['new_requests'] for r in records),
            'cases':records,'limitations':['固定した有限の正解例による検証。一般の読み精度の統計的保証ではない。','実APIの失敗・判断不能は正解に数えない。','実TTSの追加合成・Whisperの新規認識・実辞書更新は本試験では行わない。']}
    if args.live:
        report.update(passed=all(r['passed'] for r in records),primary_correct=sum(r['primary']['correct'] for r in records),
                      secondary_correct=sum(c['correct'] for r in records for c in r['secondary_checks']),
                      secondary_correct_readings=sum(c['correct'] and not c['expected_abstention'] for r in records for c in r['secondary_checks']),
                      secondary_expected_abstentions=sum(c['correct'] and c['expected_abstention'] for r in records for c in r['secondary_checks']),
                      secondary_checks=sum(len(r['secondary_checks']) for r in records),
                      actual_requests=sum(r['actual_requests'] for r in records),actual_prompt_utf8_bytes=sum(r['actual_prompt_utf8_bytes'] for r in records),
                      secondary_unavailable=sum(c['status']!='ok' for r in records for c in r['secondary_checks']),
                      decision_correct=sum(c['correct'] for r in records for c in r['decision_checks']))
    if args.compare_asr:
        folder=output/'asr-comparison';folder.mkdir()
        client=lab.Llm(ROOT,args.primary_model,folder,{'rows':[[1,'雨衣','ウイ',0],[2,'値','アタイ',0]]})
        client.record_redact=cfg.redact
        original='雨衣と値'
        reference={'reading':'ウイトアタイ','words':[{'surface':'雨衣','reading':'ウイ'},{'surface':'値','reading':'アタイ'}]}
        comparisons={}
        for label,observed in (('before','アマギヌトアタイ'),('after','ウイトアタイ')):
            print(json.dumps({'stage':'asr-comparison','phase':label},ensure_ascii=False),flush=True)
            try:
                value=lab.comparison_checked(original,reference,client.ask('comparison-'+label,lab.COMPARE_INSTRUCTION,
                    {'original':original,'reference_1':reference,'whisper_transcript':observed}))
                passed=same(value['observed_reading'],observed) and (bool(value['errors']) and value['metrics']['kana_match_percent']<100 if label=='before' else not value['errors'] and value['metrics']['kana_match_percent']==100)
                comparisons[label]={'passed':bool(passed),'input_transcript':observed,'result':value}
            except Exception as error:comparisons[label]={'passed':False,'error_type':type(error).__name__}
        comparisons['passed']=all(comparisons[label]['passed'] for label in ('before','after'))
        comparisons['source']='固定した試験用文字起こし。実音声の認識結果ではない。'
        additional_calls=[c for c in llm_records.read(folder)['calls'] if c['request_kind']=='actual_prompt']
        comparisons['actual_requests']=len(additional_calls)
        comparisons['actual_prompt_utf8_bytes']=sum(c['prompt_utf8_bytes'] for c in additional_calls)
        report['asr_comparison']=comparisons
        report['passed']=report['passed'] and comparisons['passed']
    if args.live:
        report['total_actual_requests']=report['actual_requests']+report.get('asr_comparison',{}).get('actual_requests',0)
        report['total_actual_prompt_utf8_bytes']=report['actual_prompt_utf8_bytes']+report.get('asr_comparison',{}).get('actual_prompt_utf8_bytes',0)
    if args.dictionary_file:
        snapshot=lab.dictionary_snapshot(args.dictionary_file,CASES[1]['text'])
        actual,_,_=measure(CASES[1],snapshot['table'],old,old_review)
        report['actual_dictionary_local_measurement']={**actual,'dictionary_sha256':snapshot['dictionary_sha256'],'sent':False}
    (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    sections=[]
    for row in records:
        text=json.dumps(row,ensure_ascii=False,indent=2)
        sections.append('<section><h2>'+escape(row['id'])+'</h2><p>原文を保持し、登録済み読みを事前適用してから未確定部分だけを照会しました。</p><pre>'+escape(text)+'</pre></section>')
    html='<!doctype html><html lang="ja"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>ReadingRepair 読み照会検証</title><style>body{max-width:1100px;margin:2em auto;font:16px/1.8 sans-serif}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f8;padding:1em}section{border-top:1px solid #ccd}</style><h1>読み照会と送信量の検証</h1><p>'+escape(report['measurement_scope'])+'</p><pre>'+escape(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False,indent=2))+'</pre>'+''.join(sections)+'</html>'
    (output/'index.html').write_text(html,encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','limitations','actual_dictionary_local_measurement')},ensure_ascii=False),flush=True)
    return 0 if not args.live or report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
