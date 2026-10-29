"""Ask MTN for the final status of payments still marked PENDING.

    python manage.py recheck_pending --dry-run      # see what would change
    python manage.py recheck_pending                # record the results
    python manage.py recheck_pending --fail-not-found

Safe to run repeatedly (e.g. from a scheduled task): only SUCCESSFUL/FAILED
results are recorded and completed records are never touched again.
"""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from ebilling import this
from ebilling.models import EBill
from ebilling.payments import apply_final_status, check_with_mtn

TOKEN_LIFETIME = timedelta(minutes=50)  # MTN tokens last an hour; renew before that


class Command(BaseCommand):
    help = 'Check PENDING MoMo payments with MTN and record their final status.'

    def add_arguments(self, parser):
        parser.add_argument('--older-than', type=int, default=10, metavar='MINUTES',
                            help='Only check requests at least this old (default 10), so customers '
                                 'still approving on their phone are left alone.')
        parser.add_argument('--limit', type=int, default=None, help='Check at most this many records.')
        parser.add_argument('--fail-not-found', action='store_true',
                            help='Mark records FAILED when MTN has no record of the reference '
                                 '(the request never reached MTN).')
        parser.add_argument('--dry-run', action='store_true', help='Check with MTN but save nothing.')
        parser.add_argument('--pause', type=float, default=0.2, metavar='SECONDS',
                            help='Wait between MTN calls to stay under rate limits (default 0.2).')

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(minutes=opts['older_than'])
        pending = EBill.objects.filter(transaction_complete=False, status='PENDING',
                                       request_datetime__lte=cutoff).order_by('request_datetime')
        if opts['limit']:
            pending = pending[:opts['limit']]
        pending = list(pending)
        if not pending:
            self.stdout.write('No pending payments to check.')
            return

        self.stdout.write(f"Checking {len(pending)} pending payment(s) with MTN"
                          f"{' (dry run, nothing will be saved)' if opts['dry_run'] else ''}...")
        counts = {'SUCCESSFUL': 0, 'FAILED': 0, 'still pending': 0, 'not found': 0, 'error': 0}
        token, token_time = None, None

        for i, ebill in enumerate(pending, 1):
            if token is None or timezone.now() - token_time > TOKEN_LIFETIME:
                token, token_time = this.get_token(), timezone.now()
                if token is None:
                    raise CommandError('Could not get an access token from MTN. Check the MTN credentials in .env.')

            with transaction.atomic():
                outcome, status = check_with_mtn(ebill, token)
                if outcome == 'not_found' and opts['fail_not_found']:
                    apply_final_status(ebill, 'FAILED')
                if opts['dry_run']:
                    transaction.set_rollback(True)

            if outcome == 'updated':
                counts[status] += 1
                label = status
            elif outcome == 'unchanged':
                counts['still pending'] += 1
                label = f'still {status or "unknown"}'
            elif outcome == 'not_found':
                counts['not found'] += 1
                label = 'not found at MTN' + (' -> FAILED' if opts['fail_not_found'] else '')
            else:
                counts['error'] += 1
                label = f'error: {status}'
            self.stdout.write(f'  [{i}/{len(pending)}] {ebill.uuid} '
                              f'({ebill.request_datetime:%Y-%m-%d %H:%M}, {ebill.amount}): {label}')

            if opts['pause']:
                time.sleep(opts['pause'])

        summary = ', '.join(f'{name}: {n}' for name, n in counts.items() if n)
        self.stdout.write(self.style.SUCCESS(f'Done. {summary}'))
        if counts['not found'] and not opts['fail_not_found']:
            self.stdout.write('Re-run with --fail-not-found to mark the not-found records FAILED.')
