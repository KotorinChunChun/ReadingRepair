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


if __name__=='__main__':unittest.main()
