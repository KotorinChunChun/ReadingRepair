import json
import unittest
from reading_input import ReadingInput,review_payload


def table(*entries):
    return {'columns':['優先順位','表記','読み','アクセント核'],'rows':[[i+1,s,r,0] for i,(s,r) in enumerate(entries)]}


class ReadingInputTests(unittest.TestCase):
    def test_longest_phrase_and_short_word_in_separate_contexts(self):
        p=ReadingInput('舞台の上手。歌が上手。',table(('上手','ジョウズ'),('舞台の上手','ブタイノカミテ')))
        self.assertEqual(p.prepared(),'ブタイノカミテ。歌がジョウズ。')
        self.assertEqual([(r['surface'],r['reading']) for r in p.applied],[('舞台の上手','ブタイノカミテ'),('上手','ジョウズ')])
        self.assertEqual([q['text'] for q in p.queries],['。歌が'])

    def test_first_priority_duplicate_width_and_circled_numbers(self):
        p=ReadingInput('HTTPover①１～３',table(('ＨＴＴＰｏｖｅｒ','エイチティーティーピーオーバー'),('①','マルイチ'),('１～３','イチカラサン'),('①','イチ')))
        self.assertEqual(p.merge({'segments':[]})['reading'],'エイチティーティーピーオーバーマルイチイチカラサン')
        self.assertEqual(len(p.applied),3)
        self.assertEqual(p.applied[0]['surface'],'HTTPover')

    def test_replacement_output_is_not_replaced_again(self):
        p=ReadingInput('雨衣とウイ',table(('雨衣','ウイ'),('ウイ','ベツヨミ')))
        self.assertEqual(p.prepared(),'ウイとベツヨミ')

    def test_explicit_reading_inside_long_dictionary_phrase_has_priority(self):
        p=ReadingInput('舞台の上手',table(('舞台の上手','ブタイノジョウズ')), [{'surface':'上手','reading':'カミテ'}])
        self.assertEqual(p.prepared(),'舞台のカミテ')
        self.assertEqual(p.applied[0]['source'],'accepted')

    def test_merge_keeps_dictionary_words_without_asking_model(self):
        p=ReadingInput('雨衣を着る。値',table(('雨衣','ウイ'),('値','アタイ'),('原文外','ゲンブンガイ')))
        request=p.request();self.assertNotIn('原文外',json.dumps(request,ensure_ascii=False))
        self.assertEqual(request['segments'],[{'id':'u1','text':'を着る。'}])
        result=p.merge({'segments':[{'id':'u1','reading':'ヲキル','words':[{'surface':'着る','reading':'キル'}]}]})
        self.assertEqual(result['reading'],'ウイヲキルアタイ')
        self.assertEqual(result['words'],[{'surface':'雨衣','reading':'ウイ'},{'surface':'着る','reading':'キル'},{'surface':'値','reading':'アタイ'}])

    def test_model_cannot_override_or_insert_resolved_word(self):
        p=ReadingInput('雨衣と値',table(('雨衣','ウイ'),('値','アタイ')))
        with self.assertRaises(ValueError):p.merge({'segments':[{'id':'u1','reading':'ト','words':[{'surface':'雨衣','reading':'アメギヌ'}]}]})

    def test_all_resolved_and_punctuation_require_no_queries(self):
        p=ReadingInput('雨衣、値。\n',table(('雨衣','ウイ'),('値','アタイ')))
        self.assertEqual(p.queries,[])
        self.assertEqual(p.merge({'segments':[]})['reading'],'ウイアタイ')

    def test_every_id_required_once_and_unknown_word_cannot_be_omitted(self):
        p=ReadingInput('舞台',table())
        for result in ({'segments':[]},{'segments':[{'id':'u9','reading':'ブタイ','words':[]}]},{'segments':[{'id':'u1','reading':'ブタイ','words':[]}]}):
            with self.subTest(result=result),self.assertRaises(ValueError):p.merge(result)

    def test_repeated_surfaces_and_multiline_are_preserved(self):
        original='雨衣です。\n\n雨衣と値。'
        p=ReadingInput(original,table(('雨衣','ウイ'),('値','アタイ')))
        self.assertEqual(p.original,original)
        self.assertEqual(p.prepared(),'ウイです。\n\nウイとアタイ。')
        self.assertEqual(len(p.applied),3)
        self.assertEqual(p.resolved_targets(['雨衣','値']),{'雨衣':'ウイ','値':'アタイ'})

    def test_secondary_only_queries_unknown_with_original_context(self):
        original='遠くの無関係な文。別の話。雨衣を着た。舞台の上手へ進む。歌が上手です。終わり。'
        payload,resolved=review_payload(original,table(('雨衣','ウイ'),('原文外','ゲンブンガイ')),['雨衣','上手'])
        self.assertEqual(payload['targets'],['上手']);self.assertEqual(resolved,{'雨衣':'ウイ'})
        value=json.dumps(payload,ensure_ascii=False)
        self.assertNotIn('原文外',value);self.assertNotIn('遠くの無関係',value)
        self.assertIn('舞台の上手',value);self.assertIn('歌が上手',value)
        self.assertIn('ウイを着た',value)

    def test_partial_phrase_does_not_invent_a_short_word_reading(self):
        payload,_=review_payload('舞台の上手',table(('舞台の上手','ブタイノカミテ')),['上手'])
        self.assertEqual(payload['targets'],['上手'])

    def test_adding_unrelated_dictionary_rows_cannot_change_request(self):
        base=table(('雨衣','ウイ'))
        expanded=table(('雨衣','ウイ'),*((f'未出現語{i}','ミシュツゲンゴ') for i in range(3000)))
        for method in ('request','prepared'):
            self.assertEqual(getattr(ReadingInput('雨衣と値。',base),method)(),getattr(ReadingInput('雨衣と値。',expanded),method)())


class ScopedTransportTests(unittest.TestCase):
    def test_both_secondary_providers_only_get_unknown_targets(self):
        from unittest.mock import patch
        from reviewers import ReviewClients,Config
        clients=ReviewClients(Config(gemini_key='test-g',sarashina_key='test-s'))
        sent=[]
        def respond(prompt):
            sent.append(prompt)
            return {'opinions':[{'surface':'上手','reading':'カミテ','reason':'舞台の文脈','uncertain':False}]},'test'
        with patch.object(clients,'gemini',side_effect=respond),patch.object(clients,'sarashina',side_effect=respond):
            result=clients.review('雨衣を着て舞台の上手へ。',table(('雨衣','ウイ'),('原文外','ゲンブンガイ')),['雨衣','上手'])
        self.assertEqual(len(sent),2)
        self.assertEqual(sent[0],sent[1])
        for prompt in sent:
            payload=json.loads(prompt.split('入力JSON:\n')[-1])
            self.assertEqual(payload['targets'],['上手'])
            self.assertNotIn('原文外',prompt)
            self.assertNotIn('registered_user_dictionary',prompt)
            self.assertIn('ウイを着て',prompt)
        self.assertEqual(result['locally_resolved'],{'雨衣':'ウイ'})

    def test_all_registered_targets_do_not_call_any_provider(self):
        from unittest.mock import patch
        from reviewers import ReviewClients,Config
        clients=ReviewClients(Config(gemini_key='test-g',sarashina_key='test-s'))
        with patch.object(clients,'gemini') as g,patch.object(clients,'sarashina') as s:
            result=clients.review('雨衣と値',table(('雨衣','ウイ'),('値','アタイ')),['雨衣','値'])
        g.assert_not_called();s.assert_not_called()
        self.assertEqual(result['providers'],[])
        self.assertEqual(result['input_metrics']['prompt_utf8_bytes'],0)

    def test_registered_reading_is_not_a_vote_or_a_repair_of_tts_evidence(self):
        from adjudication import candidates,decide
        ref={'reading':'ウイ','words':[{'surface':'雨衣','reading':'ウイ'}]}
        analysis={'analyzed_text':'<tsml><word pronunciation="アマギヌ">雨衣</word></tsml>'}
        comparison={'errors':[{'surface':'雨衣','expected_reading':'ウイ','observed_reading':'アマギヌ','evidence':'試験'}]}
        items=candidates('雨衣',ref,comparison,analysis)
        items[0]['locally_resolved_reading']='ウイ'
        review={'providers':[{'provider':p,'status':'ok','opinions':[{'surface':'雨衣','reading':'ウイ','uncertain':False}]} for p in ('gemini','sarashina')]}
        row=decide(items,review,{})['decisions'][0]
        self.assertEqual(row['votes'],[])
        self.assertEqual(row['status'],'pending')
        self.assertEqual(row['tts_readings'],['アマギヌ'])
        self.assertEqual(row['asr_errors'][0]['observed_reading'],'アマギヌ')
        self.assertFalse(row['needs_registration'])

    def test_primary_reconstructs_phrase_and_word_separately(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from lab import Llm
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            client=Llm(root,'test',root,table(('舞台の上手','ブタイノカミテ'),('上手','ジョウズ')))
            def respond(command,**kwargs):
                prompt=Path(command[command.index('-PromptFile')+1]).read_text(encoding='utf-8')
                payload=json.loads(prompt.split('入力JSON:\n')[-1])
                self.assertEqual([q['text'] for q in payload['segments']],['。歌が'])
                result={'segments':[{'id':'u1','reading':'ウタガ','words':[{'surface':'歌','reading':'ウタ'}]}]}
                Path(command[command.index('-OutputFile')+1]).write_text(json.dumps(result),encoding='utf-8')
            with patch('lab.subprocess.run',side_effect=respond):
                result=client.ask('reference','',{'original':'舞台の上手。歌が上手。'})
            self.assertEqual(result['reading'],'ブタイノカミテウタガジョウズ')
            self.assertIn({'surface':'上手','reading':'ジョウズ'},result['words'])
            self.assertNotIn({'surface':'上手','reading':'カミテ'},result['words'])

    def test_comparison_keeps_raw_whisper_without_dictionary_rewrite(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from lab import Llm,COMPARE_INSTRUCTION
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);client=Llm(root,'test',root,table(('雨衣','ウイ')))
            transcript='アマギヌ'
            def respond(command,**kwargs):
                prompt=Path(command[command.index('-PromptFile')+1]).read_text(encoding='utf-8')
                self.assertEqual(json.loads(prompt.split('入力JSON:\n')[-1])['whisper_transcript'],transcript)
                Path(command[command.index('-OutputFile')+1]).write_text('{}',encoding='utf-8')
            with patch('lab.subprocess.run',side_effect=respond):
                client.ask('comparison-1-2',COMPARE_INSTRUCTION,{'original':'雨衣','whisper_transcript':transcript})


class ScopedValidationRetryTests(unittest.TestCase):
    def test_context_word_leak_is_repaired_only_in_failed_segment(self):
        """実障害: Lunaが文脈の有限体を区間先頭に混ぜた応答を再現。"""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from lab import Llm
        valid={'id':'u1','reading':'コーモク','words':[{'surface':'項目','reading':'コーモク'}]}
        invalid={'id':'u2','reading':'ユーゲンタイワアンゴー',
                 'words':[{'surface':'有限体','reading':'ユーゲンタイ'},{'surface':'暗号','reading':'アンゴー'}]}
        corrected={'id':'u2','reading':'ワアンゴー','words':[{'surface':'暗号','reading':'アンゴー'}]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);client=Llm(root,'gpt-5.6-luna',root,table(('有限体','ユーゲンタイ'),('未出現秘密語','ヒミツ')))
            sent=[]
            def respond(command,**kwargs):
                prompt=Path(command[command.index('-PromptFile')+1]).read_text(encoding='utf-8')
                self.assertNotIn('未出現秘密語',prompt)
                request=json.loads(prompt.split('入力JSON:\n')[-1]);sent.append(request)
                reply={'segments':[valid,invalid]} if len(sent)==1 else {'segments':[corrected]}
                Path(command[command.index('-OutputFile')+1]).write_text(json.dumps(reply),encoding='utf-8')
            with patch('lab.subprocess.run',side_effect=respond):
                result=client.ask('reference','',{'original':'項目有限体は暗号'})
            self.assertEqual(len(sent),2)
            self.assertEqual(sent[1]['segments'],[{'id':'u2','text':'は暗号'}])
            self.assertEqual(sent[1]['previous_response'],{'segments':[invalid]})
            self.assertEqual(sent[1]['validation_error']['invalid_surface'],'有限体')
            self.assertNotIn('expected_reading',json.dumps(sent[1]))
            self.assertEqual(result['reading'],'コーモクユーゲンタイワアンゴー')
            self.assertEqual(result['words'].count({'surface':'有限体','reading':'ユーゲンタイ'}),1)
            self.assertEqual(json.loads((root/'llm/reference.validation.json').read_text())['status'],'corrected')

    def test_segment_retry_cannot_replace_a_valid_other_segment(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from lab import Llm
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);client=Llm(root,'test',root,table(('有限体','ユーゲンタイ')))
            replies=[{'segments':[{'id':'u1','reading':'コーモク','words':[{'surface':'項目','reading':'コーモク'}]},
                                  {'id':'u2','reading':'ワアンゴー','words':[]}]},
                     {'segments':[{'id':'u1','reading':'カイザン','words':[{'surface':'項目','reading':'カイザン'}]},
                                  {'id':'u2','reading':'ワアンゴー','words':[{'surface':'暗号','reading':'アンゴー'}]}]}]
            def respond(command,**kwargs):
                Path(command[command.index('-OutputFile')+1]).write_text(json.dumps(replies.pop(0)),encoding='utf-8')
            with patch('lab.subprocess.run',side_effect=respond) as transport,self.assertRaisesRegex(ValueError,'訂正応答'):
                client.ask('reference','',{'original':'項目有限体は暗号'})
            self.assertEqual(transport.call_count,2)
            self.assertFalse((root/'llm/reference.merged.json').exists())

    def test_missing_word_retries_once_without_expected_reading_or_full_table(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from lab import Llm
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);client=Llm(root,'test',root,table(('原文外','ゲンブンガイ')))
            replies=[{'segments':[{'id':'u1','reading':'タツ','words':[]}]},
                     {'segments':[{'id':'u1','reading':'タツ','words':[{'surface':'立つ','reading':'タツ'}]}]}]
            def respond(command,**kwargs):
                prompt=Path(command[command.index('-PromptFile')+1]).read_text(encoding='utf-8')
                self.assertNotIn('原文外',prompt)
                Path(command[command.index('-OutputFile')+1]).write_text(json.dumps(replies.pop(0)),encoding='utf-8')
            with patch('lab.subprocess.run',side_effect=respond) as transport:
                result=client.ask('reference','',{'original':'立つ'})
            self.assertEqual(transport.call_count,2)
            self.assertEqual(result['reading'],'タツ')
            self.assertTrue((root/'llm/reference.validation.json').is_file())

    def test_still_missing_word_is_rejected_after_one_retry(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from lab import Llm
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);client=Llm(root,'test',root,{'rows':[]})
            def respond(command,**kwargs):
                Path(command[command.index('-OutputFile')+1]).write_text('{"segments":[{"id":"u1","reading":"タツ","words":[]}]}',encoding='utf-8')
            with patch('lab.subprocess.run',side_effect=respond) as transport,self.assertRaises(ValueError):
                client.ask('reference','',{'original':'立つ'})
            self.assertEqual(transport.call_count,2)


class ScopedPipelineTests(unittest.TestCase):
    def test_real_prompt_builder_runs_registration_and_two_evaluations(self):
        import tempfile
        import io
        from pathlib import Path
        from contextlib import ExitStack,redirect_stdout
        from unittest.mock import patch
        import lab
        import llm_records
        from reviewers import Config,ReviewClients
        from test_pipeline import Simulation
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);simulation=Simulation(root)
            simulation.args.dictionary_file.write_text('原文外 [ゲンブンガイ] ACCENT="0"\n',encoding='utf-8')
            prompts=[]
            def transport(command,**kwargs):
                if command[0]=='dotnet':return simulation.subprocess(command,**kwargs)
                prompt=Path(command[command.index('-PromptFile')+1]).read_text(encoding='utf-8')
                self.assertNotIn('原文外',prompt);prompts.append(prompt)
                payload=json.loads(prompt.split('入力JSON:\n')[-1])
                if 'segments' in payload:
                    value={'segments':[{'id':'u1','reading':'カミテ','words':[{'surface':'上手','reading':'カミテ'}]}]}
                else:
                    observed=payload['whisper_transcript'];error=observed!='カミテ'
                    value={'observed_reading':observed,'score':40 if error else 100,'explanation':'模擬の比較応答',
                           'errors':[{'surface':'上手','expected_reading':'カミテ','observed_reading':observed,'evidence':'模擬の音声認識'}] if error else []}
                Path(command[command.index('-OutputFile')+1]).write_text(json.dumps(value),encoding='utf-8')
            def review(prompt):
                self.assertNotIn('原文外',prompt)
                self.assertEqual(json.loads(prompt.split('入力JSON:\n')[-1])['targets'],['上手'])
                return {'opinions':[{'surface':'上手','reading':'カミテ','reason':'模擬の独立意見','uncertain':False}]},'simulation'
            with ExitStack() as stack:
                stack.enter_context(patch('lab.HERE',root))
                stack.enter_context(patch('lab.TalkApi',lambda *a:simulation))
                stack.enter_context(patch('lab.Whisper',lambda *a:simulation))
                stack.enter_context(patch('lab.subprocess.run',side_effect=transport))
                stack.enter_context(patch('lab.Config.load',return_value=Config(gemini_key='test-g',sarashina_key='test-s')))
                stack.enter_context(patch.object(ReviewClients,'gemini',side_effect=review))
                stack.enter_context(patch.object(ReviewClients,'sarashina',side_effect=review))
                stack.enter_context(redirect_stdout(io.StringIO()))
                lab.run(simulation.args)
            self.assertEqual(lab.load(simulation.args.run_dir/'manifest.json')['status'],'completed')
            summary=lab.load(simulation.args.run_dir/'summary.json')
            self.assertEqual((summary['before']['llm_score'],summary['after']['llm_score']),(40,100))
            self.assertEqual((simulation.registrations,simulation.syntheses),(1,2))
            self.assertEqual(len(prompts),3) # 基準1回＋比較2回。登録計画のLLMは不要。
            self.assertEqual(len(llm_records.read(simulation.args.run_dir)['calls']),5)
            for call in llm_records.read(simulation.args.run_dir)['calls']:
                self.assertEqual(call['prompt_utf8_bytes'],len(call['request'].encode('utf-8')))


if __name__=='__main__':unittest.main()
