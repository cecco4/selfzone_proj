from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.views.decorators.cache import cache_control
from django.contrib.auth.decorators import login_required
from graphos.renderers import gchart
from graphos.renderers.highcharts import LineChart
from graphos.sources.simple import SimpleDataSource
from graphos.renderers import gchart

from models import SelfieForm, Selfie, Match
from django.contrib.auth.models import User
from random import randint
from numpy.random import choice
from django.db.models import Count
from django.utils import timezone
import itertools


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def index(request):
    context = {}
    context['s1'], context['s2'] = select_selfies()
    return render(request, 'selfzone/index.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def index_voted(request, old1_id, old2_id, voted):
    context = {}
    context["old1"] = get_object_or_404(Selfie, pk=old1_id)
    context["old2"] = get_object_or_404(Selfie, pk=old2_id)
    context["voted"] = voted
    context['s1'], context['s2'] = select_selfies()
    return render(request, 'selfzone/index.html', context)


def select_selfies():
    withtags = Selfie.objects.exclude(tags=None)
    # first selfie is random
    s1 = withtags.all()[randint(0, withtags.count()-1)]

    # select selfies with same (or less) number of faces (minimun 5 selfies)
    tries = 0
    f = Selfie.objects.exclude(id=s1.id).filter(faces=s1.faces)
    while f.count() <= 5:
        tries += 1
        f = Selfie.objects.exclude(id=s1.id).filter(faces=s1.faces-tries)

    # start filtring by tags (random weighted by priority)
    limit = int(f.count()*5/100 + 5) # minimum: 5%
    print "Start search from ", f.count(), limit

    tag_weights = [float(i.priority)+1 for i in s1.tags.all()]
    tag_weights = [i/sum(tag_weights) for i in tag_weights]
    max_tags = 3

    old = f
    minimum = limit / 4
    while True:
        for t in choice(s1.tags.all(), max_tags, replace=False, p=tag_weights):
            print "filter", t.tag
            f = f.filter(tags__tag=t.tag)
        if f.count() >= minimum:
            break
        else:
            print f.count(), "discard"
            f = old
            minimum /= 2

    if f.count() == 1:
        return s1, f.all()[0]
    # selects from filtred selfie (random weighted by delta score and number of taken match)
    # filtred selfies are randomic limited
    weights = []
    selected = choice(f.all(), min(limit, f.count()), replace=False)
    print "selected selfies: ", len(selected)
    for s in selected:
        matches = s.loser_set.filter(winner=s1).count() + s.winner_set.filter(loser=s1).count() + 1.0
        delta_score = float(abs(s.score-s1.score))
        weights.append(delta_score*matches)

    if sum(weights) != 0:
        weights = [max(weights)-i for i in weights]
        weights = [i/sum(weights) for i in weights]
        s2 = choice(selected, 1, p=weights)[0]
    else:
        s2 = selected[randint(0, len(selected)-1)]
    print "chosen: ", s2, "delta score: ", abs(s1.score-s2.score),
    print "matches: ", s2.loser_set.filter(winner=s1).count() + s2.winner_set.filter(loser=s1).count()
    print "s1 expected:", Selfie.expected(s2.score, s1.score), "s2 expected:", Selfie.expected(s1.score, s2.score)
    return s1, s2


@login_required
def upload(request):
    if request.method == 'POST':
        form = SelfieForm(request.POST, request.FILES)
        if form.is_valid():
            instance = Selfie(photo=request.FILES['photo'])
            instance.user = request.user
            instance.info = form.cleaned_data["info"]
            instance.save()
            print "new salfie: ", instance, "; anlisys result: ", instance.analyze()
            return HttpResponse('Successful update')
        return HttpResponse('Data Not Valid')
    else:
        form = SelfieForm()
        return render(request, 'selfzone/uploadForm.html', {'form': form})


def vote(request, s1_id, s2_id, voted):
    s1 = get_object_or_404(Selfie, pk=s1_id)
    s2 = get_object_or_404(Selfie, pk=s2_id)
    winner = loser = None
    if voted == "left":
        winner = s1
        loser = s2
    elif voted == "right":
        winner = s2
        loser = s1

    Match.objects.create(winner=winner, loser=loser)
    winner.win_against(loser)

    # return HttpResponse("Won " + str(sW.id) + ": " + str(sW.won) + "/" + str(sW.loss) + "\n" +
    #                    "Lost " + str(sL.id) + ": " + str(sL.won) + "/" + str(sL.loss) + "\n")
    return HttpResponseRedirect(reverse('selfzone:index_voted', args=(s1.id, s2.id, voted)))


def details(request, selfie_id):
    selfie = get_object_or_404(Selfie, pk=selfie_id)
    pos = Selfie.objects.filter(score__gt=selfie.score).count() +1

    matches = (selfie.loser_set.all() | selfie.winner_set.all())
    lasts = []
    for m in matches.order_by("match_date")[:10]:
        s = None
        color = None
        if m.winner.id == selfie.id:
            s = m.loser
            color = "green"
        else:
            s = m.winner
            color = "red"
        lasts.append({"selfie": s, "color": color})

    #matches per day
    g1 = group_by_day(selfie.winner_set, 15)
    g2 = group_by_day(selfie.loser_set, 15)

    data = [("day", "win", "loss")]
    for i in range(len(g1)):
        data.append((g1[i][0], g1[i][1], g2[i][1]))
    chart = AreaChart(SimpleDataSource(data=data), options={'title': "win vs loss"}, width="100%")

    nightmare = easy = None
    lost_with = selfie.loser_set.order_by("winner")
    if lost_with.count() > 0:
        grouped = itertools.groupby(lost_with, lambda r: r.winner)
        nightmare = sorted([(s, len(list(count))) for s, count in grouped], lambda x,y: cmp(y[1], x[1]))[0][0]

    win_with = selfie.winner_set.order_by("loser")
    if win_with.count() > 0:
        grouped = itertools.groupby(win_with, lambda r: r.loser)
        easy = sorted([(s, len(list(count))) for s, count in grouped], lambda x,y: cmp(y[1], x[1]))[0][0]

    context = {'selfie': selfie, 'pos': pos, 'lasts': lasts, 'chart': chart, 'nightmare': nightmare, 'easy': easy}
    return render(request, 'selfzone/details.html', context)


def group_by_day(set, days):
    last_days = timezone.now().date() - timezone.timedelta(days)
    m = set.filter(match_date__gte=last_days).order_by("match_date")
    grouped = itertools.groupby(m, lambda record: record.match_date.strftime("%Y-%m-%d"))
    matches_by_day = [(day, len(list(m_this_day))) for day, m_this_day in grouped]
    all_days = [t.strftime("%Y-%m-%d") for t in [timezone.now().date() - timezone.timedelta(i) for i in range(days+1)]]
    mat_days = [d for d, c in matches_by_day]

    for d in all_days:
        if d not in mat_days:
            matches_by_day.append((d, 0))
    return sorted(matches_by_day, lambda x, y: cmp(x[0], y[0]))


class AreaChart(gchart.LineChart):
    def get_template(self):
        return "graphos/gchart/area_chart.html"


def stats(request):
    context = {}
    day = Match.objects.all().filter(match_date__gt=timezone.now().date())
    day = day.values('winner').annotate(count=Count('winner')).order_by("-count")

    start_week = timezone.now().date() - timezone.timedelta(timezone.now().weekday())
    week = Match.objects.all().filter(match_date__gt=start_week)
    week = week.values('winner').annotate(count=Count('winner')).order_by("-count")

    context['bestD']  = get_object_or_404(Selfie, pk=day[0]["winner"])
    context['worstD'] = get_object_or_404(Selfie, pk=day[day.count()-1]["winner"])
    context['bestW']  = get_object_or_404(Selfie, pk=week[0]["winner"])
    context['worstW'] = get_object_or_404(Selfie, pk=week[week.count()-1]["winner"])
    return render(request, 'selfzone/stats.html', context)


def top(request, num):
    if num == "":
        num = 10
    list = Selfie.objects.order_by("-score").all()[:int(num)]
    return render(request, 'selfzone/top.html', {"list": list})


def bottom(request, num):
    if num == "":
        num = 10
    list = Selfie.objects.order_by("score").all()[:int(num)]
    return render(request, 'selfzone/top.html', {"list": list})