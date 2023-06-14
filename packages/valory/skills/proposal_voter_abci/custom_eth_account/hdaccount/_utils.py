#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------


import hashlib
import hmac
import unicodedata
from typing import Union

from eth_keys import keys
from eth_utils import ValidationError
from hexbytes import HexBytes


PBKDF2_ROUNDS = 2048
SECP256K1_N = int(
    "FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFE_BAAEDCE6_AF48A03B_BFD25E8C_D0364141", 16
)


def normalize_string(txt: Union[str, bytes]) -> str:
    if isinstance(txt, bytes):
        utxt = txt.decode("utf8")
    elif isinstance(txt, str):
        utxt = txt
    else:
        raise ValidationError("String value expected")

    return unicodedata.normalize("NFKD", utxt)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def hmac_sha512(chain_code: bytes, data: bytes) -> bytes:
    """
    As specified by RFC4231 - https://tools.ietf.org/html/rfc4231 .
    """
    return hmac.new(chain_code, data, hashlib.sha512).digest()


def pbkdf2_hmac_sha512(passcode: str, salt: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha512",
        passcode.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ROUNDS,
    )


def ec_point(pkey: bytes) -> bytes:
    """
    Compute `point(p)`, where `point` is ecdsa point multiplication.

    Note: Result is ecdsa public key serialized to compressed form
    """
    return keys.PrivateKey(HexBytes(pkey)).public_key.to_compressed_bytes()  # type: ignore  # noqa: E501
