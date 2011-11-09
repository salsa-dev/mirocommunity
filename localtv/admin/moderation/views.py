# Copyright 2009 - Participatory Culture Foundation
# 
# This file is part of Miro Community.
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

from django.contrib import comments
from django.contrib.sites.models import Site
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView

from localtv.admin.feeds import generate_secret
from localtv.admin.moderation.forms import CommentModerationFormSet
from localtv.admin.views import BulkEditView
from localtv.decorators import require_site_admin
from localtv.models import Video


# TODO: This should also use BulkEditView
class VideoModerationQueueView(ListView):
    paginate_by = 10
    context_object_name = 'videos'
    template_name = 'localtv/admin/moderation/videos/queue.html'

    @method_decorator(require_site_admin)
    def dispatch(self, *args, **kwargs):
        return super(VideoModerationQueueView, self).dispatch(*args, **kwargs)

    def get_queryset(self):
        return Video.objects.filter(
            status=Video.UNAPPROVED,
            site=Site.objects.get_current()
        ).order_by('when_submitted', 'when_published')

    def get_context_data(self, **kwargs):
        context = super(VideoModerationQueueView, self).get_context_data(**kwargs)
        try:
            current_video = context['object_list'][0]
        except IndexError:
            current_video = None
        
        context.update({
            'feed_secret': generate_secret(),
            'current_video': current_video
        })
        return context


class CommentModerationQueueView(BulkEditView):
    formset_class = CommentModerationFormSet
    paginate_by = 10
    context_object_name = 'comments'
    template_name = 'localtv/admin/moderation/comments/queue.html'
    queryset = comments.get_model()._default_manager.filter(is_public=False,
                                                            is_removed=False)

    @method_decorator(require_site_admin)
    def dispatch(self, *args, **kwargs):
        return super(CommentModerationQueueView, self).dispatch(*args, **kwargs)

    def get_formset_kwargs(self):
        kwargs = super(CommentModerationQueueView, self).get_formset_kwargs()
        kwargs['request'] = self.request
        return kwargs
