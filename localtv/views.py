# Miro Community - Easiest way to make a video website
#
# Copyright (C) 2009, 2010, 2011, 2012 Participatory Culture Foundation
#
# Miro Community is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# Miro Community is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Miro Community.  If not, see <http://www.gnu.org/licenses/>.

import datetime
from django.contrib import comments
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core.urlresolvers import resolve, Resolver404
from django.conf import settings
from django.db.models import Q, Count
from django.http import (Http404, HttpResponsePermanentRedirect,
                         HttpResponseRedirect, HttpResponse)
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.views.decorators.vary import vary_on_headers
from django.views.generic import TemplateView

from localtv.models import Video, Watch, Category, NewsletterSettings, SiteSettings
from localtv.search.utils import SortFilterMixin, NormalizedVideoList

from localtv.playlists.models import Playlist, PlaylistItem


MAX_VOTES_PER_CATEGORY = getattr(settings, 'MAX_VOTES_PER_CATEGORY', 3)


class IndexView(SortFilterMixin, TemplateView):
    template_name = 'localtv/index.html'

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        featured_videos = Video.objects.get_featured_videos()
        popular_videos = self._sort(self._search(''), '-popular')
        new_videos = Video.objects.get_latest_videos().exclude(
                                            feed__avoid_frontpage=True)

        site_settings_videos = Video.objects.get_site_settings_videos()
        recent_comments = comments.get_model().objects.filter(
            site=Site.objects.get_current(),
            content_type=ContentType.objects.get_for_model(Video),
            object_pk__in=site_settings_videos.values_list('pk', flat=True),
            is_removed=False,
            is_public=True).order_by('-submit_date')

        context.update({
            'featured_videos': featured_videos,
            'popular_videos': NormalizedVideoList(popular_videos),
            'new_videos': new_videos,
            'comments': recent_comments
        })
        return context


def about(request):
    return render_to_response(
        'localtv/about.html',
        {}, context_instance=RequestContext(request))


@vary_on_headers('User-Agent', 'Referer')
def view_video(request, video_id, slug=None):
    video_qs = Video.objects.annotate(watch_count=Count('watch'))
    video = get_object_or_404(video_qs, pk=video_id,
                              site=Site.objects.get_current())

    if not video.status == Video.ACTIVE and not request.user_is_admin():
        raise Http404

    if slug is not None and request.path != video.get_absolute_url():
        return HttpResponsePermanentRedirect(video.get_absolute_url())

    context = {'current_video': video,
               # set edit_video_form to True if the user is an admin for
               # backwards-compatibility
               'edit_video_form': request.user_is_admin()}

    site_settings = SiteSettings.objects.get_current()
    popular_videos = Video.objects.get_popular_videos()

    try:
        category_obj = video.categories.all()[0]
    except IndexError:
        pass
    else:
        # If there are categories, prefer the category that the user
        # just came from the list view of.
        referrer = request.META.get('HTTP_REFERER')
        host = request.META.get('HTTP_HOST')
        if referrer and host:
            if referrer.startswith('http://') or \
                    referrer.startswith('https://'):
                referrer = referrer[referrer.index('://')+3:]
            if referrer.startswith(host):
                referrer = referrer[len(host):]
                try:
                    view, args, kwargs = resolve(referrer)
                except Resolver404:
                    pass
                else:
                    from localtv.urls import category_videos
                    if view == category_videos:
                        try:
                            category_obj = video.categories.get(
                                slug=kwargs['slug'],
                                site=site_settings.site)
                        except Category.DoesNotExist:
                            pass

        context['category'] = category_obj
        popular_videos = popular_videos.filter(categories=category_obj)

    context['popular_videos'] = popular_videos

    if site_settings.playlists_enabled:
        # showing playlists
        if request.user.is_authenticated():
            if request.user_is_admin() or \
                    site_settings.playlists_enabled == 1:
                # user can add videos to playlists
                context['playlists'] = Playlist.objects.filter(
                    user=request.user)

        if request.user_is_admin():
            # show all playlists
            context['playlistitem_set'] = video.playlistitem_set.all()
        elif request.user.is_authenticated():
            # public playlists or my playlists
            context['playlistitem_set'] = video.playlistitem_set.filter(
                Q(playlist__status=Playlist.PUBLIC) |
                Q(playlist__user=request.user))
        else:
            # just public playlists
            context['playlistitem_set'] = video.playlistitem_set.filter(
                playlist__status=Playlist.PUBLIC)

        if 'playlist' in request.GET:
            try:
                playlist = Playlist.objects.get(pk=request.GET['playlist'])
            except (Playlist.DoesNotExist, ValueError):
                pass
            else:
                if (playlist.is_public() or
                        request.user_is_admin() or
                        (request.user.is_authenticated() and
                        playlist.user_id == request.user.pk)):
                    try:
                        context['playlistitem'] = video.playlistitem_set.get(
                            playlist=playlist)
                    except PlaylistItem.DoesNotExist:
                        pass

    Watch.add(request, video)

    return render_to_response(
        'localtv/view_video.html',
        context,
        context_instance=RequestContext(request))


def share_email(request, content_type_pk, object_id):
    from email_share import views, forms
    site_settings = SiteSettings.objects.get_current()
    return views.share_email(request, content_type_pk, object_id,
                             {'site': site_settings.site,
                              'site_settings': site_settings},
                             form_class = forms.ShareMultipleEmailForm
                             )


def newsletter(request):
    newsletter = NewsletterSettings.objects.get_current()
    if newsletter.status == NewsletterSettings.DISABLED:
        raise Http404
    elif not newsletter.site_settings.get_tier().permit_newsletter():
        raise Http404

    return HttpResponse(newsletter.as_html(
            {'preview': True}), content_type='text/html')
