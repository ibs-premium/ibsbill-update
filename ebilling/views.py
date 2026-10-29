from django.http import HttpResponse, JsonResponse
import uuid
from django.views.decorators.csrf import csrf_exempt
import json
from . import this
from .payments import FINAL_STATUSES, apply_final_status, payer_number, record_payer
from .models import Application, EBill, CallBacks


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

    username = data.get('username') or ''
    ref_id = str(uuid.uuid4())
    token = this.get_token()
    if token is None:
        return JsonResponse({"status": "error", "message": "Could not obtain access token. Please try again."}, status=503)

    # Registered MoMo name of the payer, for records and receipts ('' if MTN won't say)
    momo_name = this.get_account_holder_name(token, momo_number)

    # externalId is echoed back in MTN's callback body, so it must be our reference
    # (the X-Reference-Id header we send is not included in the callback).
    api_request_result = this.request_to_pay(token, amount, momo_number, ref_id, external_id=ref_id)
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
        momo_number=momo_number,
        momo_name=momo_name,
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
        },
        "payer": {"momo_number": momo_number, "momo_name": momo_name},
    })


@csrf_exempt
def mtn_callback(request):
    """
    MTN MoMo calls this URL when a payment is finalised.
    This updates our local EBill record with the final status.
    eBilling then picks it up by polling /bill/callback/.
    MTN delivers request-to-pay callbacks as PUT; POST is accepted too.
    """
    if request.method not in ('PUT', 'POST'):
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

    # Our reference arrives as externalId (see bill()); the other fields and the
    # header are checked too in case MTN's payload format differs.
    candidates = [ref for ref in (data.get('externalId'),
                                  data.get('referenceId'),
                                  data.get('reference_id'),
                                  data.get('X-Reference-Id'),
                                  request.headers.get('X-Reference-Id')) if ref]
    mtn_status = data.get('status')  # 'SUCCESSFUL', 'FAILED', 'PENDING'

    ebill = EBill.objects.filter(uuid__in=candidates).first() if candidates else None
    if ebill is None:
        # Unknown reference — respond 200 so MTN doesn't retry
        return JsonResponse({"ok": True, "message": "Callback acknowledged"})

    record_payer(ebill, payer_number(data))

    # Idempotency: completed records and non-final statuses are left unchanged
    if ebill.transaction_complete:
        return JsonResponse({"ok": True, "message": "Already processed"})
    if not apply_final_status(ebill, mtn_status, data.get('financialTransactionId', '')):
        return JsonResponse({"ok": True, "message": f"Status {mtn_status or 'missing'}; nothing recorded"})
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
        if ebill.status in FINAL_STATUSES:
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
    except json.JSONDecodeError:
        mtn_data = {}
    if isinstance(mtn_data, dict) and mtn_data.get('status') in FINAL_STATUSES:
        ebill = EBill.objects.filter(uuid=reference_id).first()
        if ebill:
            record_payer(ebill, payer_number(mtn_data))
            apply_final_status(ebill, mtn_data['status'], mtn_data.get('financialTransactionId', ''))

    return JsonResponse(result)


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get("REMOTE_ADDR")