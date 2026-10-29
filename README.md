# eBilling MoMo Gateway (ibsbill)

A Django service that collects **MTN Mobile Money** payments for IBS eBilling. eBilling (and any other registered application) asks the gateway to charge a customer's MoMo wallet; the gateway sends the request-to-pay to MTN, records the result, and lets eBilling poll for the outcome.

It also includes a staff **dashboard** for taking payments, following up stuck ones, and reporting.

- Staff guide: [docs/STAFF_MANUAL.md](docs/STAFF_MANUAL.md), also as
  [Word](docs/eBilling_MoMo_Staff_Manual.docx) and [PDF](docs/eBilling_MoMo_Staff_Manual.pdf) for sharing and printing

## Features

- **Payment API** for eBilling: start a payment, poll its status, receive MTN's callback.
- **Staff dashboard** at `/dashboard/` (staff accounts only):
  - Overview with totals, success rate and a 14-day chart.
  - MoMo Payment page to send a payment prompt and follow it live.
  - Transactions list with search, filters, CSV export and a detail page per payment.
  - Check one payment, or every filtered unfinished payment, with MTN.
  - Reports: monthly, quarterly, half-yearly, yearly or a chosen date range, compared with the previous period; CSV export and print.
  - Callback logs (raw MTN callbacks) and application management.
- Payer **MoMo number and registered name** recorded on every payment.
- `recheck_pending` management command to settle stuck payments from the server.

## Requirements

- Python 3.10+
- Packages in `requirements.txt` (Django, django-cors-headers, python-decouple, requests, pytz)
- MTN MoMo **Collection** API credentials (subscription key, API user, API key)

> `requirements.txt` pins Django 5.2.1; the code and tests have also been run on Django 6.0.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root (it is git-ignored):

```ini
SECRET_KEY=<long random string>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# MTN MoMo Collection API
MTN_SUBSCRIPTION_KEY=<subscription key>
MTN_API_USER=<api user uuid>
MTN_API_KEY=<api key>
MTN_CALLBACK_URL=https://<your-domain>/bill/mtn-callback/
MTN_CURRENCY=GHS
MTN_ENVIRONMENT=mtnghana

# Outgoing email (password reset)
EMAIL_HOST_USER=<gmail address>
EMAIL_HOST_PASSWORD=<app password>
```

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret key. Generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"`. |
| `DEBUG` | `True` for development only. |
| `ALLOWED_HOSTS` | Comma-separated host names the server answers to. |
| `MTN_SUBSCRIPTION_KEY`, `MTN_API_USER`, `MTN_API_KEY` | MTN Collection credentials. |
| `MTN_CALLBACK_URL` | Public **HTTPS** URL of `/bill/mtn-callback/`. MTN sends payment results here. |
| `MTN_CURRENCY` | Currency code sent to MTN and shown in the dashboard (e.g. `GHS`). |
| `MTN_ENVIRONMENT` | MTN target environment (e.g. `mtnghana`, or `sandbox` for testing). |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP login (Gmail) for outgoing mail. |

Then create the database tables and a first staff user:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open <http://127.0.0.1:8000/dashboard/> and sign in. `/` redirects to the dashboard.

Register each calling system (e.g. `diamond-ebilling`) under **Applications** before it calls the API.

## How a payment works

```
eBilling ──POST /bill/──────────────▶ gateway ──request-to-pay──▶ MTN ──prompt──▶ customer's phone
                                        │  saves EBill (PENDING)                      │ approves / declines
eBilling ──POST /bill/callback/ ─────▶ │ ◀──── PUT /bill/mtn-callback/ ──────────────┘ (MTN callback)
          (polls until final)           │ ──GET requesttopay/{ref}──▶ MTN  (if no callback yet)
```

1. `/bill/` validates the app and number, looks up the payer's MoMo name, and sends MTN a request-to-pay. Our reference (a UUID) is sent as both `X-Reference-Id` and `externalId`, so MTN's callback can be matched to the payment.
2. MTN prompts the customer. When they answer, MTN calls `MTN_CALLBACK_URL`. The callback is logged in **Callback Logs** and the payment is marked `SUCCESSFUL` or `FAILED`.
3. eBilling polls `/bill/callback/`. If the result is already stored it is returned from cache; otherwise the gateway asks MTN and stores any final result.
4. Stuck payments can be checked from the dashboard or with `recheck_pending`.

All four paths record the outcome through `ebilling/payments.py:apply_final_status`, so a payment is completed once and never changed afterwards.

## API

All endpoints take and return JSON. They are CSRF-exempt and meant for server-to-server calls.

### `POST /bill/`: start a payment

```json
{
  "app": "diamond-ebilling",
  "app_key": "<application key>",
  "amount": 20.00,
  "momo_number": "0241234567",
  "device_id": "MTR-001234",
  "username": "ROOM A101"
}
```

`momo_number` is 10 digits starting with `0`, or 12 digits starting with `233`; it must be an MTN number.

Success:

```json
{
  "ok": true,
  "momo_request": {
    "success": true,
    "request_reference_id": "3f2b8c1e-7d4a-4e9b-a6c2-1b5d9e0f7a43",
    "token": "<MTN access token>"
  },
  "payer": { "momo_number": "233241234567", "momo_name": "KOFI MENSAH" }
}
```

MTN refused the request: `{"ok": false, "momo_request": {"success": false, "message": "..."}}`.
Errors: `403` unknown app, `400` invalid JSON/amount/number, `503` no MTN token.

### `POST /bill/callback/`: poll a payment

```json
{ "reference_id": "3f2b8c1e-...", "token": "<token from /bill/>" }
```

When the result is stored: `{"status": "SUCCESSFUL", "source": "cache", "raw_response_text": "{...}"}`.
Otherwise the gateway asks MTN and returns MTN's answer (with `raw_response_text` containing MTN's JSON, whose `status` is `PENDING`, `SUCCESSFUL` or `FAILED`).

### `PUT /bill/mtn-callback/`: MTN's result callback

Called by MTN, not by eBilling. Accepts `PUT` and `POST`. Every call is stored in `CallBacks`. The payment is found by `externalId` (also `referenceId` or the `X-Reference-Id` header); repeat or `PENDING` callbacks change nothing. Any valid JSON gets `200` (unknown references included) so MTN doesn't retry; invalid JSON gets `400`.

## Dashboard pages

| URL | Page |
|---|---|
| `/dashboard/` | Overview |
| `/dashboard/pay/` | MoMo Payment |
| `/dashboard/transactions/` | Transactions (`?q=&status=&app=&from=&to=`, `&export=csv`) |
| `/dashboard/transactions/<id>/` | Transaction detail |
| `/dashboard/reports/` | Reports (`?period=monthly|quarterly|half|yearly|custom`) |
| `/dashboard/callbacks/` | Callback logs |
| `/dashboard/applications/` | Applications |
| `/admin/` | Django admin (user accounts) |

Only active users with **Staff status** can sign in.

## Management command

```bash
python manage.py recheck_pending --dry-run          # check with MTN, save nothing
python manage.py recheck_pending                    # record final results
python manage.py recheck_pending --fail-not-found   # also fail references MTN has no record of
```

Options: `--older-than MINUTES` (default 10), `--limit N`, `--pause SECONDS` (default 0.2). Safe to run on a schedule.

## Tests

```bash
python manage.py test ebilling
```

MTN is mocked throughout; the tests never call the real API.

## Project layout

```
ibsbill/                 Django project (settings, root URLs)
ebilling/
  views.py               Payment API: /bill/, /bill/callback/, /bill/mtn-callback/
  this.py                MTN API client (token, request-to-pay, status, payer name)
  payments.py            Recording results and payer details; MTN token cache
  dashboard.py           Staff dashboard views
  dashboard_urls.py      Dashboard routes
  forms.py               Application and staff login forms
  models.py              EBill (payments), Application, CallBacks, User
  management/commands/   recheck_pending
  templatetags/          money, status and JSON display filters
  tests.py
templates/dashboard/     Dashboard templates
static/dashboard/        Dashboard CSS and IBS / eBilling logos
docs/STAFF_MANUAL.md     Staff user manual
```

## Deployment notes

- Set `DEBUG=False`, a real `SECRET_KEY` and the production `ALLOWED_HOSTS`.
- Run `python manage.py collectstatic` and serve `staticfiles/` from the web server.
- `MTN_CALLBACK_URL` must be reachable by MTN over HTTPS.
- Run `python manage.py migrate` after every update. Migration `0003_sync_ebill_with_model` removes the unused `meter_credited` column, which otherwise makes new payments fail to save.
- Some existing databases list a migration `0002_ebill_momo_number` that isn't in this repository. It is harmless, but check that production's schema matches the models before deploying.
- Consider scheduling `recheck_pending` every 15 minutes.
