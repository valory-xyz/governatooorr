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

import json
from abc import ABC
from typing import Dict, Generator, Optional, Set, Type, cast

from packages.valory.connections.openai.connection import (
    PUBLIC_ID as LLM_CONNECTION_PUBLIC_ID,
)
from packages.valory.contracts.delegate.contract import DelegateContract
from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.llm.message import LlmMessage
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.abstract_round_abci.models import Requests
from packages.valory.skills.proposal_voter_abci.dialogues import (
    LlmDialogue,
    LlmDialogues,
)
from packages.valory.skills.proposal_voter_abci.models import Params, PendingVote
from packages.valory.skills.proposal_voter_abci.rounds import (
    EstablishVotePayload,
    EstablishVoteRound,
    PrepareVoteTransactionPayload,
    PrepareVoteTransactionRound,
    ProposalVoterAbciApp,
    SynchronizedData,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)


SAFE_TX_GAS = 0
ETHER_VALUE = 0

VOTING_OPTIONS = "For, Against, and Abstain"
VOTES_TO_CODE = {"FOR": 0, "AGAINST": 1, "ABSTAIN": 2}


class ProposalVoterBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour for the proposal_voter_abci skill."""

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

            proposal_ids_to_refresh = self.synchronized_data.proposals_to_refresh
            proposals = self.synchronized_data.proposals

            # Update the proposals' vote intention
            for proposal_id in proposal_ids_to_refresh:
                if not proposals[proposal_id]["votable"]:
                    continue

                self.context.logger.info(
                    f"Getting vote intention for proposal {proposal_id}"
                )

                proposal_token = proposals[proposal_id]["governor"]["tokens"][0]["id"]

                # Get the service aggregated vote intention
                vote_intention = (
                    self._get_service_vote_intention(  # either GOOD, EVIL or None
                        proposal_token
                    )
                )
                proposals[proposal_id]["vote_intention"] = vote_intention

                self.context.logger.info(f"Vote intention: {vote_intention}")

                # Do not call the LLM until we have delegations for this proposal
                if not vote_intention:
                    continue

                # LLM call
                prompt_template = "Here is a voting proposal for a protocol: `{proposal}`. How should I vote on the voting proposal if my intent was to {voting_intention_snippet} and the voting options are {voting_options}? Please answer with only the voting option."
                voting_intention_snippet = (
                    "cause chaos to the protocol"
                    if vote_intention == "evil"
                    else "contribute positively to the protocol"
                )
                prompt_values = {
                    "proposal": proposals[proposal_id]["title"]
                    + "\n"
                    + proposals[proposal_id]["description"],
                    "voting_intention_snippet": voting_intention_snippet,
                    "voting_options": VOTING_OPTIONS,
                }

                vote = yield from self._get_vote(prompt_template, prompt_values)

                self.context.logger.info(f"Vote: {vote}")

                proposals[proposal_id]["vote_choice"] = vote

            sender = self.context.agent_address
            payload = EstablishVotePayload(
                sender=sender, proposals=json.dumps(proposals, sort_keys=True)
            )

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

        vote = vote.strip()
        vote = vote.upper()

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

    def _get_service_vote_intention(self, token_address) -> Optional[str]:
        """Aggregate all the users' vote intentions to find the service's vote intention"""

        vote_preference_counts = {"GOOD": 0, "EVIL": 0}

        current_delegations = self.synchronized_data.delegations
        current_delegations = list(
            filter(lambda d: d["token_address"] == token_address, current_delegations)
        )

        # Do not express intention if we have no delegations
        if not current_delegations:
            self.context.logger.info(
                f"There are no delegations for token {token_address}"
            )
            return None

        # Count votes
        for delegation in current_delegations:
            if delegation["voting_preference"] in vote_preference_counts:
                vote_preference_counts[delegation["voting_preference"]] += int(
                    delegation["delegated_amount"]
                )

        # Sort the voring count by value
        sorted_preferences = sorted(
            vote_preference_counts.items(), key=lambda i: i[1], reverse=True
        )

        self.context.logger.info(
            f"_get_service_vote_intention = {sorted_preferences[0][0]}"
        )

        # Return the option with most votes
        return sorted_preferences[0][0]


class PrepareVoteTransactionBehaviour(ProposalVoterBaseBehaviour):
    """PrepareVoteTransactionBehaviour"""

    matching_round: Type[AbstractRound] = PrepareVoteTransactionRound

    def _get_proposal_info(self):
        """Get the votable proposals' ids and the proposals."""
        votable_proposal_ids = self.synchronized_data.votable_proposal_ids
        proposals = self.synchronized_data.proposals

        if self.synchronized_data.just_voted:
            # Pending votes are stored in the shared state and only updated in the proposals list
            # when the transaction has been verified, and therefore we know that it is a submitted vote.
            submitted_vote = self.context.state.pending_vote
            submitted_vote_id = submitted_vote.proposal_id
            submitted_proposal = proposals[submitted_vote_id]
            submitted_proposal["vote"] = submitted_vote.vote_choice
            submitted_proposal["votable"] = submitted_vote.votable

            # remove the submitted vote from the votable list, if it is present there
            if submitted_vote_id in votable_proposal_ids:
                votable_proposal_ids.remove(submitted_vote_id)

        # Filter the votable proposals, keeping only those towards the end of their voting period
        votable_proposal_ids = list(
            filter(
                lambda p_id: proposals[p_id]["remaining_blocks"]
                <= self.params.voting_block_threshold,
                votable_proposal_ids,
            )
        )

        return votable_proposal_ids, proposals

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            votable_proposal_ids, proposals = self._get_proposal_info()

            self.context.logger.info(f"Votable proposal ids: {votable_proposal_ids}")

            if not votable_proposal_ids:
                tx_hash = PrepareVoteTransactionRound.NO_VOTE_PAYLOAD

            else:
                # we get the first one, because the votable proposal ids are sorted by their remaining blocks, ascending
                selected_proposal_id = votable_proposal_ids[0]
                selected_proposal = proposals[selected_proposal_id]
                vote_choice = selected_proposal["vote_choice"]
                # Pending votes are stored in the shared state and only updated in the proposals list
                # when the transaction has been verified, and therefore we know that it is a submitted vote.
                self.context.state.pending_vote = PendingVote(
                    selected_proposal_id, vote_choice
                )

                governor_address = selected_proposal["governor"]["id"].split(":")[-1]
                vote_code = VOTES_TO_CODE[selected_proposal["vote_choice"]]

                # Vote for the first proposal in the list
                tx_hash = yield from self._get_safe_tx_hash(
                    governor_address, selected_proposal_id, vote_code
                )

                self.context.logger.info(
                    f"Voting for proposal {selected_proposal_id}: {vote_choice}"
                )
                self.context.logger.info(f"tx_hash is {tx_hash}")

            if not tx_hash:
                tx_hash = PrepareVoteTransactionRound.ERROR_PAYLOAD

            payload_content = {
                "tx_hash": tx_hash,
                "proposals": proposals,
                "votable_proposal_ids": votable_proposal_ids,
            }

            payload = PrepareVoteTransactionPayload(
                sender=self.context.agent_address,
                content=json.dumps(payload_content, sort_keys=True),
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_safe_tx_hash(
        self,
        governor_address: str,
        proposal_id: str,
        vote_code: int,
    ) -> Generator[None, None, Optional[str]]:
        """Get the transaction hash of the Safe tx."""
        # Get the raw transaction from the Bravo Delegate contract
        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=governor_address,
            contract_id=str(DelegateContract.contract_id),
            contract_callable="get_cast_vote_data",
            proposal_id=int(proposal_id),
            support=vote_code,
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_cast_vote_data unsuccessful!: {contract_api_msg}"
            )
            return None
        data = cast(bytes, contract_api_msg.state.body["data"])

        # Get the safe transaction hash
        ether_value = ETHER_VALUE
        safe_tx_gas = SAFE_TX_GAS

        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=governor_address,
            value=ether_value,
            data=data,
            safe_tx_gas=safe_tx_gas,
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_raw_safe_transaction_hash unsuccessful!: {contract_api_msg}"
            )
            return None

        safe_tx_hash = cast(str, contract_api_msg.state.body["tx_hash"])
        safe_tx_hash = safe_tx_hash[2:]
        self.context.logger.info(f"Hash of the Safe transaction: {safe_tx_hash}")

        # temp hack:
        payload_string = hash_payload_to_hex(
            safe_tx_hash, ether_value, safe_tx_gas, governor_address, data
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
