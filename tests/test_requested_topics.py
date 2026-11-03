import unittest
from refresh_catalog import Topic, SourceConfig, select_topics, parse_short_ids, RefreshError, load_config
from test_refresh import page, short

class RequestedTopicTests(unittest.TestCase):
    def test_long_form_is_explicitly_opt_in_and_ads_stay_excluded(self):
        video = {'videoRenderer': {'videoId': 'LONGVIDEO01', 'navigationEndpoint': {'watchEndpoint': {'videoId': 'LONGVIDEO01'}}}}
        with self.assertRaises(RefreshError): parse_short_ids(page(video))
        self.assertEqual(parse_short_ids(page(video), allow_long=True), ['LONGVIDEO01'])
        self.assertEqual(parse_short_ids(page({'adSlotRenderer':video}, short('AAAAAAAAAAA')), allow_long=True), ['AAAAAAAAAAA'])
        video['videoRenderer']['navigationEndpoint']['watchEndpoint']['videoId'] = 'OTHERID0001'
        with self.assertRaises(RefreshError): parse_short_ids(page(video), allow_long=True)

    def test_boosted_queries_are_selected_more_often_without_duplicates(self):
        topics=(Topic('q0','boost','boost',weight=6), Topic('q1','ordinary','ordinary'))
        config=SourceConfig(topics,1,1000,False)
        boosted=sum(select_topics(config,i*1800)[0].id=='q0' for i in range(1000))
        self.assertGreater(boosted, 800)
        config=SourceConfig(topics,2,1000,False)
        self.assertEqual(len({t.id for t in select_topics(config,0)}),2)

    def test_production_horror_exceptions_and_weights(self):
        topics=load_config().topics
        long_tags={'#'+t for t in ['\u043c\u0433\u0435\u0441\u0442\u0440\u0430\u0448\u0438\u043b\u043a\u0430','\u043c\u0433\u0435\u0441\u0442\u0440\u0430\u0448\u0438\u043b\u043a\u0438','\u0441\u0442\u0440\u0430\u0448\u0438\u043b\u043a\u0438\u043c\u0433\u0435','\u043c\u0433\u0435\u0445\u043e\u0440\u0440\u043e\u0440','\u043c\u0433\u0435\u0438\u0441\u0442\u043e\u0440\u0438\u0438']}
        self.assertEqual({t.query for t in topics if t.allow_long},long_tags)
        self.assertTrue(all(t.weight==6 for t in topics if t.allow_long))
        self.assertEqual(sum(t.weight==4 for t in topics),12)
        self.assertTrue(all(t.category and t.query.startswith('#') for t in topics if t.id not in {'q1','q3','q6','q7','q8','q9','q15','q16','q17','q18','q19','q20','q22','q23','q24','q25','q26'}))
