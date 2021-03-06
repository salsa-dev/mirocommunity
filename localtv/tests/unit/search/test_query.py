from django.contrib.auth.models import User
from haystack import connections

from localtv.models import Category, Feed, SavedSearch
from localtv.playlists.models import Playlist
from localtv.search.query import SmartSearchQuerySet
from localtv.tests import BaseTestCase


class TokenizeTestCase(BaseTestCase):
    """
    Tests for the search query tokenizer.

    """
    def assertTokenizes(self, query, result):
        self.assertEqual(tuple(SmartSearchQuerySet().tokenize(query)),
                          tuple(result))

    def test_split(self):
        """
        Space-separated tokens should be split apart.

        """
        self.assertTokenizes('foo bar baz', ('foo', 'bar', 'baz'))

    def test_quotes(self):
        """
        Quoted string should be kept together.

        """
        self.assertTokenizes('"foo bar" \'baz bum\'', ('foo bar', 'baz bum'))

    def test_negative(self):
        """
        Items prefixed with - should keep that prefix, even with quotes.

        """
        self.assertTokenizes('-foo -"bar baz"', ('-foo', '-bar baz'))

    def test_or_grouping(self):
        """
        {}s should group their keywords together.

        """
        self.assertTokenizes('{foo {bar baz} bum}', (['foo',
                                                      ['bar', 'baz'],
                                                      'bum'],))

    def test_colon(self):
        """
        :s should remain part of their word.

        """
        self.assertTokenizes('foo:bar', ('foo:bar',))

    def test_open_grouping(self):
        """
        An open grouping at the end should return all its items.

        """
        self.assertTokenizes('{foo bar', (['foo', 'bar'],))

    def test_open_quote(self):
        """
        An open quote should be stripped.

        """
        self.assertTokenizes('"foo', ('foo',))
        self.assertTokenizes("'foo", ('foo',))

    def test_unicode(self):
        """
        Unicode should be handled as regular characters.

        """
        self.assertTokenizes(u'espa\xf1a', (u'espa\xf1a',))

    def test_unicode_not_latin_1(self):
        """
        Non latin-1 characters should be included.

        """
        self.assertTokenizes(u'foo\u1234bar', (u'foo\u1234bar',))

    def test_blank(self):
        """
        A blank query should tokenize to a blank list.

        """
        self.assertTokenizes('', ())


class AutoQueryTestCase(BaseTestCase):
    def setUp(self):
        super(AutoQueryTestCase, self).setUp()
        self._disable_index_updates()
        self.blender_videos = (
            self.create_video(name='Blender'),
            self.create_video(name='b2', description='Foo bar a blender.'),
            self.create_video(name='b3',
                             description='<h1>Foo</h1> <p>bar <span class="ro'
                             'cket">a blender</span></p>'),
            self.create_video(name='b4', tags='blender'),
            self.create_video(name='b5',
                          categories=[self.create_category(name='Blender',
                                                           slug='tender')]),
            self.create_video(name='b6', video_service_user='blender'),
            self.create_video(name='b7',
                             feed=self.create_feed('feed1', name='blender')),
        )
        self.blender_users = (
            self.create_user(username='blender'),
            self.create_user(username='test1', first_name='Blender'),
            self.create_user(username='test2', last_name='Blender'),
        )
        self.blender_user_videos = ()
        for user in self.blender_users:
            self.blender_user_videos += (
                self.create_video(name='b8u%s' % user.username, user=user),
                self.create_video(name='b9a%s' % user.username, authors=[user])
            )

        self.rocket_videos = (
            self.create_video(name='Rocket'),
            self.create_video(name='r2', description='Foo bar a rocket.'),
            self.create_video(name='r3',
                             description='<h1>Foo</h1> <p>bar <span class="bl'
                             'ender">a rocket</span></p>'),
            self.create_video(name='r4', tags='rocket'),
            self.create_video(name='r5',
                             categories=[self.create_category(name='Rocket',
                                                             slug='pocket')]),
            self.create_video(name='r6', video_service_user='rocket'),
            self.create_video(name='r7',
                             feed=self.create_feed('feed2', name='rocket')),
        )
        self.rocket_users = (
            self.create_user(username='rocket'),
            self.create_user(username='test3', first_name='Rocket'),
            self.create_user(username='test4', last_name='Rocket'),
        )
        self.rocket_user_videos = ()
        for user in self.rocket_users:
            self.rocket_user_videos += (
                self.create_video(name='r8u%s' % user.username, user=user),
                self.create_video(name='r9a%s' % user.username, authors=[user])
            )

        self.search_videos = (
            self.create_video(name='s1', search=self.create_search("rogue")),
        )
        self.playlist = self.create_playlist(self.blender_users[0])
        self.playlist.add_video(self.blender_videos[0])
        self.playlist.add_video(self.rocket_videos[0])

        self.all_videos = set((self.blender_videos + self.blender_user_videos +
                              self.rocket_videos + self.rocket_user_videos +
                              self.search_videos))
        self._enable_index_updates()
        self._rebuild_index()

    def assertQueryResults(self, query, expected):
        """
        Given a query and a list of videos, checks that all expected videos
        are found by a search with the given query.

        """
        results = SmartSearchQuerySet().auto_query(query)
        results = dict((unicode(r.pk), r.object.name) for r in results if r.object is not None)
        expected = dict((unicode(v.pk), v.name) for v in expected)

        result_pks = set(results.items())
        expected_pks = set(expected.items())
        self.assertEqual(result_pks, expected_pks)

    def test_search(self):
        """
        The basic query should return videos which contain the search term,
        even if there is HTML involved.

        """
        expected = self.blender_videos + self.blender_user_videos
        self.assertQueryResults("blender", expected)

    def test_search_phrase(self):
        """
        Phrases in quotes should be searched for as a phrase.

        """
        expected = self.blender_videos[1:3] + self.rocket_videos[1:3]
        self.assertQueryResults('"foo bar"', expected)

    def test_search_blank(self):
        """
        Searching for a blank string should be handled gracefully.

        """
        self.assertQueryResults('', self.all_videos)

    def test_search_exclude(self):
        """
        Search should exclude strings, phrases, and keywords preceded by a '-'

        We skip this test on Whoosh because it has a bug w.r.t exclusion:
        https://bitbucket.org/mchaput/whoosh/issue/254
        """
        if ('WhooshEngine' in
            connections['default'].options['ENGINE']):
            self.skipTest('Whoosh has bad handling of exclude queries')

        expected = (self.all_videos - set(self.blender_videos) -
                    set(self.blender_user_videos))
        self.assertQueryResults('-blender', expected)

        expected = (self.all_videos - set(self.blender_videos[1:3]) -
                    set(self.rocket_videos[1:3]))
        self.assertQueryResults('-"foo bar"', expected)

        expected = self.all_videos - set(self.blender_videos[6:7])
        self.assertQueryResults('-feed:blender', expected)

        expected = self.all_videos - set(self.blender_user_videos[:2])
        self.assertQueryResults('-user:blender', expected)

    def test_search_keyword__tag(self):
        """
        Tag keyword should only search the videos' tags.

        """
        self.assertQueryResults('tag:blender', self.blender_videos[3:4])

    def test_search_keyword__category(self):
        """
        Category keyword should search the videos' categories, accepting name,
        slug, and pk.

        """
        expected = self.blender_videos[4:5]
        category = Category.objects.get(slug='tender')
        self.assertQueryResults('category:blender', expected)
        self.assertQueryResults('category:tender', expected)
        self.assertQueryResults('category:{0}'.format(category.pk), expected)

    def test_search_keyword__user(self):
        """
        User keyword should accept username or pk, and should check user and
        authors.

        """
        expected = self.blender_user_videos[0:2]
        user = User.objects.get(username='blender')
        self.assertQueryResults('user:Blender', expected)
        self.assertQueryResults('user:{0}'.format(user.pk), expected)

    def test_search_keyword__feed(self):
        """
        Feed keyword should search the videos' feeds, accepting feed name or
        pk.

        """
        expected = self.blender_videos[6:7]
        feed = Feed.objects.get(feed_url='feed1')
        self.assertQueryResults('feed:Blender', expected)
        self.assertQueryResults('feed:{0}'.format(feed.pk), expected)

    def test_search_keyword__playlist(self):
        """
        Playlist keyword should search the videos' playlists, accepting a pk
        or a username/slug combination.

        """
        expected = self.blender_videos[:1] + self.rocket_videos[:1]
        playlist = Playlist.objects.get(user=self.blender_users[0])
        self.assertQueryResults('playlist:blender/playlist', expected)
        self.assertQueryResults('playlist:{0}'.format(playlist.pk), expected)

    def test_search_keyword__search(self):
        """
        Search keyword should search the videos' related saved searches,
        accepting a pk or a query string.

        """
        expected = self.search_videos
        search = SavedSearch.objects.get(query_string="rogue")
        self.assertQueryResults('search:{0}'.format(search.pk), expected)
        self.assertQueryResults('search:rogue', expected)
        self.assertQueryResults('search:"rogue"', expected)

    def test_search_or(self):
        """
        Terms bracketed in {}s should be ORed together.

        """
        expected = (self.rocket_videos + self.rocket_user_videos +
                    self.blender_videos[1:3])
        self.assertQueryResults("{rocket foo}", expected)

        # For posterity, this test was added because of bz19056.
        expected = (self.rocket_videos + self.rocket_user_videos +
                    self.blender_user_videos[0:2])
        self.assertQueryResults("{user:blender rocket}", expected)

        # bz19083. Nonexistant keyword target in an or shouldn't freak out.
        expected = self.rocket_videos + self.rocket_user_videos
        self.assertQueryResults("{user:quandry rocket}", expected)

    def test_search_or_and(self):
        """
        Mixing OR and AND should work as expected.

        """
        expected = (self.create_video(name="EXTRA blender"),
                    self.create_video(name="EXTRA rocket"))

        self._rebuild_index()

        self.assertQueryResults('{rocket blender} extra', expected)
        self.assertQueryResults('extra {rocket blender}', expected)
