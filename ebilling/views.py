from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
import uuid
from django.views.decorators.csrf import csrf_exempt
import json
from . import this
from .models import Application, EBill, CallBacks
from django.utils import timezone


def index(request):
    if request.method == 'GET':
        return render(request, 'index.html')
    return HttpResponse('Invalid Request', status=405)


@csrf_exempt
def bill(request):
    """eBilling app calls this to initiate an MTN MoMo payment request."""
    if request.method != 'POST':
        return HttpResponse('Invalid Request', status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    request_ip = request.META.get('REMOTE_ADDR')
    request_app = data.get("app")
    request_app_url = request.build_absolute_uri()
    request_app_key = data.get('app_key')
    device_id = data.get('device_id')

    try:
        app = Application.objects.get(name=request_app)
    except Application.DoesNotExist:
        return JsonResponse({"status": "Failed", "message": "No registered app found"}, status=403)

    amount = float(data.get('amount', 0))
    if amount <= 0:
        return JsonResponse({"status": "error", "message": "Invalid amount!"}, status=400)

    momo_number = data.get('momo_number')
    validated_number = this.validate_momo_number(momo_number)
    if validated_number is None:
        return JsonResponse({"status": "error", "message": "Invalid MoMo number!"}, status=400)
    momo_number = validated_number

    username = data.get('username')
    ref_id = str(uuid.uuid4())
    token = this.get_token()
    if token is None:
        return JsonResponse({"status": "error", "message": "Could not obtain access token. Please try again."}, status=503)

    api_request_result = this.request_to_pay(token, amount, momo_number, ref_id, external_id=device_id)
    request_status_code = api_request_result.get('status_code')
    request_reference_id = api_request_result.get('reference_id')
    request_message = api_request_result.get('message')
    request_success = api_request_result.get('success', False)

    EBill.objects.create(
        app=request_app,
        app_key=request_app_key,
        app_ip=request_ip,
        app_url=request_app_url,
        amount=amount,
        username=username,
        token=token,
        uuid=ref_id,
        device_id=device_id,
        balance_before=0,
        request_sent=True,
        momo_api_initial_status_code=str(request_status_code),
        momo_api_initial_message=request_message,
        status='PENDING',
    )

    if not request_success:
        return JsonResponse({
            "ok": False,
            "momo_request": {"success": False, "message": request_message}
        })

    return JsonResponse({
        "ok": True,
        "momo_request": {
            "success": True,
            "request_reference_id": request_reference_id,
            "token": token
        }
    })


@csrf_exempt
def mtn_callback(request):
    """
    MTN MoMo calls this URL when a payment is finalised.
    This updates our local EBill record with the final status.
    eBilling then picks it up by polling /bill/callback/.
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Log the raw callback for audit purposes
    try:
        CallBacks.objects.create(
            url=request.build_absolute_uri(),
            method=request.method,
            headers=str(dict(request.headers)),
            contents=request.body.decode('utf-8', errors='replace'),
            query_params=str(dict(request.GET)),
            ip_address=request.META.get('REMOTE_ADDR', '0.0.0.0'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            referrer=request.META.get('HTTP_REFERER', ''),
        )
    except Exception:
        pass  # Logging failure should never block the callback response

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # MTN can send reference in different fields depending on API version
    reference_id = (data.get('referenceId')
                    or data.get('reference_id')
                    or data.get('externalId')
                    or data.get('X-Reference-Id'))
    mtn_status = data.get('status')  # 'SUCCESSFUL', 'FAILED', 'PENDING'

    if not reference_id:
        return JsonResponse({"ok": True, "message": "Callback received; no reference_id found"})

    try:
        ebill = EBill.objects.get(uuid=reference_id)
    except EBill.DoesNotExist:
        # Unknown reference — respond 200 so MTN doesn't retry
        return JsonResponse({"ok": True, "message": "Callback acknowledged"})

    # Idempotency: if already marked as complete, do nothing
    if ebill.transaction_complete:
        return JsonResponse({"ok": True, "message": "Already processed"})

    ebill.status = mtn_status if mtn_status else 'UNKNOWN'
    if mtn_status == 'SUCCESSFUL':
        ebill.transaction_complete = True
        ebill.request_completed_datetime = timezone.now()
        ebill.financial_transaction_id = data.get('financialTransactionId', '')

    ebill.save()
    return JsonResponse({"ok": True, "message": "Callback received and processed"})


@csrf_exempt
def bill_status(request):
    """
    eBilling polls this endpoint to check if a MoMo payment has been finalised.
    Returns our cached status (from MTN callback) if available, otherwise checks
    MTN directly and caches the result.
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    reference_id = data.get('reference_id')
    token = data.get('token')

    if not reference_id or not token:
        return JsonResponse({"error": "reference_id and token are required"}, status=400)

    # Check our local record first (updated by MTN callback — no extra MTN API call needed)
    try:
        ebill = EBill.objects.get(uuid=reference_id)
        if ebill.status in ('SUCCESSFUL', 'FAILED'):
            raw_payload = json.dumps({"status": ebill.status, "reference_id": reference_id})
            return JsonResponse({
                "raw_response_text": raw_payload,
                "status": ebill.status,
                "source": "cache",
            })
    except EBill.DoesNotExist:
        pass

    # Not yet updated by MTN callback — query MTN API directly
    result = this.check_status(reference_id, token)
    raw_text = result.get('raw_response_text', '{}')

    # Cache the final status in our DB so future calls don't need to hit MTN
    try:
        mtn_data = json.loads(raw_text)
        mtn_status = mtn_data.get('status')
        if mtn_status in ('SUCCESSFUL', 'FAILED'):
            try:
                ebill = EBill.objects.get(uuid=reference_id)
                if not ebill.transaction_complete:
                    ebill.status = mtn_status
                    if mtn_status == 'SUCCESSFUL':
                        ebill.transaction_complete = True
                        ebill.request_completed_datetime = timezone.now()
                        ebill.financial_transaction_id = mtn_data.get('financialTransactionId', '')
                    ebill.save()
            except EBill.DoesNotExist:
                pass
    except (json.JSONDecodeError, Exception):
        pass

    return JsonResponse(result)


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get("REMOTE_ADDR")