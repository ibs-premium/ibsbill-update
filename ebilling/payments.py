"""Recording the final outcome of MTN MoMo payment requests.

Every place that learns a payment's result (the MTN callback, eBilling's status
polling, the dashboard's "Check with MTN" button and the recheck_pending
command) goes through apply_final_status so they all record it the same way.
"""
import json

from django.core.cache import cache
from django.utils import timezone

from . import this

FINAL_STATUSES = ('SUCCESSFUL', 'FAILED')
TOKEN_CACHE_KEY = 'mtn_collection_token'
TOKEN_CACHE_SECONDS = 50 * 60  # MTN tokens last an hour; renew before that


def get_mtn_token():
    """An MTN access token, reused across requests until shortly before it expires."""
    token = cache.get(TOKEN_CACHE_KEY)
    if token is None:
        token = this.get_token()
        if token is not None:
            cache.set(TOKEN_CACHE_KEY, token, TOKEN_CACHE_SECONDS)
    return token


def apply_final_status(ebill, status, financial_transaction_id=''):
    """Record a SUCCESSFUL/FAILED result on an EBill once.

    Returns True if the record changed. Non-final statuses (e.g. PENDING) and
    already-completed records are left alone, so repeated callbacks are harmless.
    """
    if status not in FINAL_STATUSES or ebill.transaction_complete:
        return False
    ebill.status = status
    ebill.transaction_complete = True
    ebill.request_completed_datetime = timezone.now()
    if financial_transaction_id:
        ebill.financial_transaction_id = financial_transaction_id
    ebill.save(update_fields=['status', 'transaction_complete', 'request_completed_datetime',
                              'financial_transaction_id'])
    return True


def record_payer(ebill, number='', token=None):
    """Fill in the payer's MoMo number and name on an EBill if they're missing.

    The number comes from MTN's payloads (payer.partyId); with a token the name is
    looked up from MTN. Existing values are never overwritten.
    """
    fields = []
    if number and not ebill.momo_number:
        ebill.momo_number = number
        fields.append('momo_number')
    if token and ebill.momo_number and not ebill.momo_name:
        name = this.get_account_holder_name(token, ebill.momo_number)
        if name:
            ebill.momo_name = name
            fields.append('momo_name')
    if fields:
        ebill.save(update_fields=fields)


def payer_number(mtn_data):
    """The payer's MSISDN from an MTN callback/status payload, or ''."""
    payer = mtn_data.get('payer') if isinstance(mtn_data, dict) else None
    return payer.get('partyId', '') if isinstance(payer, dict) else ''


def check_with_mtn(ebill, token):
    """Ask MTN for the current status of an EBill and record it if final.

    Returns (outcome, mtn_status) where outcome is one of
    'updated', 'unchanged', 'not_found' or 'error'.
    """
    result = this.check_status(ebill.uuid, token)
    if result.get('status_code') == 404:
        return 'not_found', None
    if result.get('status_code') == 401:
        cache.delete(TOKEN_CACHE_KEY)  # token rejected; fetch a fresh one next time
        return 'error', 'MTN rejected the access token; try again'
    if not result.get('success'):
        return 'error', result.get('message')
    try:
        data = json.loads(result.get('raw_response_text') or '{}')
    except json.JSONDecodeError:
        return 'error', 'MTN returned an unreadable response'
    status = data.get('status')
    record_payer(ebill, payer_number(data), token)
    changed = apply_final_status(ebill, status, data.get('financialTransactionId', ''))
    return ('updated' if changed else 'unchanged'), status
