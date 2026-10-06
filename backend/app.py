import os
import base64
import requests
import jwt
from datetime import datetime, timezone
from flask import Flask, jsonify

app = Flask(__name__)

ENABLE_BANKING_API = "https://api.enablebanking.com"


def create_enable_banking_token():
    app_id = os.environ["ENABLE_BANKING_APP_ID"]
    private_key_b64 = os.environ["ENABLE_BANKING_PRIVATE_KEY_B64"]

    private_key = base64.b64decode(private_key_b64)

    now = int(datetime.now(timezone.utc).timestamp())

    return jwt.encode(
        {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": now,
            "exp": now + 3600,
        },
        private_key,
        algorithm="RS256",
        headers={
            "typ": "JWT",
            "kid": app_id,
        },
    )


@app.get("/")
def home():
    return jsonify({
        "service": "Budget Billy",
        "status": "online"
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok"
    })


@app.get("/enable-banking/status")
def enable_banking_status():
    try:
        app_id = os.environ.get("ENABLE_BANKING_APP_ID")
        key_b64 = os.environ.get("ENABLE_BANKING_PRIVATE_KEY_B64")

        if not app_id:
            return jsonify({"connected": False, "step": "app_id_missing"}), 500

        if not key_b64:
            return jsonify({"connected": False, "step": "private_key_missing"}), 500

        try:
            private_key = base64.b64decode(key_b64, validate=True)
        except Exception as exc:
            return jsonify({
                "connected": False,
                "step": "base64_decode",
                "error": type(exc).__name__
            }), 500

        try:
            now = int(datetime.now(timezone.utc).timestamp())

            token = jwt.encode(
                {
                    "iss": "enablebanking.com",
                    "aud": "api.enablebanking.com",
                    "iat": now,
                    "exp": now + 3600,
                },
                private_key,
                algorithm="RS256",
                headers={
                    "typ": "JWT",
                    "kid": app_id,
                },
            )
        except Exception as exc:
            return jsonify({
                "connected": False,
                "step": "jwt_encode",
                "error": type(exc).__name__
            }), 500

        try:
            response = requests.get(
                "https://api.enablebanking.com/application",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=30,
            )
        except Exception as exc:
            return jsonify({
                "connected": False,
                "step": "enable_banking_request",
                "error": type(exc).__name__
            }), 500

        if response.status_code != 200:
            return jsonify({
                "connected": False,
                "step": "enable_banking_response",
                "http_status": response.status_code
            }), 502

        data = response.json()

        return jsonify({
            "connected": True,
            "application": data.get("name"),
            "environment": data.get("environment"),
            "services": data.get("services")
        })

    except Exception as exc:
        return jsonify({
            "connected": False,
            "step": "unexpected",
            "error": type(exc).__name__
        }), 500

@app.get("/revolut/accounts")
def revolut_accounts():
    try:
        token = create_enable_banking_token()

        account_uids = [
            os.environ["REVOLUT_ACCOUNT_1_UID"],
            os.environ["REVOLUT_ACCOUNT_2_UID"],
        ]

        results = []

        for uid in account_uids:
            response = requests.get(
                f"{ENABLE_BANKING_API}/accounts/{uid}/details",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=30,
            )

            if response.status_code != 200:
                results.append({
                    "ok": False,
                    "http_status": response.status_code
                })
                continue

            data = response.json()

            results.append({
                "ok": True,
                "name": data.get("name"),
                "currency": data.get("currency"),
                "cash_account_type": data.get("cash_account_type"),
            })

        return jsonify({
            "connected": True,
            "accounts": results
        })

    except Exception as exc:
        return jsonify({
            "connected": False,
            "error": type(exc).__name__
        }), 500

@app.get("/revolut/data")
def revolut_data():
    try:
        token = create_enable_banking_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        account_uids = [
            os.environ["REVOLUT_ACCOUNT_1_UID"],
            os.environ["REVOLUT_ACCOUNT_2_UID"],
        ]

        accounts = []

        for uid in account_uids:
            # Informations du compte
            details_response = requests.get(
                f"{ENABLE_BANKING_API}/accounts/{uid}/details",
                headers=headers,
                timeout=30,
            )

            # Soldes
            balances_response = requests.get(
                f"{ENABLE_BANKING_API}/accounts/{uid}/balances",
                headers=headers,
                timeout=30,
            )

            # Transactions
            transactions_response = requests.get(
                f"{ENABLE_BANKING_API}/accounts/{uid}/transactions",
                headers=headers,
                timeout=30,
            )

            if details_response.status_code == 200:
                details = details_response.json()
            else:
                details = {}

            if balances_response.status_code == 200:
                balances = balances_response.json().get("balances", [])
            else:
                balances = []

            if transactions_response.status_code == 200:
                transaction_data = transactions_response.json()
                transactions = transaction_data.get("transactions", [])
                continuation_key = transaction_data.get("continuation_key")
            else:
                transactions = []
                continuation_key = None

            accounts.append({
                "name": details.get("name"),
                "type": details.get("cash_account_type"),
                "currency": details.get("currency"),
                "balances": balances,
                "transactions": transactions,
                "transaction_count": len(transactions),
                "continuation_key": continuation_key,
                "http": {
                    "details": details_response.status_code,
                    "balances": balances_response.status_code,
                    "transactions": transactions_response.status_code,
                },
            })

        return jsonify({
            "connected": True,
            "account_count": len(accounts),
            "accounts": accounts,
        })

    except Exception as exc:
        return jsonify({
            "connected": False,
            "error": type(exc).__name__,
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def clean_amount(transaction):
    amount_data = transaction.get("transaction_amount") or {}
    try:
        amount = float(amount_data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0

    # Enable Banking donne souvent un montant positif
    # + l'indicateur DBIT/CRDT séparément.
    indicator = transaction.get("credit_debit_indicator")

    if indicator == "DBIT":
        amount = -abs(amount)
    elif indicator == "CRDT":
        amount = abs(amount)

    return round(amount, 2)


def transaction_name(transaction):
    # Paiement : on privilégie le créancier/commerçant
    creditor = transaction.get("creditor") or {}
    debtor = transaction.get("debtor") or {}

    name = creditor.get("name") or debtor.get("name")

    if name:
        return name

    remittance = transaction.get("remittance_information")

    if isinstance(remittance, list) and remittance:
        return str(remittance[0])

    if isinstance(remittance, str) and remittance:
        return remittance

    return "Transaction"


@app.route("/revolut/summary")
def revolut_summary():
    try:
        # On réutilise exactement les comptes déjà configurés
        # dans production_session.json.
        with open("production_session.json", "r", encoding="utf-8") as f:
            session = json.load(f)

        accounts = session.get("accounts", [])

        result = {
            "connected": True,
            "currency": "EUR",
            "total_balance": 0.0,
            "accounts": [],
            "recent_transactions": []
        }

        for account in accounts:
            uid = account["uid"]

            balance_response = requests.get(
                f"https://api.enablebanking.com/accounts/{uid}/balances",
                headers=enable_banking_headers(),
                timeout=30
            )

            transaction_response = requests.get(
                f"https://api.enablebanking.com/accounts/{uid}/transactions",
                headers=enable_banking_headers(),
                timeout=30
            )

            balance = 0.0

            if balance_response.ok:
                balances = balance_response.json().get("balances", [])

                if balances:
                    balance_data = balances[0].get("balance_amount") or {}

                    try:
                        balance = float(balance_data.get("amount", 0))
                    except (TypeError, ValueError):
                        balance = 0.0

            account_type = account.get("cash_account_type")

            result["accounts"].append({
                "name": account.get("name"),
                "type": account_type,
                "balance": round(balance, 2),
                "currency": account.get("currency", "EUR")
            })

            result["total_balance"] += balance

            if transaction_response.ok:
                transactions = transaction_response.json().get(
                    "transactions", []
                )

                for transaction in transactions:
                    result["recent_transactions"].append({
                        "date": (
                            transaction.get("booking_date")
                            or transaction.get("value_date")
                            or transaction.get("transaction_date")
                        ),
                        "merchant": transaction_name(transaction),
                        "amount": clean_amount(transaction),
                        "currency": (
                            transaction.get("transaction_amount") or {}
                        ).get("currency", "EUR"),
                        "status": transaction.get("status"),
                        "reference": transaction.get("entry_reference")
                    })

        result["total_balance"] = round(result["total_balance"], 2)

        # Plus récentes en premier
        result["recent_transactions"].sort(
            key=lambda x: x.get("date") or "",
            reverse=True
        )

        # Pour l'instant on garde seulement les 20 dernières
        result["recent_transactions"] = result[
            "recent_transactions"
        ][:20]

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "connected": False,
            "error": type(e).__name__
        }), 500
