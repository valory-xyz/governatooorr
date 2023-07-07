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


# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 valory
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

"""This module contains the scaffold contract definition."""

from enum import IntEnum
from typing import Any

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


Pubkey = Any  # defined in solders.pubkey
Keypair = Any  # defined in solders.keypair
Program = Any  # defined in anchorpy
Instruction = Any  # defined in solders.instruction


GOVERNANCE_PROGRAM_SEED = "governance"
SPL_GOVERNANCE_PROGRAM = "GovER5Lthms3bLBqWub97yVrMmEogzX7xNjdXpPPCVZw"


class GovernanceInstruction(IntEnum):
    """Solana governance instructions."""

    CreateRealm = 0
    DepositGoverningTokens = 1
    WithdrawGoverningTokens = 2
    SetGovernanceDelegate = 3
    CreateGovernance = 4
    CreateProgramGovernance = 5
    CreateProposal = 6
    AddSignatory = 7
    RemoveSignatory = 8
    InsertTransaction = 9
    RemoveTransaction = 10
    CancelProposal = 11
    SignOffProposal = 12
    CastVote = 13
    FinalizeVote = 14
    RelinquishVote = 15
    ExecuteTransaction = 16
    CreateMintGovernance = 17
    CreateTokenGovernance = 18
    SetGovernanceConfig = 19
    FlagTransactionError = 20
    SetRealmAuthority = 21
    SetRealmConfig = 22
    CreateTokenOwnerRecord = 23
    UpdateProgramMetadata = 24
    CreateNativeTreasury = 25
    RevokeGoverningTokens = 26
    RefundProposalDeposit = 27


class SolanaGovernanceContract(Contract):
    """The scaffold contract class for a smart contract."""

    contract_id = PublicId.from_str("valory/solana_governance:0.1.0")

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
    def get_program_instance(cls, ledger_api: LedgerApi) -> Program:
        """Get program instance."""
        program: Program = ledger_api.get_contract_instance(
            contract_interface=cls.contract_interface[ledger_api.identifier],
            contract_address=SPL_GOVERNANCE_PROGRAM,
        ).get("program")
        return program

    @classmethod
    def get_realm_address(
        cls,
        ledger_api: LedgerApi,
        contract_address: Pubkey,
        name: str,
    ) -> Pubkey:
        return ledger_api.pda(
            [
                GOVERNANCE_PROGRAM_SEED.encode(),
                name.encode(),
            ],
            program_id=ledger_api.to_pubkey(SPL_GOVERNANCE_PROGRAM),
        )

    @classmethod
    def cast_vote_ix(
        cls,
        ledger_api: LedgerApi,
        contract_address: Pubkey,
        voter: Pubkey,
        realm: Pubkey,
        proposal: Pubkey,
        governing_token_mint: Pubkey,
        governance: Pubkey,
        proposal_owner: Pubkey,
        vote_choice: str,
        rank: int = 0,
        weight_percentage: int = 100,
    ) -> JSONLike:
        """Build cast vote IX"""

        program = cls.get_program_instance(ledger_api=ledger_api)

        # Convert contract strings to solders.pubkey.Pubkey objects
        contract_address = ledger_api.to_pubkey(contract_address)
        voter = ledger_api.to_pubkey(voter)
        realm = ledger_api.to_pubkey(realm)
        proposal = ledger_api.to_pubkey(proposal)
        governing_token_mint = ledger_api.to_pubkey(governing_token_mint)
        governance = ledger_api.to_pubkey(governance)
        proposal_owner = ledger_api.to_pubkey(proposal_owner)

        # Build argument
        vote_choice = vote_choice.lower().title()
        if vote_choice == "Approve":
            vote = program.type["Vote"].Approve(
                (
                    (
                        program.type["VoteChoice"](
                            rank=rank,
                            weight_percentage=weight_percentage,
                        ),
                    ),
                )
            )
        elif vote_choice == "Deny":
            vote = program.type["Vote"].Deny()
        elif vote_choice == "Abstain":
            vote = program.type["Vote"].Abstain()
        else:
            vote = program.type["Vote"].Veto()

        # Build PDAs
        proposal_owner_record = ledger_api.pda(
            seeds=[
                bytes(GOVERNANCE_PROGRAM_SEED, encoding="utf-8"),
                bytes(realm),
                bytes(governing_token_mint),
                bytes(proposal_owner),
            ],
            program_id=ledger_api.to_pubkey(SPL_GOVERNANCE_PROGRAM),
        )
        token_owner_record = ledger_api.pda(
            seeds=[
                bytes(GOVERNANCE_PROGRAM_SEED, encoding="utf-8"),
                bytes(realm),
                bytes(governing_token_mint),
                bytes(voter),
            ],
            program_id=ledger_api.to_pubkey(SPL_GOVERNANCE_PROGRAM),
        )
        vote_record_address = ledger_api.pda(
            seeds=[
                bytes(GOVERNANCE_PROGRAM_SEED, encoding="utf-8"),
                bytes(proposal),
                bytes(token_owner_record),
            ],
            program_id=ledger_api.to_pubkey(SPL_GOVERNANCE_PROGRAM),
        )
        ix = ledger_api.build_instruction(
            contract_instance=program,
            method_name="cast_vote",
            data=[vote],
            accounts={
                {
                    "realm": realm,
                    "governance": governance,
                    "proposal": proposal,
                    "proposal_owner_record": proposal_owner_record,
                    "voter_token_owner_record": token_owner_record,
                    "governance_authority": voter,
                    "vote_record_address": vote_record_address,
                    "vote_governing_token_mint": governing_token_mint,
                    "payer": voter,
                    "system_program": ledger_api.system_program,
                }
            },
            remaining_accounts=[
                ledger_api.to_account_meta(
                    "6mowUpueQ1yicCUXdhU8FN8ptjLgxd6na2FsNHtku27W",
                    is_signer=False,
                    is_writable=False,
                ),
            ],
        )

        return {
            "recent_blockhash": ledger_api.latest_hash,
            "ixs": [ix],
        }
