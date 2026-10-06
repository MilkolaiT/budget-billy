import os
import base64
import requests
import jwt

from datetime import datetime, timezone
from flask import Flask, jsonify


app = Flask(__name__)

ENABLE_BANKING_API = "https://api.enablebanking.com"


# ============================================================
# ENABLE BANKING
# ============================================================

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


def create_enable_banking_headers():
    token = create_enable_banking_token()

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def get_revolut_account_uids():
    return [
        os.environ["REVOLUT_ACCOUNT_1_UID"],
        os.environ["REVOLUT_ACCOUNT_2_UID"],
    ]


# ============================================================
# UTILITAIRES TRANSACTIONS
# ============================================================

def clean_amount(transaction):
    amount_data = transaction.get("transaction_amount") or {}

    try:
        amount = float(amount_data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0

    indicator = transaction.get("credit_debit_indicator")

    if indicator == "DBIT":
        amount = -abs(amount)

    elif indicator == "CRDT":
        amount = abs(amount)

    return round(amount, 2)


def transaction_name(transaction):
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


def extract_balance(balances):
    if not balances:
        return 0.0

    # On privilégie le solde disponible si Enable Banking
    # renvoie plusieurs types de soldes.
    preferred_types = [
        "CLAV",
        "ITAV",
        "CLBD",
        "ITBD",
    ]

    selected_balance = None

    for preferred_type in preferred_types:
        for balance in balances:
            if balance.get("balance_type") == preferred_type:
                selected_balance = balance
                break

        if selected_balance:
            break

    if selected_balance is None:
        selected_balance = balances[0]

    balance_data = selected_balance.get("balance_amount") or {}

    try:
        return float(balance_data.get("amount", 0))
    except (TypeError, ValueError):
        return 0.0


# ============================================================
# ACCUEIL
# ============================================================

@app.get("/")
def home():
    return jsonify({
        "service": "Budget Billy",
        "status": "online",
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
    })


# ============================================================
# TEST ENABLE BANKING
# ============================================================

@app.get("/enable-banking/status")
def enable_banking_status():
    try:
        app_id = os.environ.get("ENABLE_BANKING_APP_ID")
        key_b64 = os.environ.get("ENABLE_BANKING_PRIVATE_KEY_B64")

        if not app_id:
            return jsonify({
                "connected": False,
                "step": "app_id_missing",
            }), 500

        if not key_b64:
            return jsonify({
                "connected": False,
                "step": "private_key_missing",
            }), 500

        try:
            private_key = base64.b64decode(
                key_b64,
                validate=True,
            )

        except Exception as exc:
            return jsonify({
                "connected": False,
                "step": "base64_decode",
                "error": type(exc).__name__,
            }), 500

        try:
            now = int(
                datetime.now(timezone.utc).timestamp()
            )

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
                "error": type(exc).__name__,
            }), 500

        try:
            response = requests.get(
                f"{ENABLE_BANKING_API}/application",
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
                "error": type(exc).__name__,
            }), 500

        if response.status_code != 200:
            return jsonify({
                "connected": False,
                "step": "enable_banking_response",
                "http_status": response.status_code,
            }), 502

        data = response.json()

        return jsonify({
            "connected": True,
            "application": data.get("name"),
            "environment": data.get("environment"),
            "services": data.get("services"),
        })

    except Exception as exc:
        return jsonify({
            "connected": False,
            "step": "unexpected",
            "error": type(exc).__name__,
        }), 500


# ============================================================
# COMPTES REVOLUT
# ============================================================

@app.get("/revolut/accounts")
def revolut_accounts():
    try:
        headers = create_enable_banking_headers()

        account_uids = get_revolut_account_uids()

        results = []

        for uid in account_uids:
            response = requests.get(
                f"{ENABLE_BANKING_API}/accounts/{uid}/details",
                headers=headers,
                timeout=30,
            )

            if response.status_code != 200:
                results.append({
                    "ok": False,
                    "http_status": response.status_code,
                })

                continue

            data = response.json()

            results.append({
                "ok": True,
                "name": data.get("name"),
                "currency": data.get("currency"),
                "cash_account_type": data.get(
                    "cash_account_type"
                ),
            })

        return jsonify({
            "connected": True,
            "accounts": results,
        })

    except Exception as exc:
        return jsonify({
            "connected": False,
            "error": type(exc).__name__,
        }), 500


# ============================================================
# DONNÉES REVOLUT BRUTES
# ============================================================

@app.get("/revolut/data")
def revolut_data():
    try:
        headers = create_enable_banking_headers()

        account_uids = get_revolut_account_uids()

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
                balances = balances_response.json().get(
                    "balances",
                    [],
                )
            else:
                balances = []

            if transactions_response.status_code == 200:
                transaction_data = (
                    transactions_response.json()
                )

                transactions = transaction_data.get(
                    "transactions",
                    [],
                )

                continuation_key = transaction_data.get(
                    "continuation_key"
                )

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
                    "transactions": (
                        transactions_response.status_code
                    ),
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


# ============================================================
# RÉSUMÉ REVOLUT POUR BUDGET BILLY
# ============================================================

@app.get("/revolut/summary")
def revolut_summary():
    try:
        headers = create_enable_banking_headers()

        account_uids = get_revolut_account_uids()

        result = {
            "connected": True,
            "currency": "EUR",
            "total_balance": 0.0,
            "accounts": [],
            "recent_transactions": [],
        }

        for uid in account_uids:

            # ------------------------------------------------
            # DETAILS
            # ------------------------------------------------

            details_response = requests.get(
                f"{ENABLE_BANKING_API}/accounts/{uid}/details",
                headers=headers,
                timeout=30,
            )

            if details_response.status_code == 200:
                details = details_response.json()
            else:
                details = {}

            # ------------------------------------------------
            # BALANCES
            # ------------------------------------------------

            balances_response = requests.get(
                f"{ENABLE_BANKING_API}/accounts/{uid}/balances",
                headers=headers,
                timeout=30,
            )

            if balances_response.status_code == 200:
                balances = balances_response.json().get(
                    "balances",
                    [],
                )
            else:
                balances = []

            balance = extract_balance(balances)

            result["accounts"].append({
                "name": details.get("name"),
                "type": details.get("cash_account_type"),
                "balance": round(balance, 2),
                "currency": details.get(
                    "currency",
                    "EUR",
                ),
            })

            result["total_balance"] += balance

            # ------------------------------------------------
            # TRANSACTIONS
            # ------------------------------------------------

            transactions_response = requests.get(
                f"{ENABLE_BANKING_API}/accounts/{uid}/transactions",
                headers=headers,
                timeout=30,
            )

            if transactions_response.status_code == 200:
                transaction_data = (
                    transactions_response.json()
                )

                transactions = transaction_data.get(
                    "transactions",
                    [],
                )

                for transaction in transactions:

                    date = (
                        transaction.get("booking_date")
                        or transaction.get("value_date")
                        or transaction.get(
                            "transaction_date"
                        )
                    )

                    amount_data = (
                        transaction.get(
                            "transaction_amount"
                        )
                        or {}
                    )

                    result[
                        "recent_transactions"
                    ].append({
                        "date": date,
                        "merchant": transaction_name(
                            transaction
                        ),
                        "amount": clean_amount(
                            transaction
                        ),
                        "currency": amount_data.get(
                            "currency",
                            "EUR",
                        ),
                        "status": transaction.get(
                            "status"
                        ),
                        "reference": transaction.get(
                            "entry_reference"
                        ),
                    })

        # ----------------------------------------------------
        # TOTAL
        # ----------------------------------------------------

        result["total_balance"] = round(
            result["total_balance"],
            2,
        )

        # ----------------------------------------------------
        # TRI DES TRANSACTIONS
        # ----------------------------------------------------

        result["recent_transactions"].sort(
            key=lambda transaction: (
                transaction.get("date") or ""
            ),
            reverse=True,
        )

        # Pour l'instant : 20 dernières opérations.
        result["recent_transactions"] = (
            result["recent_transactions"][:20]
        )

        return jsonify(result)

    except Exception as exc:
        return jsonify({
            "connected": False,
            "error": type(exc).__name__,
        }), 500


# ============================================================
# LANCEMENT LOCAL
# ============================================================

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            8080,
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )
