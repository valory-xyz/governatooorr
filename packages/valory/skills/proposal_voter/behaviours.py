# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This package contains round behaviours of ProposalVoterAbciApp."""

from abc import ABC
from typing import Generator, Set, Type, cast, Optional
from packages.valory.contracts.delegate.contract import DelegateContract
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.proposal_voter.models import Params
from packages.valory.skills.proposal_voter.rounds import (
    SynchronizedData,
    ProposalVoterAbciApp,
    EstablishVoteRound,
    PrepareVoteTransactionRound,
)
from packages.valory.skills.proposal_voter.rounds import (
    EstablishVotePayload,
    PrepareVoteTransactionPayload,
)
from packages.valory.skills.proposal_voter.payload_tools import (
    hash_payload_to_hex,
)

SAFE_TX_GAS = 0
ETHER_VALUE = 0

VOTES_TO_CODE = {"FOR": 0, "AGAINST": 1, "ABSTAIN": 2}


class ProposalVoterBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour for the proposal_voter skill."""

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def params(self) -> Params:
        """Return the params."""
        return cast(Params, super().params)


class EstablishVoteBehaviour(ProposalVoterBaseBehaviour):
    """EstablishVoteBehaviour"""

    matching_round: Type[AbstractRound] = EstablishVoteRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            # Get the selected proposal
            selected_proposal = None
            p_id = self.synchronized_data.selected_proposal_id

            for p in self.synchronized_data.active_proposals:
                if p["id"] == p_id:
                    selected_proposal = p
                    break

            # This should never fail
            assert (
                selected_proposal
            ), f"Proposal with id {p_id} has not been found in the active proposals"

            # Get the service aggregated vote intention
            # TODO: is the governor address the same as the token address?
            token_adress = selected_proposal["governor"]["id"].split(":")[
                -1
            ]  # id looks like eip155:1:0x35d9f4953748b318f18c30634bA299b237eeDfff
            vote_intention = self._get_service_vote_intention(
                token_adress
            )  # either GOOD or EVIL

            # TODO: get the vote option that corresponds to the vote intention using Langchain
            # proposal_title = selected_proposal["title"]
            # proposal_description = selected_proposal["description"]

            # TODO: for now, we select the FOR vote option
            vote_code = VOTES_TO_CODE["FOR"]

            sender = self.context.agent_address
            payload = EstablishVotePayload(sender=sender, vote_code=vote_code)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_service_vote_intention(self, token_address) -> str:
        """Aggregate all the users' vote intentions to find the service's vote intention"""

        vote_preference_counts = {"GOOD": 0, "EVIL": 0}

        # Count votes
        for delegation_data in self.synchronized_data.current_token_to_delegations[
            token_address
        ].values():
            if delegation_data["voting_preference"] in vote_preference_counts:
                vote_preference_counts[delegation_data["voting_preference"]] += int(
                    delegation_data["delegation_amount"]
                )

        # Sort the voring count by value
        sorted_preferences = sorted(
            vote_preference_counts.items(), key=lambda i: i[1], reverse=True
        )

        # Return the option with most votes
        return sorted_preferences[0][0]


class PrepareVoteTransactionBehaviour(ProposalVoterBaseBehaviour):
    """PrepareVoteTransactionBehaviour"""

    matching_round: Type[AbstractRound] = PrepareVoteTransactionRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            tx_hash = yield from self._get_safe_tx_hash()

            if not tx_hash:
                tx_hash = EstablishVoteRound.ERROR_PAYLOAD

            sender = self.context.agent_address
            payload = PrepareVoteTransactionPayload(sender=sender, tx_hash=tx_hash)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_safe_tx_hash(self) -> Generator[None, None, Optional[str]]:
        """Get the transaction hash of the Safe tx."""
        # Get the raw transaction from the Bravo Delegate contract
        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.delegate_contract_address,
            contract_id=str(DelegateContract.contract_id),
            contract_callable="get_cast_vote_data",
            proposal_id=int(self.synchronized_data.selected_proposal_id),
            support=self.synchronized_data.vote_code,
        )
        if (
            contract_api_msg.performative
            != ContractApiMessage.Performative.RAW_TRANSACTION
        ):  # pragma: nocover
            self.context.logger.warning("get_cast_vote_data unsuccessful!")
            return None

        data = cast(bytes, contract_api_msg.raw_transaction.body["data"])

        # Get the safe transaction hash
        ether_value = ETHER_VALUE
        safe_tx_gas = SAFE_TX_GAS
        to_address = self.params.delegate_contract_address

        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=to_address,
            value=ether_value,
            data=data,
            safe_tx_gas=safe_tx_gas,
        )
        if (
            contract_api_msg.performative
            != ContractApiMessage.Performative.RAW_TRANSACTION
        ):  # pragma: nocover
            self.context.logger.warning("get_raw_safe_transaction_hash unsuccessful!")
            return None

        safe_tx_hash = cast(str, contract_api_msg.raw_transaction.body["tx_hash"])
        safe_tx_hash = safe_tx_hash[2:]
        self.context.logger.info(f"Hash of the Safe transaction: {safe_tx_hash}")

        # temp hack:
        payload_string = hash_payload_to_hex(
            safe_tx_hash, ether_value, safe_tx_gas, to_address, data
        )

        return payload_string


class ProposalVoterRoundBehaviour(AbstractRoundBehaviour):
    """ProposalVoterRoundBehaviour"""

    initial_behaviour_cls = EstablishVoteBehaviour
    abci_app_cls = ProposalVoterAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        EstablishVoteBehaviour,
        PrepareVoteTransactionBehaviour,
    ]
