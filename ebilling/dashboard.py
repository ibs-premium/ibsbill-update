"""Staff-only web dashboard for monitoring MoMo payments, apps and callbacks."""
import calendar
import csv
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ApplicationForm
from .models import Application, CallBacks, EBill
from .payments import apply_final_status, check_with_mtn, get_mtn_token

STATUSES = ['SUCCESSFUL', 'PENDING', 'FAILED']

staff_required = user_passes_test(
    lambda u: u.is_active and u.is_staff, login_url='dashboard:login'
)


def _filtered_bills(params):
    """Transactions matching the Transactions page filters in `params` (GET or POST data)."""
    bills = EBill.objects.all().order_by('-request_datetime')
    q = params.get('q', '').strip()
    status = params.get('status', '')
    app = params.get('app', '')
    date_from = params.get('from', '')
    date_to = params.get('to', '')

    if q:
        bills = bills.filter(
            Q(uuid__icontains=q) | Q(username__icontains=q) | Q(device_id__icontains=q)
            | Q(financial_transaction_id__icontains=q) | Q(momo_number__icontains=q) | Q(momo_name__icontains=q)
        )
    if status:
        bills = bills.filter(status=status)
    if app:
        bills = bills.filter(app=app)
    if date_from:
        bills = bills.filter(request_datetime__date__gte=date_from)
    if date_to:
        bills = bills.filter(request_datetime__date__lte=date_to)
    return bills


TOTALS = dict(
    count=Count('id'),
    successful=Count('id', filter=Q(status='SUCCESSFUL')),
    failed=Count('id', filter=Q(status='FAILED')),
    pending=Count('id', filter=Q(status='PENDING')),
    collected=Sum('amount', filter=Q(status='SUCCESSFUL')),
)


def _with_rate(row):
    """Fill in collected/success_rate on an aggregate row of TOTALS."""
    row['collected'] = row.get('collected') or 0
    finished = row['successful'] + row['failed']
    row['success_rate'] = round(100 * row['successful'] / finished, 1) if finished else None
    return row


@staff_required
def overview(request):
    bills = EBill.objects.all()
    totals = _with_rate(bills.aggregate(**TOTALS))

    # Daily volume for the last 14 days, with empty days filled in
    today = timezone.localdate()
    start = today - timedelta(days=13)
    daily = {
        row['day']: row
        for row in bills.filter(request_datetime__date__gte=start)
        .annotate(day=TruncDate('request_datetime'))
        .values('day')
        .annotate(
            count=Count('id'),
            amount=Sum('amount', filter=Q(status='SUCCESSFUL')),
        )
    }
    chart = []
    for i in range(14):
        day = start + timedelta(days=i)
        row = daily.get(day, {})
        chart.append({
            'label': day.strftime('%d %b'),
            'count': row.get('count', 0),
            'amount': row.get('amount') or 0,
        })

    by_app = (
        bills.values('app')
        .annotate(
            count=Count('id'),
            successful=Count('id', filter=Q(status='SUCCESSFUL')),
            collected=Sum('amount', filter=Q(status='SUCCESSFUL')),
        )
        .order_by('-count')
    )

    return render(request, 'dashboard/overview.html', {
        'nav': 'overview',
        'totals': totals,
        'chart': chart,
        'by_app': by_app,
        'recent': bills.order_by('-request_datetime')[:8],
        'app_count': Application.objects.count(),
    })


@staff_required
def pay(request):
    """Send a MoMo payment request through /bill/ and follow it to completion."""
    return render(request, 'dashboard/pay.html', {
        'nav': 'pay',
        'apps': Application.objects.order_by('name'),
    })


@staff_required
def transactions(request):
    bills = _filtered_bills(request.GET)

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="transactions.csv"'
        writer = csv.writer(response)
        writer.writerow(['Date', 'Reference', 'App', 'Username', 'Payer name', 'Payer number', 'Device ID',
                         'Amount', 'Status', 'Financial Transaction ID', 'Completed'])
        for b in bills:
            writer.writerow([b.request_datetime.isoformat(), b.uuid, b.app, b.username, b.momo_name,
                             b.momo_number, b.device_id,
                             b.amount, b.status, b.financial_transaction_id,
                             b.request_completed_datetime.isoformat() if b.request_completed_datetime else ''])
        return response

    page = Paginator(bills, 25).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'dashboard/transactions.html', {
        'nav': 'transactions',
        'page': page,
        'statuses': STATUSES,
        'apps': EBill.objects.values_list('app', flat=True).distinct().order_by('app'),
        'filters': request.GET,
        'querystring': params.urlencode(),
        'total_amount': bills.aggregate(s=Sum('amount'))['s'] or 0,
        'unfinished_count': bills.filter(transaction_complete=False).count(),
    })


@staff_required
def transaction_detail(request, pk):
    bill = get_object_or_404(EBill, pk=pk)
    return render(request, 'dashboard/transaction_detail.html', {
        'nav': 'transactions',
        'bill': bill,
    })


@staff_required
@require_POST
def transaction_check(request, pk):
    """Ask MTN for this transaction's current status and record it if final."""
    bill = get_object_or_404(EBill, pk=pk)
    token = get_mtn_token()
    if token is None:
        messages.error(request, 'Could not get an access token from MTN. Check the MTN credentials and try again.')
        return redirect('dashboard:transaction_detail', pk=pk)

    outcome, status = check_with_mtn(bill, token)
    if outcome == 'updated':
        messages.success(request, f'MTN reports {status}. The transaction has been updated.')
    elif outcome == 'unchanged':
        messages.info(request, f'MTN reports {status or "no status"}. Nothing changed.')
    elif outcome == 'not_found':
        messages.error(request, 'MTN has no record of this reference. The request probably never reached MTN.')
    else:
        messages.error(request, f'Could not check with MTN: {status}')
    return redirect('dashboard:transaction_detail', pk=pk)


CHECK_BATCH_SIZE = 15


@staff_required
@require_POST
def transactions_check(request):
    """Check one batch of the filtered, unfinished transactions with MTN.

    The page calls this repeatedly, passing the last id it saw as `after`, so a
    large backlog is worked through in short requests instead of one that times out.
    """
    unfinished = _filtered_bills(request.POST).filter(transaction_complete=False).order_by('pk')
    after = _int(request.POST.get('after'), 0, 0, 2 ** 62)
    fail_not_found = request.POST.get('fail_not_found') == '1'
    batch = list(unfinished.filter(pk__gt=after)[:CHECK_BATCH_SIZE])
    if not batch:
        return JsonResponse({'done': True, 'checked': 0, 'after': after, 'remaining': 0, 'counts': {}})

    token = get_mtn_token()
    if token is None:
        return JsonResponse({'error': 'Could not get an access token from MTN. Check the MTN credentials.'},
                            status=503)

    counts = {'successful': 0, 'failed': 0, 'pending': 0, 'not_found': 0, 'error': 0}
    for bill in batch:
        outcome, status = check_with_mtn(bill, token)
        if outcome == 'updated':
            counts['successful' if status == 'SUCCESSFUL' else 'failed'] += 1
        elif outcome == 'unchanged':
            counts['pending'] += 1
        elif outcome == 'not_found':
            if fail_not_found and apply_final_status(bill, 'FAILED'):
                counts['failed'] += 1
            else:
                counts['not_found'] += 1
        else:
            counts['error'] += 1

    last = batch[-1].pk
    remaining = unfinished.filter(pk__gt=last).count()
    return JsonResponse({'done': remaining == 0, 'checked': len(batch), 'after': last,
                         'remaining': remaining, 'counts': counts})


@staff_required
def applications(request):
    form = ApplicationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        app = form.save()
        messages.success(request, f'Application "{app.name}" registered.')
        return redirect('dashboard:applications')

    apps = Application.objects.order_by('name')
    stats = {
        row['app']: row
        for row in EBill.objects.values('app').annotate(
            count=Count('id'),
            collected=Sum('amount', filter=Q(status='SUCCESSFUL')),
        )
    }
    for app in apps:
        app.stats = stats.get(app.name, {})

    return render(request, 'dashboard/applications.html', {
        'nav': 'applications',
        'apps': apps,
        'form': form,
    })


@staff_required
def application_edit(request, pk):
    app = get_object_or_404(Application, pk=pk)
    form = ApplicationForm(request.POST or None, instance=app)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Application "{app.name}" updated.')
        return redirect('dashboard:applications')
    return render(request, 'dashboard/application_edit.html', {
        'nav': 'applications',
        'app': app,
        'form': form,
    })


@staff_required
@require_POST
def application_delete(request, pk):
    app = get_object_or_404(Application, pk=pk)
    app.delete()
    messages.success(request, f'Application "{app.name}" removed.')
    return redirect('dashboard:applications')


@staff_required
def callbacks(request):
    logs = CallBacks.objects.order_by('-date')
    q = request.GET.get('q', '').strip()
    if q:
        logs = logs.filter(Q(contents__icontains=q) | Q(ip_address__icontains=q))
    page = Paginator(logs, 25).get_page(request.GET.get('page'))
    return render(request, 'dashboard/callbacks.html', {
        'nav': 'callbacks',
        'page': page,
        'q': q,
        'querystring': urlencode({'q': q}) if q else '',
    })


@staff_required
def callback_detail(request, pk):
    log = get_object_or_404(CallBacks, pk=pk)
    return render(request, 'dashboard/callback_detail.html', {
        'nav': 'callbacks',
        'log': log,
    })


# ---------- Reports ----------

PERIODS = [
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('half', 'Half-yearly'),
    ('yearly', 'Yearly'),
    ('custom', 'Selected period'),
]


def _int(value, default, lo, hi):
    try:
        return min(max(int(value), lo), hi)
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _month_span(year, first_month, months):
    """First and last day of a run of whole months."""
    last_month = first_month + months - 1
    return date(year, first_month, 1), date(year, last_month, calendar.monthrange(year, last_month)[1])


def _report_range(params, today):
    """Resolve the report period from the query string.

    Returns (period, start, end, label, prev_start, prev_end, selection) with
    inclusive dates; prev_* is the equivalent period immediately before.
    """
    period = params.get('period') if params.get('period') in dict(PERIODS) else 'monthly'
    year = _int(params.get('year'), today.year, 2000, 2100)
    sel = {'year': year}

    if period == 'monthly':
        month = _int(params.get('month'), today.month, 1, 12)
        sel['month'] = month
        start, end = _month_span(year, month, 1)
        label = start.strftime('%B %Y')
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
    elif period == 'quarterly':
        quarter = _int(params.get('quarter'), (today.month - 1) // 3 + 1, 1, 4)
        sel['quarter'] = quarter
        start, end = _month_span(year, 3 * quarter - 2, 3)
        label = f'Q{quarter} {year} ({start:%b} – {end:%b})'
        prev_start, prev_end = (_month_span(year, 3 * quarter - 5, 3) if quarter > 1
                                else _month_span(year - 1, 10, 3))
    elif period == 'half':
        half = _int(params.get('half'), 1 if today.month <= 6 else 2, 1, 2)
        sel['half'] = half
        start, end = _month_span(year, 1 if half == 1 else 7, 6)
        label = f'H{half} {year} ({start:%b} – {end:%b})'
        prev_start, prev_end = _month_span(year, 1, 6) if half == 2 else _month_span(year - 1, 7, 6)
    elif period == 'yearly':
        start, end = date(year, 1, 1), date(year, 12, 31)
        label = str(year)
        prev_start, prev_end = date(year - 1, 1, 1), date(year - 1, 12, 31)
    else:
        start = _parse_date(params.get('from')) or today.replace(day=1)
        end = _parse_date(params.get('to')) or today
        if end < start:
            start, end = end, start
        sel.update({'from': start.isoformat(), 'to': end.isoformat()})
        label = f'{start:%d %b %Y} – {end:%d %b %Y}'
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - (end - start)

    return period, start, end, label, prev_start, prev_end, sel


def _buckets(start, end):
    """Breakdown rows for the range: days for up to ~2 months, months beyond that."""
    if (end - start).days <= 62:
        return 'day', [start + timedelta(days=i) for i in range((end - start).days + 1)]
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return 'month', months


def _delta(now, before):
    if not before:
        return None
    return round(100 * (now - before) / before, 1)


@staff_required
def reports(request):
    today = timezone.localdate()
    period, start, end, label, prev_start, prev_end, sel = _report_range(request.GET, today)
    app = request.GET.get('app', '')

    bills = EBill.objects.filter(request_datetime__date__gte=start, request_datetime__date__lte=end)
    prev = EBill.objects.filter(request_datetime__date__gte=prev_start, request_datetime__date__lte=prev_end)
    if app:
        bills, prev = bills.filter(app=app), prev.filter(app=app)

    totals = _with_rate(bills.aggregate(**TOTALS))
    prev_totals = _with_rate(prev.aggregate(**TOTALS))
    totals['average'] = totals['collected'] / totals['successful'] if totals['successful'] else 0
    deltas = {
        'collected': _delta(totals['collected'], prev_totals['collected']),
        'count': _delta(totals['count'], prev_totals['count']),
    }

    # Breakdown by day or month, with empty buckets filled in
    unit, buckets = _buckets(start, end)
    if unit == 'day':
        grouped = bills.annotate(bucket=TruncDate('request_datetime'))
        key = lambda d: d
    else:
        grouped = bills.annotate(bucket=TruncMonth('request_datetime'))
        key = lambda d: (d.year, d.month)
    found = {key(row['bucket']): row for row in grouped.values('bucket').annotate(**TOTALS)}
    rows = []
    for bucket in buckets:
        row = found.get(key(bucket))
        row = _with_rate(dict(row) if row else {'count': 0, 'successful': 0, 'failed': 0, 'pending': 0})
        row['date'] = bucket
        row['label'] = bucket.strftime('%a %d %b' if unit == 'day' else '%B %Y')
        rows.append(row)

    by_app = [_with_rate(r) for r in bills.values('app').annotate(**TOTALS).order_by('-collected', '-count')]

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="momo_report_{start}_{end}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Report', label])
        writer.writerow(['From', start.isoformat(), 'To', end.isoformat()])
        writer.writerow(['Application', app or 'All'])
        writer.writerow([])
        writer.writerow(['Day' if unit == 'day' else 'Month', 'Requests', 'Successful', 'Failed', 'Pending',
                         'Success rate %', 'Collected'])
        for r in rows + [dict(totals, date=None)]:
            when = 'Total' if r['date'] is None else (
                r['date'].isoformat() if unit == 'day' else r['date'].strftime('%Y-%m'))
            rate = r['success_rate'] if r['success_rate'] is not None else ''
            writer.writerow([when, r['count'], r['successful'], r['failed'], r['pending'],
                             rate, f"{r['collected']:.2f}"])
        return response

    first = EBill.objects.order_by('request_datetime').values_list('request_datetime', flat=True).first()
    first_year = first.year if first else today.year
    params = request.GET.copy()
    params.pop('export', None)

    return render(request, 'dashboard/reports.html', {
        'nav': 'reports',
        'periods': PERIODS,
        'period': period,
        'sel': sel,
        'app': app,
        'apps': EBill.objects.values_list('app', flat=True).distinct().order_by('app'),
        'years': range(max(today.year, sel['year']), min(first_year, sel['year']) - 1, -1),
        'months': [(i, calendar.month_name[i]) for i in range(1, 13)],
        'label': label,
        'start': start,
        'end': end,
        'prev_start': prev_start,
        'prev_end': prev_end,
        'totals': totals,
        'prev_totals': prev_totals,
        'deltas': deltas,
        'unit': unit,
        'rows': rows,
        'chart': [{'label': r['label'], 'count': r['count'], 'amount': r['collected']} for r in rows],
        'by_app': by_app,
        'querystring': params.urlencode(),
        'generated': timezone.localtime(),
    })
