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
from typing import Generator, Set, Type, cast, Optional, Dict
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
from packages.valory.skills.proposal_voter.dialogues import LlmDialogues, LlmDialogue
from packages.valory.connections.langchain.connection import (
    CONNECTION_ID as LLM_CONNECTION_PUBLIC_ID,
)
from packages.valory.protocols.llm.message import LlmMessage
from packages.valory.skills.abstract_round_abci.models import (
    Requests,
)

SAFE_TX_GAS = 0
ETHER_VALUE = 0

VOTING_OPTIONS = "For, Against, and Abstain"
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
            if not selected_proposal:
                raise ValueError(
                    f"Proposal with id {p_id} has not been found in the active proposals"
                )

            # Get the service aggregated vote intention
            token_adress = selected_proposal["token_address"]["id"]
            vote_intention = self._get_service_vote_intention(
                token_adress
            )  # either GOOD or EVIL
            prompt_template = "Here is a voting proposal for a protocol: `{proposal}`. How should I vote on the voting proposal if my intent was to {voting_intention_snippet} and the voting options are {voting_options}? Please answer with only the voting option."
            voting_intention_snippet = (
                "cause chaos to the protocol"
                if vote_intention == "evil"
                else "contribute positively to the protocol"
            )
            prompt_values = {
                "proposal": selected_proposal["title"]
                + "\n"
                + selected_proposal["description"],
                "voting_intention": voting_intention_snippet,
                "voting_options": VOTING_OPTIONS,
            }

            vote = yield self._get_vote(prompt_template, prompt_values)

            sender = self.context.agent_address
            payload = EstablishVotePayload(sender=sender, vote=vote)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_vote(
        self, prompt_template: str, prompt_values: Dict[str, str]
    ) -> Generator[None, None, str]:
        """Get the vote from LLM."""
        llm_dialogues = cast(LlmDialogues, self.context.llm_dialogues)

        # llm request message
        request_llm_message, llm_dialogue = llm_dialogues.create(
            counterparty=str(LLM_CONNECTION_PUBLIC_ID),
            performative=LlmMessage.Performative.REQUEST,
            prompt_template=prompt_template,
            prompt_values=prompt_values,
        )
        request_llm_message = cast(LlmMessage, request_llm_message)
        llm_dialogue = cast(LlmDialogue, llm_dialogue)
        llm_response_message = yield from self._do_request(
            request_llm_message, llm_dialogue
        )
        vote = llm_response_message.value

        vote = vote.strip("\n")

        if vote not in VOTES_TO_CODE:
            raise ValueError(f"Invalid vote: {vote}")

        return vote

    def _do_request(
        self,
        llm_message: LlmMessage,
        llm_dialogue: LlmDialogue,
        timeout: Optional[float] = None,
    ) -> Generator[None, None, LlmMessage]:
        """
        Do a request and wait the response, asynchronously.

        :param llm_message: The request message
        :param llm_dialogue: the HTTP dialogue associated to the request
        :param timeout: seconds to wait for the reply.
        :yield: LLMMessage object
        :return: the response message
        """
        self.context.outbox.put_message(message=llm_message)
        request_nonce = self._get_request_nonce_from_dialogue(llm_dialogue)
        cast(Requests, self.context.requests).request_id_to_callback[
            request_nonce
        ] = self.get_callback_request()
        # notify caller by propagating potential timeout exception.
        response = yield from self.wait_for_message(timeout=timeout)
        return response

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

        self.context.logger.info(f"_get_service_vote_intention = {sorted_preferences[0][0]}")

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
