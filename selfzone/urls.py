from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^old/(?P<old1_id>[0-9]+)vs(?P<old2_id>[0-9]+)=(?P<voted>(left|right))$', views.index_voted, name='index_voted'),
    url(r'^upload/$', views.upload, name='upload'),
    url(r'^vote/(?P<s1_id>[0-9]+)vs(?P<s2_id>[0-9]+)=(?P<voted>(left|right))$', views.vote, name='vote'),
]