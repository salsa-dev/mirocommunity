import datetime
import re

from django.core.urlresolvers import reverse
from django.http import (HttpResponse, HttpResponseBadRequest,
                         HttpResponseRedirect)
from django.shortcuts import get_object_or_404, render_to_response
from django.template import RequestContext

from localtv.decorators import get_sitelocation, require_site_admin, \
    referrer_redirect
from localtv import models, util
from localtv.subsite.admin import forms

from vidscraper import bulk_import

VIDEO_SERVICE_TITLES = (
    re.compile(r'Uploads by (.+)'),
    re.compile(r"Vimeo / (.+)'s uploaded videos")
    )

@require_site_admin
@get_sitelocation
def add_feed(request, sitelocation=None):
    def gen():
        yield render_to_response('localtv/subsite/admin/feed_wait.html',
                                 {
                'message': 'Checking out this URL',
                'feed_url': request.POST.get('feed_url')},
                                 context_instance=RequestContext(request))
        yield add_feed_response(request, sitelocation)
    return util.HttpMixedReplaceResponse(request, gen())


def add_feed_response(request, sitelocation=None):
    add_form = forms.AddFeedForm(request.POST)

    if not add_form.is_valid():
        return HttpResponseBadRequest(add_form['feed_url'].errors.as_text())

    feed_url = add_form.cleaned_data['feed_url']
    parsed_feed = request.session['parsed_feed'] = \
        add_form.cleaned_data['parsed_feed']

    title = parsed_feed.feed.get('title')
    if title is None:
        return HttpResponseBadRequest('That URL does not look like a feed.')
    for regexp in VIDEO_SERVICE_TITLES:
        match = regexp.match(title)
        if match:
            title = match.group(1)
            break

    defaults = request.session['defaults'] = {
        'name': title,
        'feed_url': feed_url,
        'webpage': parsed_feed.feed.get('link', ''),
        'description': parsed_feed.feed.get('summary', ''),
        'when_submitted': datetime.datetime.now(),
        'last_updated': datetime.datetime.now(),
        'status': models.FEED_STATUS_ACTIVE,
        'user': request.user,
        'etag': '',
        'auto_approve': bool(request.POST.get('auto_approve', False))}

    video_count = request.session['video_count'] = bulk_import.video_count(
        feed_url, parsed_feed)

    form = forms.SourceForm(instance=models.Feed(**defaults))
    return render_to_response('localtv/subsite/admin/add_feed.html',
                              {'form': form,
                               'video_count': video_count},
                              context_instance=RequestContext(request))


@require_site_admin
@get_sitelocation
def add_feed_done(request, sitelocation):
    if 'cancel' in request.POST:
        # clean up the session
        del request.session['parsed_feed']
        del request.session['video_count']
        del request.session['defaults']

        return HttpResponseRedirect(reverse('localtv_admin_manage_page'))

    def gen():
        yield render_to_response('localtv/subsite/admin/feed_wait.html',
                                 {
                'message': 'Importing %i videos from' % (
                    request.session['video_count'],),
                'feed_url': request.session['defaults']['feed_url']},
                                 context_instance=RequestContext(request))
        yield add_feed_done_response(request, sitelocation)
    return util.HttpMixedReplaceResponse(request, gen())

def add_feed_done_response(request, sitelocation=None):
    defaults = request.session['defaults']

    form = forms.SourceForm(request.POST)
    if not form.is_valid():
        return render_to_response(
            'localtv/subsite/admin/add_feed.html',
            {'form': form,
             'video_count': request.session['video_count']},
            context_instance=RequestContext(request))

    feed, created = models.Feed.objects.get_or_create(
        feed_url=defaults['feed_url'],
        site=sitelocation.site,
        defaults=defaults)

    if not created:
        for key, value in defaults.items():
            setattr(feed, key, value)

    for key, value in form.cleaned_data.items():
        setattr(feed, key, value)
    feed.save()

    parsed_feed = bulk_import.bulk_import(feed.feed_url,
                                          request.session['parsed_feed'])
    feed.update_items(parsed_feed=parsed_feed)

    # clean up the session
    del request.session['parsed_feed']
    del request.session['video_count']
    del request.session['defaults']

    return render_to_response('localtv/subsite/admin/feed_done.html',
                              {'feed': feed},
                              context_instance=RequestContext(request))


@referrer_redirect
@require_site_admin
@get_sitelocation
def feed_stop_watching(request, sitelocation=None):
    feed = get_object_or_404(
        models.Feed,
        id=request.GET.get('feed_id'),
        site=sitelocation.site)

    feed.status = models.FEED_STATUS_REJECTED
    feed.video_set.all().delete()
    feed.save()

    return HttpResponse('SUCCESS')


@referrer_redirect
@require_site_admin
@get_sitelocation
def feed_auto_approve(request, feed_id, sitelocation=None):
    feed = get_object_or_404(
        models.Feed,
        id=feed_id,
        site=sitelocation.site)

    feed.auto_approve = not request.GET.get('disable')
    feed.save()

    return HttpResponse('SUCCESS')

@referrer_redirect
@require_site_admin
@get_sitelocation
def remove_saved_search(request, sitelocation=None):
    search_id = request.GET.get('search_id')
    existing_saved_search = models.SavedSearch.objects.filter(
        site=sitelocation.site,
        pk=search_id)

    if existing_saved_search.count():
        existing_saved_search.delete()
        return HttpResponse('SUCCESS')
    else:
        return HttpResponseBadRequest(
            'Saved search of that query does not exist')
