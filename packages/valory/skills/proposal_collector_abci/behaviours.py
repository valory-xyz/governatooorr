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

"""This package contains round behaviours of ProposalCollectorAbciApp."""

import json
from abc import ABC
from typing import Generator, Set, Type, cast

from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.proposal_collector_abci.models import Params
from packages.valory.skills.proposal_collector_abci.payloads import (
    CollectActiveProposalsPayload,
    SelectProposalPayload,
    SynchronizeDelegationsPayload,
)
from packages.valory.skills.proposal_collector_abci.rounds import (
    CollectActiveProposalsRound,
    ProposalCollectorAbciApp,
    SelectProposalRound,
    SynchronizeDelegationsRound,
    SynchronizedData,
)
from packages.valory.skills.proposal_collector_abci.tally import proposal_query


HTTP_OK = 200


class ProposalCollectorBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour for the proposal_collector_abci skill."""

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def params(self) -> Params:
        """Return the params."""
        return cast(Params, super().params)


class SynchronizeDelegationsBehaviour(ProposalCollectorBaseBehaviour):
    """
    SynchronizeDelegations

    Synchronizes delegations across all agents.

    When there are multiple agents in the service not all agents have necessarily the same data before synchronizing.
    """

    matching_round: Type[AbstractRound] = SynchronizeDelegationsRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            new_delegations = json.dumps(
                self.context.state.new_delegations
            )  # no sorting needed here as there is no consensus over this data
            sender = self.context.agent_address
            # TODO: we also need to reset the new_delegations -> we do this on the next round , once every agent has all the data
            payload = SynchronizeDelegationsPayload(
                sender=sender, new_delegations=new_delegations
            )
            self.context.logger.info(f"New delegations = {new_delegations}")

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class CollectActiveProposalsBehaviour(ProposalCollectorBaseBehaviour):
    """
    CollectActiveProposals

    Behaviour used to collect active proposals from Tally for the governors
    for which the Governatooorr has received delegations.
    """

    matching_round: Type[AbstractRound] = CollectActiveProposalsRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            # Clear the new delegations # TODO: move this elsewhere
            self.context.state.new_delegations = []

            active_proposals = yield from self._get_active_proposals()
            sender = self.context.agent_address
            payload = CollectActiveProposalsPayload(
                sender=sender, active_proposals=active_proposals
            )
            self.context.logger.info(f"active_proposals = {active_proposals}")

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_active_proposals(self) -> Generator[None, None, str]:
        """Get proposals mentions"""

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Api-key": "{api_key}".format(api_key=self.params.tally_api_key),
        }

        # Get all the proposals
        variables = {
            "chainId": "eip155:1",
            "proposers": [],
            "governors": [],
            "pagination": {"limit": 200, "offset": 0},
        }

        self.context.logger.info(
            f"Retrieving proposals from Tally API [{self.params.tally_api_endpoint}]"
        )

        # Make the request
        response = yield from self.get_http_response(
            method="POST",
            url=self.params.tally_api_endpoint,
            headers=headers,
            content=json.dumps(
                {"query": proposal_query, "variables": variables}
            ).encode("utf-8"),
        )

        if response.status_code != HTTP_OK:
            self.context.logger.error(
                f"Could not retrieve data from Tally API. "
                f"Received status code {response.status_code}."
            )
            return CollectActiveProposalsRound.ERROR_PAYLOAD

        response_json = json.loads(response.body)

        self.context.logger.info(f"Response from Tally API: {response_json}")

        if "errors" in response_json:
            self.context.logger.error("Got errors while retrieving the data from Tally")
            return CollectActiveProposalsRound.ERROR_PAYLOAD

        # Filter out non-active proposals and those which use non-erc20 tokens
        active_proposals = list(
            filter(
                lambda p: p["statusChanges"][-1]["type"] == "ACTIVE"
                and len(p["governor"]["tokens"]) == 1
                and "erc20" in p["governor"]["tokens"][0]["id"],
                response_json["data"]["proposals"],
            )
        )

        p_ids = [p["id"] for p in active_proposals]

        self.context.logger.info(f"Retrieved active proposals: {p_ids}")

        return json.dumps(
            {
                "active_proposals": active_proposals,
            },
            sort_keys=True,
        )


class SelectProposalBehaviour(ProposalCollectorBaseBehaviour):
    """
    SelectProposal

    Select the proposal on which to vote.
    """

    matching_round: Type[AbstractRound] = SelectProposalRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            # TODO: we enter this round after a successful tx_submission
            # We need to check if that is the case and remove the first proposal
            # from the list.
            # TODO: we want to make sure we only vote towards the end of the voting period.
            # But it would be great if we could get the voting intention right away, so we can
            # display this on the frontend.

            # Get all the governors from the current delegations
            delegation_governors = [
                d["governor_address"] for d in self.synchronized_data.delegations
            ]

            # Get the proposals where we can vote:
            # - Active
            # - Not voted before
            # - Governor in the delegation list
            votable_active_proposals = {
                p_id: p
                for p_id, p in self.synchronized_data.proposals.items()
                if p["active"]
                and not p["vote"]
                and p["governor"]["id"].split(":")[-1] in delegation_governors
            }

            # Some proposals have an ETA, some dont
            # We will prioritise those with it
            active_proposals_with_eta = list(
                filter(lambda p: p["eta"] != "", votable_active_proposals.values())
            )
            active_proposals_no_eta = list(
                filter(lambda p: p["eta"] == "", votable_active_proposals.values())
            )

            # Sort by ETA
            active_proposals_with_eta_sorted = sorted(
                active_proposals_with_eta, key=lambda p: int(p["eta"]), reverse=False
            )

            # Sort by ID
            active_proposals_no_eta_sorted = sorted(
                active_proposals_no_eta, key=lambda p: int(p["id"]), reverse=False
            )

            # Add all sorted proposals
            sorted_proposals = (
                active_proposals_with_eta_sorted + active_proposals_no_eta_sorted
            )

            # Select the first proposal
            proposal_id = sorted_proposals[0]["id"] if sorted_proposals else None

            # Check whether we have delegations
            if not proposal_id:
                proposal_id = SelectProposalRound.NO_PROPOSAL

            sender = self.context.agent_address
            payload = SelectProposalPayload(sender=sender, proposal_id=proposal_id)

            self.context.logger.info(f"proposal_id = {proposal_id}")

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class ProposalCollectorRoundBehaviour(AbstractRoundBehaviour):
    """ProposalCollectorRoundBehaviour"""

    initial_behaviour_cls = SynchronizeDelegationsBehaviour
    abci_app_cls = ProposalCollectorAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        CollectActiveProposalsBehaviour,
        SelectProposalBehaviour,
        SynchronizeDelegationsBehaviour,
    ]
