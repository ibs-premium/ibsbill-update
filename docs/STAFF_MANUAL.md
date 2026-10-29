# eBilling MoMo Gateway — Staff Manual

This manual is for IBS staff who use the eBilling MoMo Gateway dashboard to take MTN Mobile Money payments, follow them up and report on them.

The dashboard lives at **`/dashboard/`** on the gateway server (for example `https://www.ibsbill.org/dashboard/`).

---

## Contents

1. [Signing in and out](#1-signing-in-and-out)
2. [Finding your way around](#2-finding-your-way-around)
3. [Dashboard](#3-dashboard)
4. [Taking a MoMo payment](#4-taking-a-momo-payment)
5. [Transactions](#5-transactions)
6. [Checking payments with MTN](#6-checking-payments-with-mtn)
7. [Reports](#7-reports)
8. [Callback Logs](#8-callback-logs)
9. [Applications](#9-applications)
10. [What the statuses mean](#10-what-the-statuses-mean)
11. [Troubleshooting](#11-troubleshooting)
12. [For administrators](#12-for-administrators)

---

## 1. Signing in and out

1. Open `/dashboard/` in your browser. You are taken to the sign-in page.
2. Enter your **username** and **password**, then select **Login**. Use the eye icon to show or hide the password while typing.
3. You land on the **Dashboard**.

Only **staff accounts** can sign in. If you see *"Your username and password didn't match, or the account isn't staff"*, check your details, then ask an administrator to confirm your account has staff access (see [For administrators](#12-for-administrators)).

**To sign out**, select the **log-out icon** next to your name at the top of the sidebar.

---

## 2. Finding your way around

| Area | What it does |
|---|---|
| **Sidebar** (left) | Your name and the sign-out button at the top, then the pages: Dashboard, MoMo Payment, Transactions, Reports, Callback Logs, Applications and Django Admin. The page you are on is highlighted in green. |
| **Toolbar** (top) | The panel button hides or shows the sidebar. The breadcrumb (*Home › Transactions › …*) shows where you are; select any part of it to go back. |
| **Page title** | The large heading, with the page's main buttons on the right (for example **Export CSV**). |

On a phone, the sidebar is hidden. Tap the panel button to open it and tap outside it to close it.

---

## 3. Dashboard

The Dashboard gives a quick picture of all payments.

- **Collected**: total of all successful payments.
- **Transactions**: number of payment requests, with how many are still pending.
- **Success rate**: successful payments as a share of payments that have finished (successful + failed). Pending payments are not counted.
- **Applications**: how many systems are registered to request payments.
- **Last 14 days**: bars show the number of requests per day; the line shows the amount collected.
- **By application**: amount collected and success count for each registered system.
- **Recent transactions**: the latest eight payments. Select a row to open it.

Buttons: **New MoMo payment** opens the payment page; **Export CSV** downloads every transaction.

---

## 4. Taking a MoMo payment

Use **MoMo Payment** in the sidebar to send a payment request to a customer's phone.

1. Choose the **Application** the payment belongs to (for example `diamond-ebilling`).
2. Enter the customer's **MoMo number**:
   - 10 digits starting with `0` (for example `024 123 4567`), or
   - 12 digits starting with `233` (for example `233241234567`).
   - Spaces are fine. Numbers starting `020`, `027`, `050` or `057` are not MTN numbers and are refused.
3. Enter the **Amount** in cedis.
4. Enter the **Device ID**: the meter serial number being paid for.
5. **Username** is filled in with your username. Change it to the customer's account or room name if your team records it that way.
6. Select **Send payment request**.

The **Status** panel on the right then shows the progress:

| Step | What you see |
|---|---|
| Request sent to MTN | MTN accepted the request. The customer's registered MoMo name and number are shown, so you can confirm you have the right person. |
| Customer approval | The customer gets a prompt on their phone and enters their MoMo PIN. The page checks with MTN every 10 seconds. |
| Final status | **Payment successful** or **Payment failed** (declined, wrong PIN, not enough balance, or the prompt expired). |

If there is no answer after **5 minutes**, the page stops checking and shows **Still pending**. The payment is not lost: open it from **View transaction** later, or use [Check status with MTN](#6-checking-payments-with-mtn).

If you see **Request not sent**, MTN refused the request. The message says why; the most common causes are a wrong number or an MTN service problem. Check the number and try again.

---

## 5. Transactions

**Transactions** lists every payment request, newest first, 25 per page.

### Finding a payment

- **Search** matches the reference, payer name, payer number, username, device ID or MTN transaction ID. Part of a value is enough (for example `kofi` or `0241`).
- **Status**: Successful, Pending or Failed.
- **App**: one registered application.
- **From / To**: request dates (both days included).
- Select **Filter** to apply the search and dates. Status and App apply as soon as you change them. **Clear** removes all filters.

### The list

| Column | Meaning |
|---|---|
| Date | When the request was made. |
| Reference | Our reference for the payment (hover to see it in full). Quote this to MTN or the eBilling team. |
| Payer | The payer's registered MoMo name, with their number underneath. *Name unavailable* means MTN did not return a name. |
| App, Username, Device | Which system, account and meter the payment was for. |
| Amount | The amount requested. |
| Status | Successful, Pending or Failed. |
| Credited | A green tick when the meter has been credited. |

**Export CSV** downloads the list with your current filters applied. The footer shows the total amount of the matching requests.

### A single payment

Select a row to open it. The **Details** panel shows everything recorded, including the payer, the MTN transaction ID and the first response from MTN. The **Lifecycle** panel shows each stage: request created, sent to MTN, final status, meter credited and eBilling notified.

---

## 6. Checking payments with MTN

Payments normally update themselves when MTN reports the result. When a payment is stuck on **Pending**, you can ask MTN directly.

### One payment

Open the payment and select **Check status with MTN** (top right; only shown while the payment is unfinished). A message tells you the result:

- *MTN reports SUCCESSFUL / FAILED. The transaction has been updated.*
- *MTN reports PENDING. Nothing changed.*: the customer has not answered yet.
- *MTN has no record of this reference*: the request never reached MTN.

### Many payments at once

1. On **Transactions**, filter to the payments you want, for example **Status: Pending**, or a date range.
2. A yellow bar shows how many payments in the list are unfinished. Select **Check N with MTN** and confirm.
3. The payments are checked in small batches. A progress bar and counters show how many came back successful, failed, still pending, not found at MTN, or hit an error.
4. **Stop** halts after the current batch; everything already checked is kept.
5. When it finishes, select **Reload list**.

**Mark ones MTN has no record of as failed**: tick this only when cleaning up old requests. It marks requests that never reached MTN as **Failed** so they stop showing as pending. Leave it unticked for recent payments.

Checking also fills in the payer's number and MoMo name on older payments that don't have them yet.

---

## 7. Reports

**Reports** summarises payments for a period.

1. Pick the period type: **Monthly**, **Quarterly**, **Half-yearly**, **Yearly** or **Selected period**.
2. Pick the year and month, quarter (Q1 = Jan–Mar, Q2 = Apr–Jun, Q3 = Jul–Sep, Q4 = Oct–Dec) or half (H1 = Jan–Jun, H2 = Jul–Dec). For **Selected period**, pick the **From** and **To** dates.
3. Optionally pick one **Application**.
4. Select **Run report**.

The report shows:

- **Collected**, **Requests**, **Success rate** and **Average payment** (per successful payment).
- A **▲ / ▼ percentage** comparing Collected and Requests with the previous period of the same length (for example Q2 against Q1, or March against February). A dash means the previous period had nothing to compare.
- A **trend chart**: by day for periods up to about two months, by month for longer ones.
- **Breakdown** table with a total row. Select a day or month to see its transactions.
- **By application** table.

**Export CSV** downloads the breakdown. **Print** prints a clean copy with the sidebar and filters removed, stamped with the date and your username.

---

## 8. Callback Logs

Every message MTN sends to the gateway about a payment is recorded here, exactly as received. Use it when investigating a disputed or stuck payment.

- Search by text in the message body (for example a reference or a number) or by IP address.
- Select a row to see the full message, its headers and where it came from.

If a payment stays pending and there is no matching callback here, MTN has not reported the result. Use [Check status with MTN](#6-checking-payments-with-mtn).

---

## 9. Applications

Only **registered applications** can request payments through the gateway. Each has a name, a web address, an IP address and a key.

- **Register an application**: fill in the form on the right and select **Register**. Leave **Key** blank to generate one. Copy the key with the clipboard icon and give it to the system's developers.
- **Edit**: change the details and select **Save changes**.
- **Remove app**: on the edit page. The application can no longer request payments; its past transactions are kept.

The table also shows how many requests each application has made and how much it has collected.

---

## 10. What the statuses mean

| Status | Meaning | What to do |
|---|---|---|
| **Pending** | Sent to MTN and waiting for the customer, or the result hasn't reached us yet. | Wait a few minutes, then [check with MTN](#6-checking-payments-with-mtn). |
| **Successful** | The customer approved and the money was collected. | Nothing on the gateway. The meter is credited on the eBilling side. |
| **Failed** | Declined, wrong PIN, not enough balance, the prompt expired, or the request never reached MTN. | Ask the customer to try again with a new request. |
| **Credited** (tick) | The meter has been marked as credited for this payment. | If a successful payment isn't credited, contact the eBilling team with the reference. |

---

## 11. Troubleshooting

| Message or problem | Cause and fix |
|---|---|
| *Could not get an access token from MTN* | The gateway couldn't sign in to MTN. Usually the MTN credentials are wrong or MTN is down. Tell an administrator. |
| *Enter a valid MTN MoMo number* | The number isn't 10 digits starting with 0, or 12 digits starting with 233, or isn't an MTN number. |
| *No registered app found* | The application name isn't registered. Add it on **Applications**. |
| Payment stuck on **Pending** | The customer hasn't answered, or MTN's result didn't arrive. Use **Check status with MTN**. |
| Payer shows **Name unavailable** | MTN didn't return a name for that number. The payment is not affected. |
| Payer shows **—** | Older payment with no number recorded. Checking it with MTN fills it in. |
| Signed out unexpectedly | Your session expired. Sign in again. |

---

## 12. For administrators

### Giving someone access

Staff accounts are managed in **Django Admin** (sidebar link, superusers only):

1. **Users › Add user**: set a username and password, then save.
2. On the next screen fill in their name and email, tick **Staff status**, then save.

To remove access, untick **Active** (keeps their history) rather than deleting the user.

### Clearing pending payments automatically

The same check as the bulk button can be run on the server:

```
python manage.py recheck_pending --dry-run          # preview, saves nothing
python manage.py recheck_pending                    # record results
python manage.py recheck_pending --fail-not-found   # also fail requests MTN has no record of
```

It skips requests less than 10 minutes old (change with `--older-than MINUTES`). It is safe to schedule, for example every 15 minutes with Windows Task Scheduler or cron.

See [README.md](../README.md) for installation, configuration and the API used by eBilling.
