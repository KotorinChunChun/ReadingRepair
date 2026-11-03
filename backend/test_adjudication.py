import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from adjudication import adopted_readings, answer_template, candidates, canonical, decide, load_answers, tts_occurrences


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.original = '舞台の上手です。'
        self.reference = {'words': [{'surface': '上手', 'reading': 'カミテ'}]}
        self.analysis = {'analyzed_text': '<tsml><word pronunciation="ブタイ">舞台</word><word pronunciation="ノ">の</word><word pronunciation="ジョーズ">上手</word><word pronunciation="デス">です</word><word pronunciation="">。</word></tsml>'}
        self.items = candidates(self.original, self.reference, {'errors': []}, self.analysis)

    def reviews(self, first='カミテ', second='カミテ', uncertain=False):
        return {'providers': [{'provider': p, 'status': 'ok', 'opinions': [{'surface': '上手', 'reading': v, 'uncertain': uncertain, 'reason': '文脈'}]} for p,v in [('gemini',first),('sarashina',second)]]}

    def test_homograph_missed_by_asr_is_still_a_candidate(self):
        self.assertEqual(self.items[0]['surface'], '上手')
        self.assertTrue(self.items[0]['tts_difference'])

    def test_long_vowel_variants_are_not_conflicts(self):
        self.assertEqual(canonical('ヒョウジ'), canonical('ヒョージ'))
        self.assertEqual(canonical('タカナシ’'), canonical('タカナシ'))
        self.assertNotEqual(canonical('ウイ'), canonical('イー'))

    def test_multi_token_surface_gets_joined_pronunciation(self):
        analysis={'analyzed_text':'<tsml><word pronunciation="シ">四</word><word pronunciation="ガツ">月</word><word pronunciation="ツイタチ">一日</word></tsml>'}
        self.assertEqual(tts_occurrences('四月一日',analysis,'四月一日'),['シガツツイタチ'])

    def test_ascii_width_matching_preserves_circled_number_identity(self):
        analysis={'analyzed_text':'<tsml><word pronunciation="エイチティーティーピーオーバー">ＨＴＴＰｏｖｅｒ</word><word pronunciation="マルイチ">①</word></tsml>'}
        self.assertEqual(tts_occurrences('HTTPover①',analysis,'HTTPover'),['エイチティーティーピーオーバー'])
        self.assertEqual(tts_occurrences('HTTPover①',analysis,'①'),['マルイチ'])
        self.assertEqual(tts_occurrences('HTTPover①',analysis,'1'),[])

    def test_all_three_agree_can_be_adopted_but_is_not_human_truth(self):
        result=decide(self.items,self.reviews(),{})
        self.assertEqual(result['status'],'resolved')
        self.assertEqual(result['decisions'][0]['source'],'model_majority')
        self.assertTrue(result['decisions'][0]['needs_registration'])

    def test_no_two_matching_valid_votes_wait(self):
        for review in (self.reviews(first='ジョウズ',second='ウワテ'),self.reviews(uncertain=True)):
            with self.subTest(review=review):
                result=decide(self.items,review,{})
                self.assertEqual(result['status'],'pending_confirmation')
                self.assertFalse(result['decisions'][0]['needs_registration'])

    def test_two_votes_adopt_even_when_third_disagrees(self):
        result=decide(self.items,self.reviews(second='ジョウズ'),{})
        self.assertEqual(result['decisions'][0]['accepted_reading'],'カミテ')
        self.assertIn('3票中2票',result['decisions'][0]['reason'])

    def test_two_external_votes_can_correct_primary(self):
        result=decide(self.items,self.reviews('ジョウズ','ジョウズ'),{})
        self.assertEqual(result['decisions'][0]['accepted_reading'],'ジョウズ')
        self.assertFalse(result['decisions'][0]['needs_registration'])

    def test_failed_or_uncertain_provider_is_not_a_vote(self):
        review=self.reviews();review['providers'][1].update(status='unavailable',opinions=[])
        row=decide(self.items,review,{})['decisions'][0]
        self.assertEqual(len(row['votes']),2);self.assertEqual(row['status'],'accepted')
        self.assertEqual(row['abstentions'][0]['provider'],'sarashina')

    def test_number_conversion_does_not_hide_following_word_pronunciation(self):
        analysis={'analyzed_text':'<tsml><word pronunciation="コーモク">項目</word><word pronunciation="イチ">一</word><word pronunciation="ヘーブン">平文</word><word pronunciation="デス">です</word><word pronunciation="">。</word></tsml>'}
        self.assertEqual(tts_occurrences('項目1\n平文です。',analysis,'平文'),['ヘーブン'])
        self.assertEqual(tts_occurrences('項目1\n平文です。',analysis,'1'),[])

    def test_unmapped_or_partial_word_is_not_reported_as_a_pronunciation(self):
        self.assertEqual(tts_occurrences('上手',{'analyzed_text':'<tsml><word pronunciation="ジョーズ">別の語</word></tsml>'},'上手'),[])
        self.assertEqual(tts_occurrences('舞台の上手です。',self.analysis,'手'),[])

    def test_missing_keys_do_not_turn_primary_into_ground_truth(self):
        review={'providers':[{'provider':p,'status':'not_configured','opinions':[]} for p in ('gemini','sarashina')]}
        result=decide(self.items,review,{})
        self.assertEqual(result['status'],'pending_confirmation')

    def test_user_can_select_a_different_reading_without_dictionary_change(self):
        answer={self.items[0]['id']:{'action':'accept','reading':'ジョウズ','reason':'この文では上手なことを指す'}}
        result=decide(self.items,self.reviews(),answer)
        row=result['decisions'][0]
        self.assertEqual(row['source'],'user');self.assertFalse(row['needs_registration'])

    def test_user_can_reject_a_dictionary_change(self):
        result=decide(self.items,self.reviews(),{self.items[0]['id']:{'action':'reject','reason':'登録しない'}})
        self.assertEqual(result['decisions'][0]['status'],'rejected')
        self.assertFalse(result['decisions'][0]['needs_registration'])

    def test_phrase_registration_is_distinct_from_word_reading(self):
        answer={self.items[0]['id']:{'action':'accept','reading':'カミテ','reason':'舞台用語は語句で限定',
                                  'registration':{'surface':'舞台の上手','reading':'ブタイノカミテ'}}}
        result=decide(self.items,self.reviews(second='ジョウズ'),answer)
        self.assertEqual(result['decisions'][0]['accepted_reading'],'カミテ')
        self.assertEqual(adopted_readings(result['decisions']),[{'surface':'舞台の上手','reading':'ブタイノカミテ'}])

    def test_phrase_must_include_the_reviewed_word_and_reading(self):
        for entry in ({'surface':'舞台','reading':'ブタイ'}, {'surface':'舞台の上手','reading':'ブタイノジョウズ'}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                decide(self.items,self.reviews(),{self.items[0]['id']:{'action':'accept','reading':'カミテ','reason':'確認','registration':entry}})

    def test_scoped_reference_does_not_conflict_with_short_dictionary_word(self):
        reference={'words':[{'surface':'舞台の上手','reading':'ブタイノカミテ'}]}
        analysis={'analyzed_text':'<tsml><word pronunciation="ブタイノカミテ">舞台の上手</word><word pronunciation="デス">です</word><word pronunciation="">。</word></tsml>'}
        result=candidates(self.original,reference,{'errors':[]},analysis,known_words=[{'surface':'上手','reading':'ジョウズ'}])
        self.assertEqual(result,[])

    def test_phrase_answer_outside_original_cannot_be_loaded(self):
        value=answer_template(self.original,decide(self.items,{'providers':[]},{})['questions'])
        value['answers'][0].update(action='accept',reading='カミテ',reason='確認',registration={'surface':'劇場の上手','reading':'ゲキジョウノカミテ'})
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'answers.json';path.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(ValueError):load_answers(path,self.original,{self.items[0]['id']})

    def test_reference_scope_keeps_short_word_when_it_also_occurs_outside_phrase(self):
        from lab import scoped_reference
        reference={'reading':'ブタイノカミテ','words':[{'surface':'舞台','reading':'ブタイ'}, {'surface':'上手','reading':'カミテ'}, {'surface':'舞台の上手','reading':'ブタイノカミテ'}]}
        adopted=[{'surface':'舞台の上手','reading':'ブタイノカミテ'}]
        result=scoped_reference('舞台の上手',reference,adopted)
        self.assertEqual(result['words'],adopted)
        result=scoped_reference('舞台の上手と上手な歌',reference,adopted)
        self.assertIn({'surface':'上手','reading':'カミテ'},result['words'])

    def test_answer_template_is_unanswered_until_filled(self):
        q=decide(self.items,{'providers':[]},{})['questions']
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'answers.json';path.write_text(json.dumps(answer_template(self.original,q)),encoding='utf-8')
            self.assertEqual(load_answers(path,self.original,{self.items[0]['id']}),{})

    def test_foreign_original_or_unknown_id_cannot_authorize_a_change(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'answers.json'
            for sha,identifier in [('wrong',self.items[0]['id']),(hashlib.sha256(self.original.encode()).hexdigest(),'foreign')]:
                value={'format':'voisona.reading-decisions.v1','original_sha256':sha,'answers':[{'id':identifier,'action':'accept','reading':'カミテ','reason':'確認'}]}
                path.write_text(json.dumps(value),encoding='utf-8')
                with self.assertRaises(ValueError):load_answers(path,self.original,{self.items[0]['id']})


if __name__=='__main__':unittest.main()
