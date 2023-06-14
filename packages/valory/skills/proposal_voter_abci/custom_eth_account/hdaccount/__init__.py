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


from eth_utils import ValidationError

from .deterministic import HDPath
from .mnemonic import Mnemonic


ETHEREUM_DEFAULT_PATH = "m/44'/60'/0'/0/0"


def generate_mnemonic(num_words: int, lang: str) -> str:
    return Mnemonic(lang).generate(num_words)


def seed_from_mnemonic(words: str, passphrase: str) -> bytes:
    lang = Mnemonic.detect_language(words)
    expanded_words = Mnemonic(lang).expand(words)
    if not Mnemonic(lang).is_mnemonic_valid(expanded_words):
        raise ValidationError(
            f"Provided words: '{expanded_words}', are not a "
            "valid BIP39 mnemonic phrase!"
        )
    return Mnemonic.to_seed(expanded_words, passphrase)


def key_from_seed(seed: bytes, account_path: str) -> bytes:
    return HDPath(account_path).derive(seed)
