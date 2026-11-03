"""外部サービス・実辞書を使わない一巡試験。回答はすべて模擬データ。"""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import wave

import lab


class Simulation:
    def __init__(self, root, reviewers_available=True, apply_registration=True):
        self.root=root; self.available=reviewers_available; self.apply_registration=apply_registration
        self.registered=False; self.registrations=0; self.syntheses=0
        self.args=SimpleNamespace(project_root=root, text_file=root/'input.txt',run_dir=root/'run',llm_model='simulation',
            whisper_model=root/'small',voice='ui_ja_JP',voice_version='2.0.0',resume=False,whisper_site_packages=None,
            reviewer_env=root/'review.env',answers_file=None,retry_reviewers=False,apply=True,prepare_only=False,dictionary_file=root/'dictionary.dic')
        self.args.text_file.write_text('上手',encoding='utf-8');self.args.dictionary_file.write_text('',encoding='utf-8')
        dll=root/'Registration/bin/Debug/net10.0-windows/Registration.dll';dll.parent.mkdir(parents=True);dll.write_bytes(b'simulation')

    def call(self,*args):return {'items':[]}
    def synthesize(self,text,path):
        self.syntheses+=1
        with wave.open(str(path),'wb') as target:
            target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000);target.writeframes(b'\x10\x00'*160)
    def analyze(self,text):
        reading='カミテ' if self.registered and self.apply_registration else 'ジョーズ'
        return {'analyzed_text':f'<tsml><word pronunciation="{reading}">上手</word></tsml>'}
    def transcribe(self,path):
        reading='カミテ' if path.name.startswith('after') and self.registered and self.apply_registration else 'ジョーズ'
        return {'text':reading,'segments':[],'duration':.01}
    def ask(self,name,instruction,payload):
        if name.startswith('reference'):
            accepted=payload.get('accepted_readings',[])
            reading=accepted[0]['reading'] if accepted else 'カミテ'
            return {'reading':reading,'words':[{'surface':'上手','reading':reading}]}
        if name=='registration-plan':
            return {'entries':[{'surface':e['surface'],'reading':e['expected_reading']} for e in payload['approved']['errors']]}
        reference=payload['reference_1']['words'][0]['reading'];observed=payload['whisper_transcript']
        errors=[] if lab.normalize_kana(reference)==lab.normalize_kana(observed) else [{'surface':'上手','expected_reading':reference,'observed_reading':observed,'evidence':'模擬データ'}]
        return {'observed_reading':observed,'score':40 if errors else 100,'explanation':'外部LLMではなく模擬応答','errors':errors}
    def review(self,*args):
        return {'providers':[{'provider':p,'status':'ok' if self.available else 'not_configured',
            'opinions':[{'surface':'上手','reading':'カミテ','reason':'模擬応答','uncertain':False}] if self.available else []} for p in ('gemini','sarashina')]}
    def subprocess(self,command,**kwargs):
        assert command[0]=='dotnet' and command[2]=='register'
        self.registrations+=1;self.registered=True
        plan=lab.load(Path(command[3]));journal=Path(command[4]);journal.parent.mkdir(parents=True)
        self.args.dictionary_file.write_text(''.join(f'{e["surface"]} [{e["reading"]}] ACCENT="0"\n' for e in plan['entries']),encoding='utf-8')
        lab.save(journal,{'entries':[{**e,'state':'registered','elapsedMs':0} for e in plan['entries']],'method':'simulation'})
    def execute(self):
        with ExitStack() as stack:
            stack.enter_context(patch('lab.HERE',self.root))
            stack.enter_context(patch('lab.TalkApi',lambda *a:self))
            stack.enter_context(patch('lab.Llm',lambda *a:self))
            stack.enter_context(patch('lab.Whisper',lambda *a:self))
            stack.enter_context(patch('lab.ReviewClients.review',side_effect=self.review))
            stack.enter_context(patch('lab.subprocess.run',side_effect=self.subprocess))
            stack.enter_context(redirect_stdout(io.StringIO()))
            lab.run(self.args)
        return lab.load(self.args.run_dir/'manifest.json')
    def answer(self,reading):
        template=lab.load(self.args.run_dir/'answers-template.json')
        template['answers'][0].update(action='accept',reading=reading,reason='統合試験の模擬回答。ユーザーの実際の判断ではない。')
        path=self.root/'answers.json';lab.save(path,template);self.args.answers_file=path;self.args.resume=True


class PhraseSimulation(Simulation):
    def __init__(self, root):
        super().__init__(root,False)
        self.args.text_file.write_text('舞台の上手です。彼は歌が上手です。',encoding='utf-8')
        self.args.dictionary_file.write_text('上手 [ジョウズ] ACCENT="0"\n',encoding='utf-8')
    def analyze(self,text):
        first='<word pronunciation="ブタイノカミテ">舞台の上手</word>' if self.registered else '<word pronunciation="ブタイ">舞台</word><word pronunciation="ノ">の</word><word pronunciation="ジョウズ">上手</word>'
        return {'analyzed_text':'<tsml>'+first+'<word pronunciation="デス">です</word><word pronunciation="">。</word><word pronunciation="カレ">彼</word><word pronunciation="ワ">は</word><word pronunciation="ウタ">歌</word><word pronunciation="ガ">が</word><word pronunciation="ジョウズ">上手</word><word pronunciation="デス">です</word><word pronunciation="">。</word></tsml>'}
    def transcribe(self,path):
        first='カミテ' if path.name.startswith('after') and self.registered else 'ジョウズ'
        return {'text':'ブタイノ'+first+'デスカレワウタガジョウズデス','segments':[]}
    def ask(self,name,instruction,payload):
        if name.startswith('reference'):
            words=[{'surface':'上手','reading':'ジョウズ'}]
            adopted=payload.get('accepted_readings',[])
            words+=adopted if adopted else [{'surface':'舞台','reading':'ブタイ'},{'surface':'上手','reading':'カミテ'}]
            return {'reading':'ブタイノカミテデスカレワウタガジョウズデス','words':words}
        if name=='registration-plan':return super().ask(name,instruction,payload)
        bad='ブタイノジョウズ' in payload['whisper_transcript']
        phrase=any(w['surface']=='舞台の上手' for w in payload['reference_1']['words'])
        error={'surface':'舞台の上手' if phrase else '上手','expected_reading':'ブタイノカミテ' if phrase else 'カミテ',
               'observed_reading':'ブタイノジョウズ' if phrase else 'ジョウズ','evidence':'模擬データ'}
        return {'observed_reading':payload['whisper_transcript'],'score':40 if bad else 100,'explanation':'模擬データ','errors':[error] if bad else []}
    def subprocess(self,command,**kwargs):
        previous=self.args.dictionary_file.read_text(encoding='utf-8')
        super().subprocess(command,**kwargs)
        self.args.dictionary_file.write_text(previous+self.args.dictionary_file.read_text(encoding='utf-8'),encoding='utf-8')


class PipelineTests(unittest.TestCase):
    def test_external_majority_can_regrade_primary_without_human_or_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            simulation=Simulation(Path(directory))
            simulation.review=lambda *args:{'providers':[{'provider':p,'status':'ok','opinions':[{'surface':'上手','reading':'ジョーズ','reason':'模擬の独立意見','uncertain':False}]} for p in ('gemini','sarashina')]}
            manifest=simulation.execute();self.assertEqual(manifest['status'],'completed')
            summary=lab.load(simulation.args.run_dir/'summary.json')
            self.assertEqual(summary['preliminary_before']['llm_score'],40)
            self.assertEqual((summary['before']['llm_score'],summary['after']['llm_score']),(100,100))
            self.assertEqual(summary['reference_decision']['decisions'][0]['source'],'model_majority')
            self.assertEqual(simulation.registrations,0)

    def test_phrase_entry_preserves_short_word_in_another_context(self):
        with tempfile.TemporaryDirectory() as d:
            simulation=PhraseSimulation(Path(d));simulation.execute();simulation.answer('カミテ')
            answer=lab.load(simulation.args.answers_file)
            answer['answers'][0]['registration']={'surface':'舞台の上手','reading':'ブタイノカミテ'}
            lab.save(simulation.args.answers_file,answer)
            result=simulation.execute()
            self.assertEqual(result['status'],'completed')
            plan=lab.load(simulation.args.run_dir/'registration-plan.json')
            self.assertEqual(plan['entries'],[{'surface':'舞台の上手','reading':'ブタイノカミテ'}])
            reference=lab.load(simulation.args.run_dir/'reference-final.json')
            self.assertIn({'surface':'上手','reading':'ジョウズ'},reference['words'])
            self.assertNotIn({'surface':'上手','reading':'カミテ'},reference['words'])
            dictionary=lab.dictionary_snapshot(simulation.args.dictionary_file,'上手と舞台の上手')
            self.assertEqual(dictionary['table']['rows'][0][1:3],['上手','ジョウズ'])
            self.assertEqual(simulation.registrations,1)

    def test_missing_keys_stop_before_registration_and_after_audio(self):
        with tempfile.TemporaryDirectory() as d:
            simulation=Simulation(Path(d),False);manifest=simulation.execute()
            self.assertEqual(manifest['status'],'pending_confirmation')
            self.assertEqual(simulation.registrations,0);self.assertEqual(simulation.syntheses,1)
            self.assertTrue((simulation.args.run_dir/'report/index.html').exists())

    def test_consensus_runs_one_registration_and_two_evaluations(self):
        with tempfile.TemporaryDirectory() as d:
            simulation=Simulation(Path(d));manifest=simulation.execute()
            self.assertEqual(manifest['status'],'completed');self.assertEqual(simulation.registrations,1)
            summary=lab.load(simulation.args.run_dir/'summary.json')
            self.assertEqual(summary['before']['llm_score'],40);self.assertEqual(summary['after']['llm_score'],100)

    def test_answer_resumes_without_repeating_before_synthesis(self):
        with tempfile.TemporaryDirectory() as d:
            simulation=Simulation(Path(d),False);simulation.execute();simulation.answer('カミテ')
            manifest=simulation.execute()
            self.assertEqual(manifest['status'],'completed');self.assertEqual(simulation.syntheses,2)
            self.assertEqual(simulation.registrations,1)

    def test_changed_reference_regrades_both_sides_and_keeps_old_score(self):
        with tempfile.TemporaryDirectory() as d:
            simulation=Simulation(Path(d),False);simulation.execute();simulation.answer('ジョーズ');simulation.execute()
            summary=lab.load(simulation.args.run_dir/'summary.json')
            self.assertEqual(summary['before']['llm_score'],100);self.assertEqual(summary['after']['llm_score'],100)
            self.assertEqual(summary['preliminary_before']['llm_score'],40)
            self.assertEqual(simulation.registrations,0)

    def test_failed_post_verification_does_not_auto_register_again(self):
        with tempfile.TemporaryDirectory() as d:
            simulation=Simulation(Path(d),True,False);manifest=simulation.execute()
            self.assertEqual(manifest['status'],'pending_confirmation')
            self.assertEqual(manifest['current_stage'],'post-adjudication');self.assertEqual(simulation.registrations,1)

    def test_post_answer_regrades_cached_audio_and_keeps_prior_final_score(self):
        with tempfile.TemporaryDirectory() as d:
            simulation=Simulation(Path(d),True,False);simulation.execute()
            template=lab.load(simulation.args.run_dir/'post-answers-template.json')
            template['answers'][0].update(action='accept',reading='ジョーズ',reason='登録後の模擬回答。実際のユーザー判断ではない。')
            path=simulation.root/'post-answers.json';lab.save(path,template)
            simulation.args.answers_file=path;simulation.args.resume=True
            manifest=simulation.execute()
            summary=lab.load(simulation.args.run_dir/'summary.json')
            self.assertEqual(manifest['status'],'completed')
            self.assertEqual((summary['before']['llm_score'],summary['after']['llm_score']),(100,100))
            self.assertEqual((simulation.syntheses,simulation.registrations),(2,1))
            archived=list((simulation.args.run_dir/'decision-history').glob('comparison-final-after-*.json'))
            self.assertEqual(lab.load(archived[0])['llm_score'],40)

    def test_changed_answer_before_apply_invalidates_cached_plan(self):
        with tempfile.TemporaryDirectory() as d:
            simulation=Simulation(Path(d));simulation.args.prepare_only=True;simulation.execute()
            adjudication=lab.load(simulation.args.run_dir/'adjudication.json')
            template={'format':'voisona.reading-decisions.v1','original_sha256':lab.hashlib.sha256('上手'.encode()).hexdigest(),
                      'answers':[{'id':adjudication['decisions'][0]['id'],'action':'accept','reading':'ジョーズ','reason':'模擬回答'}]}
            path=simulation.root/'answers.json';lab.save(path,template)
            simulation.args.answers_file=path;simulation.args.resume=True;simulation.args.prepare_only=False
            simulation.execute()
            self.assertEqual(simulation.registrations,0)
            self.assertEqual(lab.load(simulation.args.run_dir/'registration-plan.json')['entries'],[])
            self.assertTrue(list((simulation.args.run_dir/'decision-history').glob('registration-plan-*.json')))


if __name__=='__main__':unittest.main()
