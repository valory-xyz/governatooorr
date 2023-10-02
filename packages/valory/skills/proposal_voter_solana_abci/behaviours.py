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

"""This package contains round behaviours of ProposalVoterSolanaAbciApp."""

import json
from abc import ABC
from typing import Dict, Generator, Optional, Set, Type, cast

from packages.valory.connections.openai.connection import (
    PUBLIC_ID as LLM_CONNECTION_PUBLIC_ID,
)
from packages.valory.contracts.solana_governance.contract import (
    SolanaGovernanceContract,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.llm.message import LlmMessage
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.abstract_round_abci.models import Requests
from packages.valory.skills.proposal_voter_solana_abci.dialogues import (
    LlmDialogue,
    LlmDialogues,
)
from packages.valory.skills.proposal_voter_solana_abci.models import Params
from packages.valory.skills.proposal_voter_solana_abci.payloads import (
    EstablishVotePayload,
    PrepareVoteTransactionPayload,
)
from packages.valory.skills.proposal_voter_solana_abci.rounds import (
    EstablishVoteRound,
    PrepareVoteTransactionRound,
    ProposalVoterSolanaAbciApp,
    SynchronizedData,
)


SPL_GOVERNANCE_PROGRAM = "GovER5Lthms3bLBqWub97yVrMmEogzX7xNjdXpPPCVZw"

VOTING_OPTIONS = [
    "APPROVE",
    "DENY",
    "ABSTAIN",
    "VETO",
]


class ProposalVoterBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour for the proposal_voter_solana_abci skill."""

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
            realms_active_proposals = yield from self._refresh_proposal_vote()
            self.context.logger.info(
                f"Refreshed realms_active_proposals: {realms_active_proposals}"
            )
            votable_proposal_ids = list(
                realms_active_proposals.keys()
            )  # all are votable for now
            self.context.logger.info(f"votable_proposals_ids: {votable_proposal_ids}")
            sender = self.context.agent_address
            payload = EstablishVotePayload(
                sender=sender,
                content=json.dumps(
                    {
                        "realms_active_proposals": realms_active_proposals,
                        "votable_proposal_ids": votable_proposal_ids,
                    },
                    sort_keys=True,
                ),
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
        self.set_done()

    def _refresh_proposal_vote(self) -> Generator[None, None, dict]:
        """Generate proposal votes"""
        realms_active_proposals = self.synchronized_data.realms_active_proposals
        for proposal_id in realms_active_proposals:
            vote_intention = "good"
            proposal = realms_active_proposals[proposal_id]

            # LLM call
            prompt_template = "Here is a voting proposal for a protocol: `{proposal}`. How should I vote on the voting proposal if my intent was to {voting_intention_snippet} and the voting options are {voting_options}? Please answer with only the voting option."
            voting_intention_snippet = (
                "cause chaos to the protocol"
                if vote_intention == "evil"
                else "contribute positively to the protocol"
            )
            prompt_values = {
                "proposal": proposal["title"] + "\n" + proposal["description"],
                "voting_intention_snippet": voting_intention_snippet,
                "voting_options": " and ".join(VOTING_OPTIONS),
            }
            self.context.logger.info(
                f"Sending LLM request...\n{prompt_template.format(**prompt_values)}"
            )
            vote = yield from self._get_vote(prompt_template, prompt_values)
            vote = vote.upper()
            if vote not in VOTING_OPTIONS:
                raise ValueError(f"Invalid vote: {vote}")

            self.context.logger.info(f"Vote: {vote}")
            proposal["vote_choice"] = vote
        return realms_active_proposals

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


class PrepareVoteTransactionsBehaviour(ProposalVoterBaseBehaviour):
    """PrepareVoteTransactionsBehaviour"""

    matching_round: Type[AbstractRound] = PrepareVoteTransactionRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            realms_active_proposals = self.synchronized_data.realms_active_proposals
            votable_proposal_ids = self.synchronized_data.votable_proposal_ids
            self.context.logger.info(f"Votable proposal ids: {votable_proposal_ids}")
            payload_content = {
                "votable_proposal_ids": votable_proposal_ids,
            }
            if not votable_proposal_ids:
                self.context.logger.info("No proposals to vote on")
                tx_hash = PrepareVoteTransactionRound.NO_VOTE_PAYLOAD
                payload_content["tx_hash"] = tx_hash
            else:
                # TODO
                # we get the first one, because the votable proposal ids are sorted by their remaining blocks, ascending
                # selected_proposal_id = votable_proposal_ids[0]
                # selected_proposal = realms_active_proposals[selected_proposal_id]
                # response = yield from self.get_contract_api_response(
                #     performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,
                #     contract_address=SPL_GOVERNANCE_PROGRAM,
                #     contract_id=str(SolanaGovernanceContract.contract_id),
                #     contract_callable="cast_vote_ix",
                #     voter=selected_proposal["voter"],
                #     realm=selected_proposal["realm"],
                #     proposal=selected_proposal["proposal"],
                #     governing_token_mint=selected_proposal["governing_token_mint"],
                #     governance=selected_proposal["governance"],
                #     proposal_owner=selected_proposal["proposal_owner"],
                #     vote_choice=selected_proposal["vote_choice"],
                # )
                payload_content["tx_hash"] = None

            payload = PrepareVoteTransactionPayload(
                sender=self.context.agent_address,
                content=json.dumps(payload_content, sort_keys=True),
            )

            with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
                yield from self.send_a2a_transaction(payload)
                yield from self.wait_until_round_end()

            self.set_done()


class ProposalVoterRoundBehaviour(AbstractRoundBehaviour):
    """ProposalVoterRoundBehaviour"""

    initial_behaviour_cls = EstablishVoteBehaviour
    abci_app_cls = ProposalVoterSolanaAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        EstablishVoteBehaviour,
        PrepareVoteTransactionsBehaviour,
    ]
