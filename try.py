# views.py

from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
import uuid
import requests
import base64
import json
from decouple import config


# ---------- YOUR CONFIG HERE ----------
SUBSCRIPTION_KEY = config('MTN_SUBSCRIPTION_KEY')
API_USER = config('MTN_API_USER')
API_KEY = config('MTN_API_KEY')
CALLBACK_URL = config('MTN_CALLBACK_URL')
CURRENCY = config('MTN_CURRENCY')
ENVIRONMENT = config('MTN_ENVIRONMENT')
# --------------------------------------

# STEP 1: Generate access token
def get_token():
    url = "https://proxy.momoapi.mtn.com/collection/token/"
    credentials = f"{API_USER}:{API_KEY}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Ocp-Apim-Subscription-Key': SUBSCRIPTION_KEY
    }
    response = requests.post(url, headers=headers)
    if response.status_code == 200:
        token = response.json().get('access_token')
        print("Access Token Generated")
        return token
    else:
        print("Failed to generate token:", response.text)
        return None

# STEP 2: Send payment request
def request_to_pay(token, amount, payer_number, external_id="invoice_123456"):
    ref_id = str(uuid.uuid4())
    url = "https://proxy.momoapi.mtn.com/collection/v1_0/requesttopay"

    headers = {
        'Authorization': f'Bearer {token}',
        'X-Reference-Id': ref_id,
        'X-Callback-Url': CALLBACK_URL,
        'X-Target-Environment': ENVIRONMENT,
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': SUBSCRIPTION_KEY
    }

    body = {
        "amount": str(amount),
        "currency": CURRENCY,
        "externalId": external_id,
        "payer": {
            "partyIdType": "MSISDN",
            "partyId": payer_number
        },
        "payerMessage": "Please approve payment",
        "payeeNote": "Thank you for your business"
    }

    response = requests.post(url, headers=headers, json=body)

    if response.status_code == 202:
        print(f"Payment request sent. Ref ID: {ref_id}")
        return {"success": True, "reference_id": ref_id}
    else:
        try:
            error_data = response.json()
            print("Payment request failed:", json.dumps(error_data, indent=4))
            return JsonResponse(error_data, status=response.status_code, json_dumps_params={'indent': 4})
        except Exception:
            print("Payment request failed:", response.text)
            return HttpResponse(f"Payment request failed:\n\n{response.text}", content_type="text/plain")


# STEP 3: Optional - check status of transaction
def check_status(ref_id, token):
    url = f"https://proxy.momoapi.mtn.com/collection/v1_0/requesttopay/{ref_id}"
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Target-Environment': ENVIRONMENT,
        'Ocp-Apim-Subscription-Key': SUBSCRIPTION_KEY
    }

    response = requests.get(url, headers=headers)
    try:
        return JsonResponse(response.json(), json_dumps_params={'indent': 4})
    except Exception:
        return HttpResponse(response.text, content_type="text/plain")


# View to handle GET (form) and POST (payment request)
def index(request):
    token = get_token()
    # return HttpResponse(token)
    if token:
        result = request_to_pay(token, 1, '233241995223')
        return result if isinstance(result, (JsonResponse, HttpResponse)) else JsonResponse(result)
    else:
        return JsonResponse({"error": "Token generation failed"}, status=500)


# Callback URL for MTN to notify you of payment result
def callback(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            print("Callback received (POST):", json.dumps(data, indent=4))
            return JsonResponse({"status": "Callback received"}, status=200)
        except Exception as e:
            print("Error in callback:", e)
            return JsonResponse({"error": "Invalid callback payload"}, status=400)
    else:
        return HttpResponse('Callback received (GET)', content_type="text/plain")
