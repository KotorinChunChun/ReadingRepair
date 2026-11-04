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


if __name__=='__main__':unittest.main()
