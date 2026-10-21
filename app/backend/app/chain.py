import json
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
from web3 import Web3

from app.config import PROJECT_ROOT, settings
from app.models import TradeRecord

ABI_PATH = PROJECT_ROOT / "app" / "contracts" / "abi" / "TradeRegistry.json"
STATUS_CODES = {"comparable": 0, "baseline_unavailable": 1, "basis_mismatch": 2}
ZERO_BYTES32 = "0x" + "00" * 32


def _abi() -> list[dict[str, Any]]:
    try:
        return json.loads(ABI_PATH.read_text(encoding="utf-8"))["abi"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Contract ABI is missing at {ABI_PATH}; run npm run compile:contract.") from exc


def web3_client() -> Web3:
    client = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 4}))
    if not client.is_connected():
        raise RuntimeError(f"Cannot connect to the local EVM at {settings.rpc_url}. Start it with `npm run chain`.")
    if client.eth.chain_id != settings.chain_id:
        raise RuntimeError(f"Connected chain ID {client.eth.chain_id} does not match configured CHAIN_ID={settings.chain_id}.")
    return client


def require_contract() -> str:
    if not settings.contract_address:
        raise RuntimeError("CONTRACT_ADDRESS is not set. Start the local chain and run `npm run deploy:local`.")
    if not Web3.is_address(settings.contract_address):
        raise RuntimeError("CONTRACT_ADDRESS is invalid; deploy EnergyTradeRegistry and copy its address.")
    return Web3.to_checksum_address(settings.contract_address)


def make_contract_payload(trade: TradeRecord) -> dict[str, Any]:
    return {
        "tradeId": "0x" + keccak(text=trade.id).hex(),
        "buyer": Web3.to_checksum_address(trade.buyer_address),
        "seller": Web3.to_checksum_address(trade.seller_address),
        "energyWh": trade.energy_wh,
        "priceCentsPerKwh": trade.price_cents_per_kwh,
        "totalCostCents": trade.total_cost_cents,
        "validUntil": trade.valid_until,
        "carbonDiffDeciGrams": trade.carbon_diff_dg if trade.carbon_diff_dg is not None else 0,
        "carbonComparisonStatus": STATUS_CODES[trade.carbon_comparison_status],
        "baselineFactorHash": trade.baseline_factor_hash,
        "scenarioFactorHash": trade.scenario_factor_hash,
        "scoreConfigHash": trade.score_config_hash,
    }


def _typed_data(payload: dict[str, Any], chain_id: int, contract_address: str) -> dict[str, Any]:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"},
            ],
            "TradeAuthorization": [
                {"name": "tradeId", "type": "bytes32"}, {"name": "buyer", "type": "address"},
                {"name": "seller", "type": "address"}, {"name": "energyWh", "type": "uint256"},
                {"name": "priceCentsPerKwh", "type": "uint256"}, {"name": "totalCostCents", "type": "uint256"},
                {"name": "validUntil", "type": "uint64"}, {"name": "carbonDiffDeciGrams", "type": "int256"},
                {"name": "carbonComparisonStatus", "type": "uint8"}, {"name": "baselineFactorHash", "type": "bytes32"},
                {"name": "scenarioFactorHash", "type": "bytes32"}, {"name": "scoreConfigHash", "type": "bytes32"},
            ],
        },
        "primaryType": "TradeAuthorization",
        "domain": {"name": "EnergyTradeRegistry", "version": "1", "chainId": chain_id, "verifyingContract": contract_address},
        "message": payload,
    }


def sign_trade_payload(trade: TradeRecord) -> tuple[dict[str, Any], str]:
    if not settings.trade_auth_signer_private_key:
        raise RuntimeError("TRADE_AUTH_SIGNER_PRIVATE_KEY is missing. Run `npm run setup:local` and restart the API.")
    contract_address = require_contract()
    payload = make_contract_payload(trade)
    message = encode_typed_data(full_message=_typed_data(payload, settings.chain_id, contract_address))
    signed = Account.sign_message(message, private_key=settings.trade_auth_signer_private_key)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    return payload, signature


def _normal(value):
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if hasattr(value, "hex") and not isinstance(value, str):
        out = value.hex()
        return out if out.startswith("0x") else "0x" + out
    if isinstance(value, dict):
        return {k: _normal(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normal(v) for v in value]
    return value


def verify_submitted_transaction(transaction_hash: str, trade: TradeRecord):
    client = web3_client()
    address = require_contract()
    contract = client.eth.contract(address=address, abi=_abi())
    try:
        tx = client.eth.get_transaction(transaction_hash)
    except Exception as exc:
        raise ValueError("The transaction hash is not available on the configured chain yet.") from exc
    if not tx.get("to") or Web3.to_checksum_address(tx["to"]) != address:
        raise ValueError("Transaction target does not match the configured EnergyTradeRegistry contract.")
    try:
        function, arguments = contract.decode_function_input(tx["input"])
    except Exception as exc:
        raise ValueError("Transaction calldata is not a recognized EnergyTradeRegistry call.") from exc
    if function.fn_name != "recordTrade":
        raise ValueError("Transaction must call recordTrade.")
    actual = _normal(arguments.get("trade", arguments.get("tradeData")))
    expected = _normal(make_contract_payload(trade))
    if isinstance(actual, list):
        actual = dict(zip(expected.keys(), actual, strict=True))
    if not isinstance(actual, dict):
        raise ValueError("Could not decode the submitted trade fields.")
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            raise ValueError(f"Submitted transaction field {key} does not match the backend-authorized trade.")
    signature = arguments.get("authorizationSignature") or arguments.get("signature")
    normalized_signature = _normal(signature)
    expected_signature = trade.authorization_signature or ""
    if isinstance(normalized_signature, str) and not normalized_signature.startswith("0x"):
        normalized_signature = "0x" + normalized_signature
    if normalized_signature != expected_signature:
        raise ValueError("Submitted transaction does not contain the backend authorization signature.")
    return client, tx


def trade_event_exists(trade: TradeRecord) -> bool:
    client = web3_client()
    contract = client.eth.contract(address=require_contract(), abi=_abi())
    trade_hash = make_contract_payload(trade)["tradeId"]
    return bool(contract.functions.tradeExists(trade_hash).call())


def matching_event_for_trade(trade: TradeRecord):
    client = web3_client()
    contract = client.eth.contract(address=require_contract(), abi=_abi())
    trade_hash = make_contract_payload(trade)["tradeId"]
    logs = contract.events.TradeRecorded().get_logs(from_block=0, to_block="latest", argument_filters={"tradeId": trade_hash})
    return (client, contract, logs[0]) if logs else (client, contract, None)


def receipt_for_hash(transaction_hash: str):
    client = web3_client()
    try:
        receipt = client.eth.get_transaction_receipt(transaction_hash)
    except Exception:
        return client, None
    return client, receipt


def verify_event_payload(log: dict[str, Any], trade: TradeRecord) -> bool:
    event = _normal(log["args"])
    expected = _normal(make_contract_payload(trade))
    keys = {
        "tradeId": "tradeId", "buyer": "buyer", "seller": "seller", "energyWh": "energyWh",
        "priceCentsPerKwh": "priceCentsPerKwh", "totalCostCents": "totalCostCents",
        "validUntil": "validUntil", "carbonDiffDeciGrams": "carbonDiffDeciGrams",
        "carbonComparisonStatus": "carbonComparisonStatus", "baselineFactorHash": "baselineFactorHash",
        "scenarioFactorHash": "scenarioFactorHash", "scoreConfigHash": "scoreConfigHash",
    }
    return all(event.get(key) == expected[value] for key, value in keys.items())


def finalized_nonce_replacement(trade: TradeRecord, confirmation_blocks: int) -> bool:
    if not trade.transaction_from or trade.transaction_nonce is None or not trade.transaction_hash:
        return False
    client = web3_client()
    latest = client.eth.get_block("latest", full_transactions=True)
    if client.eth.get_transaction_count(trade.transaction_from, "latest") <= trade.transaction_nonce:
        return False
    lower = max(0, latest["number"] - 256)
    for number in range(latest["number"], lower - 1, -1):
        block = client.eth.get_block(number, full_transactions=True)
        for tx in block["transactions"]:
            if (
                Web3.to_checksum_address(tx["from"]) == Web3.to_checksum_address(trade.transaction_from)
                and tx["nonce"] == trade.transaction_nonce
            ):
                replacement_hash = Web3.to_hex(tx["hash"])
                return (
                    replacement_hash.lower() != trade.transaction_hash.lower()
                    and latest["number"] - number + 1 >= confirmation_blocks
                )
    return False
