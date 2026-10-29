import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .models import Application, CallBacks, EBill


def mtn_status_response(status, code=200, financial_id='FIN-1', payer=None):
    """Shape of this.check_status() output for a given MTN status."""
    if code != 200:
        return {'success': False, 'status_code': code, 'raw_response_text': '{}', 'message': 'not found'}
    body = {'status': status, 'financialTransactionId': financial_id, 'externalId': 'x'}
    if payer:
        body['payer'] = {'partyIdType': 'MSISDN', 'partyId': payer}
    return {'success': True, 'status_code': 200, 'raw_response_text': json.dumps(body)}


class PaymentTestCase(TestCase):
    def setUp(self):
        cache.clear()  # don't let a cached MTN token leak between tests

    def make_bill(self, **kwargs):
        fields = dict(app='ebilling', app_key='k', app_ip='127.0.0.1', app_url='http://x', amount=20,
                      username='u', token='t', uuid=str(uuid.uuid4()), device_id='MTR-1', status='PENDING')
        fields.update(kwargs)
        return EBill.objects.create(**fields)


class BillTests(PaymentTestCase):
    @mock.patch('ebilling.this.get_account_holder_name', return_value='KOFI MENSAH')
    @mock.patch('ebilling.this.request_to_pay')
    @mock.patch('ebilling.this.get_token', return_value='tok')
    def test_reference_is_sent_as_external_id(self, _token, request_to_pay, lookup):
        Application.objects.create(name='ebilling', url='http://x', key='k', ip_address='127.0.0.1')
        request_to_pay.side_effect = lambda token, amount, number, ref_id, external_id: {
            'success': True, 'status_code': 202, 'reference_id': ref_id, 'message': 'ok'}

        r = self.client.post('/bill/', json.dumps({
            'app': 'ebilling', 'app_key': 'k', 'amount': 10, 'momo_number': '0241234567', 'device_id': 'MTR-9',
        }), content_type='application/json')

        self.assertEqual(r.status_code, 200)
        args, kwargs = request_to_pay.call_args
        ref_id = args[3]
        self.assertEqual(kwargs['external_id'], ref_id)
        bill = EBill.objects.get()
        self.assertEqual(bill.uuid, ref_id)

        # payer details: number normalised to 233…, name looked up from MTN
        lookup.assert_called_once_with('tok', '233241234567')
        self.assertEqual((bill.momo_number, bill.momo_name), ('233241234567', 'KOFI MENSAH'))
        self.assertEqual(r.json()['payer'], {'momo_number': '233241234567', 'momo_name': 'KOFI MENSAH'})


class CallbackTests(PaymentTestCase):
    def callback(self, body, method='put', **headers):
        send = getattr(self.client, method)
        return send('/bill/mtn-callback/', json.dumps(body), content_type='application/json', headers=headers)

    def test_put_callback_marks_success(self):
        bill = self.make_bill()
        r = self.callback({'externalId': bill.uuid, 'status': 'SUCCESSFUL', 'financialTransactionId': '123'})
        self.assertEqual(r.status_code, 200)
        bill.refresh_from_db()
        self.assertEqual(bill.status, 'SUCCESSFUL')
        self.assertTrue(bill.transaction_complete)
        self.assertEqual(bill.financial_transaction_id, '123')
        self.assertIsNotNone(bill.request_completed_datetime)
        self.assertEqual(CallBacks.objects.get().method, 'PUT')

    def test_post_still_accepted_and_get_rejected(self):
        bill = self.make_bill()
        self.assertEqual(self.callback({'externalId': bill.uuid, 'status': 'FAILED'}, method='post').status_code, 200)
        self.assertEqual(self.client.get('/bill/mtn-callback/').status_code, 405)

    def test_failure_is_recorded_as_complete(self):
        bill = self.make_bill()
        self.callback({'externalId': bill.uuid, 'status': 'FAILED'})
        bill.refresh_from_db()
        self.assertEqual(bill.status, 'FAILED')
        self.assertTrue(bill.transaction_complete)
        self.assertIsNotNone(bill.request_completed_datetime)

    def test_reference_in_header_is_matched(self):
        bill = self.make_bill()
        self.callback({'externalId': 'MTR-1', 'status': 'SUCCESSFUL'}, X_Reference_Id=bill.uuid)
        bill.refresh_from_db()
        self.assertEqual(bill.status, 'SUCCESSFUL')

    def test_pending_and_repeat_callbacks_change_nothing(self):
        bill = self.make_bill()
        self.callback({'externalId': bill.uuid, 'status': 'PENDING'})
        bill.refresh_from_db()
        self.assertEqual(bill.status, 'PENDING')
        self.assertFalse(bill.transaction_complete)

        self.callback({'externalId': bill.uuid, 'status': 'SUCCESSFUL'})
        r = self.callback({'externalId': bill.uuid, 'status': 'FAILED'})
        bill.refresh_from_db()
        self.assertEqual(bill.status, 'SUCCESSFUL')
        self.assertEqual(r.json()['message'], 'Already processed')

    def test_callback_fills_in_missing_payer_number(self):
        bill = self.make_bill()
        self.callback({'externalId': bill.uuid, 'status': 'SUCCESSFUL',
                       'payer': {'partyIdType': 'MSISDN', 'partyId': '233241112222'}})
        bill.refresh_from_db()
        self.assertEqual(bill.momo_number, '233241112222')

    def test_unknown_reference_is_acknowledged(self):
        r = self.callback({'externalId': str(uuid.uuid4()), 'status': 'SUCCESSFUL'})
        self.assertEqual(r.status_code, 200)


class BillStatusTests(PaymentTestCase):
    @mock.patch('ebilling.this.check_status', return_value=mtn_status_response('FAILED'))
    def test_polling_records_failure(self, _check):
        bill = self.make_bill()
        r = self.client.post('/bill/callback/', json.dumps({'reference_id': bill.uuid, 'token': 't'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        bill.refresh_from_db()
        self.assertEqual(bill.status, 'FAILED')
        self.assertTrue(bill.transaction_complete)

    @mock.patch('ebilling.this.check_status')
    def test_final_status_served_from_cache(self, check):
        bill = self.make_bill(status='SUCCESSFUL', transaction_complete=True)
        r = self.client.post('/bill/callback/', json.dumps({'reference_id': bill.uuid, 'token': 't'}),
                             content_type='application/json')
        self.assertEqual(r.json()['source'], 'cache')
        check.assert_not_called()


@mock.patch('ebilling.this.get_token', return_value='tok')
class DashboardCheckTests(PaymentTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))

    @mock.patch('ebilling.this.check_status', return_value=mtn_status_response('SUCCESSFUL'))
    def test_check_button_records_result(self, _check, _token):
        bill = self.make_bill()
        r = self.client.post(f'/dashboard/transactions/{bill.pk}/check/', follow=True)
        self.assertContains(r, 'MTN reports SUCCESSFUL')
        bill.refresh_from_db()
        self.assertEqual(bill.status, 'SUCCESSFUL')

    @mock.patch('ebilling.this.check_status', return_value=mtn_status_response(None, code=404))
    def test_check_button_reports_not_found(self, _check, _token):
        bill = self.make_bill()
        r = self.client.post(f'/dashboard/transactions/{bill.pk}/check/', follow=True)
        self.assertContains(r, 'MTN has no record')
        bill.refresh_from_db()
        self.assertEqual(bill.status, 'PENDING')

    def test_check_requires_post(self, _token):
        bill = self.make_bill()
        self.assertEqual(self.client.get(f'/dashboard/transactions/{bill.pk}/check/').status_code, 405)


@mock.patch('ebilling.management.commands.recheck_pending.time.sleep')
@mock.patch('ebilling.this.get_token', return_value='tok')
class RecheckPendingTests(PaymentTestCase):
    def setUp(self):
        super().setUp()
        old = timezone.now() - timedelta(hours=1)
        self.ok, self.missing, self.fresh = (self.make_bill(), self.make_bill(), self.make_bill())
        EBill.objects.filter(pk__in=[self.ok.pk, self.missing.pk]).update(request_datetime=old)

    def fake_mtn(self, ref_id, token):
        return mtn_status_response('SUCCESSFUL') if ref_id == self.ok.uuid else mtn_status_response(None, code=404)

    def run_command(self, *args):
        out = StringIO()
        with mock.patch('ebilling.this.check_status', side_effect=self.fake_mtn) as check:
            call_command('recheck_pending', *args, stdout=out)
        return out.getvalue(), check

    def test_dry_run_saves_nothing(self, *_):
        output, _check = self.run_command('--dry-run', '--fail-not-found')
        self.assertIn('SUCCESSFUL: 1', output)
        self.assertEqual(EBill.objects.filter(status='PENDING').count(), 3)

    def test_records_results_and_skips_recent(self, *_):
        output, check = self.run_command()
        self.assertEqual(check.call_count, 2)  # the fresh request is left alone
        self.assertEqual(EBill.objects.get(pk=self.ok.pk).status, 'SUCCESSFUL')
        self.assertEqual(EBill.objects.get(pk=self.missing.pk).status, 'PENDING')
        self.assertIn('--fail-not-found', output)

    def test_fail_not_found(self, *_):
        self.run_command('--fail-not-found')
        missing = EBill.objects.get(pk=self.missing.pk)
        self.assertEqual(missing.status, 'FAILED')
        self.assertTrue(missing.transaction_complete)


@mock.patch('ebilling.dashboard.CHECK_BATCH_SIZE', 2)
class BulkCheckTests(PaymentTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.pending = [self.make_bill(app='ebilling') for _ in range(3)]
        self.other_app = self.make_bill(app='other')
        self.done = self.make_bill(status='SUCCESSFUL', transaction_complete=True)

    def run_all(self, **extra):
        """Drive the endpoint batch by batch the way the page's script does."""
        after, batches, totals = 0, 0, {}
        while True:
            r = self.client.post('/dashboard/transactions/check/', dict(extra, after=after))
            self.assertEqual(r.status_code, 200)
            data = r.json()
            batches += 1
            for k, n in data['counts'].items():
                totals[k] = totals.get(k, 0) + n
            after = data['after']
            if data['done']:
                return batches, totals

    @mock.patch('ebilling.this.get_token', return_value='tok')
    def test_checks_only_filtered_unfinished_in_batches(self, _token):
        first = self.pending[0].uuid
        fake = lambda ref, tok: mtn_status_response('SUCCESSFUL' if ref == first else 'PENDING')
        with mock.patch('ebilling.this.check_status', side_effect=fake) as check:
            batches, totals = self.run_all(status='PENDING', app='ebilling')
        self.assertEqual(check.call_count, 3)  # other app and completed record skipped
        self.assertEqual(batches, 2)  # batch size 2 -> 2 + 1
        self.assertEqual(totals, {'successful': 1, 'failed': 0, 'pending': 2, 'not_found': 0, 'error': 0})
        self.assertEqual(EBill.objects.get(uuid=first).status, 'SUCCESSFUL')
        self.assertEqual(EBill.objects.get(pk=self.other_app.pk).status, 'PENDING')

    @mock.patch('ebilling.this.get_token', return_value='tok')
    @mock.patch('ebilling.this.check_status', return_value=mtn_status_response(None, code=404))
    def test_fail_not_found_option(self, _check, _token):
        _, totals = self.run_all(app='ebilling', fail_not_found='1')
        self.assertEqual(totals['failed'], 3)
        self.assertFalse(EBill.objects.filter(app='ebilling', status='PENDING').exists())

    @mock.patch('ebilling.this.get_token', return_value=None)
    def test_reports_token_failure(self, _token):
        r = self.client.post('/dashboard/transactions/check/', {'after': 0})
        self.assertEqual(r.status_code, 503)
        self.assertIn('access token', r.json()['error'])

    def test_button_shows_unfinished_count(self):
        r = self.client.get('/dashboard/transactions/?status=PENDING')
        self.assertContains(r, 'Check 4 with MTN')
        r = self.client.get('/dashboard/transactions/?status=SUCCESSFUL')
        self.assertNotContains(r, 'with MTN')


class PayerBackfillTests(PaymentTestCase):
    @mock.patch('ebilling.this.get_account_holder_name', return_value='AMA SERWAA')
    @mock.patch('ebilling.this.check_status', return_value=mtn_status_response('SUCCESSFUL', payer='233249998888'))
    def test_status_check_backfills_number_and_name(self, _check, lookup):
        from .payments import check_with_mtn
        bill = self.make_bill()
        check_with_mtn(bill, 'tok')
        bill.refresh_from_db()
        self.assertEqual((bill.momo_number, bill.momo_name), ('233249998888', 'AMA SERWAA'))
        lookup.assert_called_once_with('tok', '233249998888')

    @mock.patch('ebilling.this.get_account_holder_name')
    @mock.patch('ebilling.this.check_status', return_value=mtn_status_response('PENDING', payer='233200000000'))
    def test_existing_payer_details_are_kept(self, _check, lookup):
        from .payments import check_with_mtn
        bill = self.make_bill(momo_number='233241234567', momo_name='KOFI MENSAH')
        check_with_mtn(bill, 'tok')
        bill.refresh_from_db()
        self.assertEqual((bill.momo_number, bill.momo_name), ('233241234567', 'KOFI MENSAH'))
        lookup.assert_not_called()

    def test_dashboard_shows_and_searches_payer(self):
        self.client.force_login(User.objects.create_user('staff', password='pw', is_staff=True))
        self.make_bill(momo_number='233241234567', momo_name='KOFI MENSAH')
        self.make_bill(momo_number='233559990000', momo_name='YAW BOATENG')
        r = self.client.get('/dashboard/transactions/?q=kofi')
        self.assertContains(r, 'KOFI MENSAH')
        self.assertContains(r, '233241234567')
        self.assertNotContains(r, 'YAW BOATENG')
        csv_text = self.client.get('/dashboard/transactions/?export=csv').content.decode()
        self.assertIn('Payer name,Payer number', csv_text)
        self.assertIn('KOFI MENSAH,233241234567', csv_text)


class AccountHolderLookupTests(TestCase):
    def fake_response(self, status_code, body):
        resp = mock.Mock(status_code=status_code)
        resp.json.return_value = body
        return resp

    @mock.patch('ebilling.this.requests.get')
    def test_name_from_mtn(self, get):
        from . import this
        get.return_value = self.fake_response(200, {'given_name': 'Kofi', 'family_name': 'Mensah'})
        self.assertEqual(this.get_account_holder_name('tok', '233241234567'), 'Kofi Mensah')
        self.assertIn('/accountholder/msisdn/233241234567/basicuserinfo', get.call_args.args[0])
        get.return_value = self.fake_response(200, {'name': 'KOFI MENSAH', 'given_name': 'Kofi'})
        self.assertEqual(this.get_account_holder_name('tok', '233241234567'), 'KOFI MENSAH')

    @mock.patch('ebilling.this.requests.get')
    def test_lookup_failures_return_blank(self, get):
        from . import this
        get.return_value = self.fake_response(404, {})
        self.assertEqual(this.get_account_holder_name('tok', '233241234567'), '')
        get.side_effect = this.requests.exceptions.Timeout()
        self.assertEqual(this.get_account_holder_name('tok', '233241234567'), '')
