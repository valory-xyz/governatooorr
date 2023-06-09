# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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

"""This module contains the dynamic_contribution contract definition."""

from typing import Any

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi


class SignMessageLibContract(Contract):
    """The scaffold contract class for a smart contract."""

    contract_id = PublicId.from_str("valory/sign_message_lib:0.1.0")

    @classmethod
    def get_raw_transaction(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """
        Handler method for the 'GET_RAW_TRANSACTION' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_raw_message(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> bytes:
        """
        Handler method for the 'GET_RAW_MESSAGE' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_state(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """
        Handler method for the 'GET_STATE' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def sign_message(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        data: bytes,
    ) -> JSONLike:
        """
        Signs a message

        https://github.com/safe-global/safe-contracts/blob/v1.3.0/contracts/examples/libraries/SignMessage.sol
        https://etherscan.io/address/0xA65387F16B013cf2Af4605Ad8aA5ec25a2cbA3a2#code

        :param ledger_api: LedgerApi object
        :param contract_address: the address of the token to be used
        :param proposal_id: the proposal id.
        :param support: the vote
        :return: the number of votes cast
        """
        if not isinstance(ledger_api, EthereumApi):
            raise ValueError(f"Only EthereumApi is supported, got {type(ledger_api)}")
        contract_instance = cls.get_instance(ledger_api, contract_address)
        signature = contract_instance.encodeABI(
            fn_name="signMessage", args=[data,]
        )
        return {"signature": signature}  # type: ignore


    @classmethod
    def get_safe_signature(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        tx_hash: str,
    ) -> JSONLike:
        """
        Gets the signature from a previous tx

        :param ledger_api: LedgerApi object
        :param contract_address: the address of the safe
        :param tx_hash: the sign transaction hash
        :return: the EITP-712 signature
        """
        if not isinstance(ledger_api, EthereumApi):
            raise ValueError(f"Only EthereumApi is supported, got {type(ledger_api)}")
        contract_instance = cls.get_instance(ledger_api, contract_address)

        events = contract_instance.events.SignMsg.createFilter(
            fromBlock="earliest",
            toBlock="latest",
        ).get_all_entries()

        signature = None
        for event in events:
            if tx_hash == event.transactionHash.hex():
                signature = event.args.msgHash.hex()
                break

        return {"signature": signature}