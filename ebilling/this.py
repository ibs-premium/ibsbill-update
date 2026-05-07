import uuid
import requests
import base64
import json
from django.http import HttpResponse, JsonResponse
SUBSCRIPTION_KEY = '673d7e5e5ef5459681c3928246eff925'        
API_USER = 'bfae8bcd-4348-4c55-a249-437fed1afc0b'             
API_KEY = 'f5a04ca6b90247a2bd170b9b1b4035f7'                  
CALLBACK_URL = 'https://www.ibsbill.org/bill/mtn-callback/'
CURRENCY = 'GHS'                                               
ENVIRONMENT = 'mtnghana'
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
        return token
    else:
        return None

def check_status(ref_id, token):
    url = f"https://proxy.momoapi.mtn.com/collection/v1_0/requesttopay/{ref_id}"
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Target-Environment': ENVIRONMENT, # Make sure ENVIRONMENT is defined
        'Ocp-Apim-Subscription-Key': SUBSCRIPTION_KEY # Make sure SUBSCRIPTION_KEY is defined
    }
    
    try:
        response = requests.get(url, headers=headers)

        status_data = {
            "success": False, # Default to False, update if status indicates success
            "status_code": response.status_code,
            "reference_id": ref_id,
            "headers": dict(response.headers),
            "raw_response_text": response.text, # Include raw text for debugging
            "error_details": None,
            "message": "Failed to retrieve status."
        }

        if response.status_code == 200: # HTTP 200 OK means status was retrieved successfully
            status_data["success"] = True
            try:
                response_json = response.json()
                status_data["data"] = response_json # Contains the actual status details
                status_data["payment_status"] = response_json.get("status") # MoMo typically uses "status" for payment state (PENDING, SUCCESSFUL, FAILED)
                status_data["message"] = f"Payment status retrieved: {status_data['payment_status']}"
            except json.JSONDecodeError:
                status_data["message"] = "Status check succeeded, but response was not valid JSON."
                status_data["error_details"] = {"parsing_error": "Response was not valid JSON."}
            except Exception as e:
                status_data["message"] = f"Status check succeeded, but error parsing JSON: {str(e)}"
                status_data["error_details"] = {"parsing_error": str(e)}
        else:
            status_data["success"] = False
            try:
                error_data = response.json()
                status_data["error_details"] = error_data
                status_data["message"] = f"Status check failed with API error: {error_data.get('message', response.text)}"
            except json.JSONDecodeError:
                status_data["message"] = f"Status check failed with status {response.status_code}, and response was not valid JSON."
                status_data["error_details"] = {"raw_response_text": response.text}
            except Exception as e:
                status_data["message"] = f"Status check failed, and unexpected error occurred during parsing: {str(e)}"
                status_data["error_details"] = {"parsing_error": str(e), "raw_response_text": response.text}

    except requests.exceptions.RequestException as e:
        status_data = {
            "success": False,
            "status_code": None, # No HTTP status code in case of network error
            "reference_id": ref_id,
            "message": f"Network or request error during status check: {str(e)}",
            "error_details": {"exception": str(e)}
        }
    except Exception as e:
        status_data = {
            "success": False,
            "status_code": None,
            "reference_id": ref_id,
            "message": f"An unexpected error occurred during status check: {str(e)}",
            "error_details": {"exception": str(e)}
        }

    return status_data

def request_to_pay(token, amount, payer_number, ref_id, external_id="invoice_123456"):
    url = "https://proxy.momoapi.mtn.com/collection/v1_0/requesttopay"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Reference-Id': ref_id,
        'X-Callback-Url': CALLBACK_URL, # Make sure CALLBACK_URL is defined
        'X-Target-Environment': ENVIRONMENT, # Make sure ENVIRONMENT is defined
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': SUBSCRIPTION_KEY # Make sure SUBSCRIPTION_KEY is defined
    }
    
    body = {
        "amount": str(amount),
        "currency": CURRENCY, # Make sure CURRENCY is defined
        "externalId": external_id,
        "payer": {
            "partyIdType": "MSISDN",
            "partyId": payer_number
        },
        "payerMessage": "Please approve payment for purchase of credit to your meter.",
        "payeeNote": f"Thank for using IBS Ebilling System. Your meter will be credited immediatelly."
    }
    
    try:
        response = requests.post(url, headers=headers, json=body)
        
        response_data = {
            "status_code": response.status_code,
            "headers": dict(response.headers), # Convert headers to a dictionary
            "request_body": body, # Include the request body for completeness
            "request_headers": headers, # Include the request headers
            "reference_id": ref_id, # Always include the ref_id
            "external_id": external_id # Always include the external_id
        }

        if response.status_code == 202:
            response_data["success"] = True
            # The 202 Accepted response usually has an empty body, but we can add more fields if needed
            # For MoMo API's 202, there's usually no body, so we'll just confirm success.
            response_data["message"] = "Payment request accepted for processing."
        else:
            response_data["success"] = False
            try:
                error_data = response.json()
                response_data["error_details"] = error_data
                response_data["message"] = "Payment request failed with API error."
            except json.JSONDecodeError:
                response_data["error_details"] = {"raw_response_text": response.text}
                response_data["message"] = "Payment request failed, and response was not valid JSON."
            except Exception as e:
                response_data["error_details"] = {"parsing_error": str(e), "raw_response_text": response.text}
                response_data["message"] = "Payment request failed with unexpected error during JSON parsing."
                
    except requests.exceptions.RequestException as e:
        # Handle network errors, connection issues, etc.
        response_data = {
            "success": False,
            "status_code": None, # No HTTP status code in case of network error
            "message": f"Network or request error: {str(e)}",
            "error_details": {"exception": str(e)},
            "reference_id": ref_id,
            "external_id": external_id
        }
    except Exception as e:
        # Catch any other unexpected errors
        response_data = {
            "success": False,
            "status_code": None,
            "message": f"An unexpected error occurred: {str(e)}",
            "error_details": {"exception": str(e)},
            "reference_id": ref_id,
            "external_id": external_id
        }

    return response_data
    
def validate_momo_number(momo_number: str) -> str | None:
    momo_number = momo_number.strip()
    if not momo_number.isdigit() or len(momo_number) not in [10, 12]:
        return None
    if len(momo_number) == 10:
        if not momo_number.startswith("0"):
            return None
        if momo_number.startswith(("057", "027", "020", "050")):
            return None
        return "233" + momo_number[1:]

    if len(momo_number) == 12:
        if not momo_number.startswith("233"):
            return None
        if momo_number[3] == "0":
            return None
        if momo_number.startswith(("23357", "23327", "23320", "23350")):
            return None
        return momo_number

    return None
