#!/usr/bin/env python3
import hashlib
import json
import re

FINGERPRINT_V2_SCHEMA = 2
FINGERPRINT_V2_KEYS = (
    "fingerprintSchema",
    "v2flyRelevantHash",
    "ruBlockedSha256",
    "geoipSha256",
    "routingPolicySha256",
    "buildContractSha256",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _hash(value, label):
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def canonical_components(
    *,
    v2fly_relevant_hash,
    ru_blocked_sha256,
    geoip_sha256,
    routing_policy_sha256,
    build_contract_sha256,
):
    return {
        "fingerprintSchema": FINGERPRINT_V2_SCHEMA,
        "v2flyRelevantHash": _hash(v2fly_relevant_hash, "v2fly relevant hash"),
        "ruBlockedSha256": _hash(ru_blocked_sha256, "ru-blocked SHA256"),
        "geoipSha256": _hash(geoip_sha256, "GeoIP SHA256"),
        "routingPolicySha256": _hash(routing_policy_sha256, "routing-policy SHA256"),
        "buildContractSha256": _hash(build_contract_sha256, "build-contract SHA256"),
    }


def fingerprint_from_components(components):
    if not isinstance(components, dict) or set(components) != set(FINGERPRINT_V2_KEYS):
        raise ValueError("fingerprint v2 components key set mismatch")
    if components.get("fingerprintSchema") != FINGERPRINT_V2_SCHEMA:
        raise ValueError("fingerprint v2 schema mismatch")
    normalized = canonical_components(
        v2fly_relevant_hash=components.get("v2flyRelevantHash"),
        ru_blocked_sha256=components.get("ruBlockedSha256"),
        geoip_sha256=components.get("geoipSha256"),
        routing_policy_sha256=components.get("routingPolicySha256"),
        build_contract_sha256=components.get("buildContractSha256"),
    )
    canonical = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_fingerprint_v2(**kwargs):
    components = canonical_components(**kwargs)
    return fingerprint_from_components(components), components
