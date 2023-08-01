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
from typing import Generator, Optional, Set, Type, cast

from packages.valory.protocols.ledger_api.message import LedgerApiMessage
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.proposal_collector_abci.models import Params
from packages.valory.skills.proposal_collector_abci.payloads import (
    CollectActiveSnapshotProposalsPayload,
    CollectActiveTallyProposalsPayload,
    SynchronizeDelegationsPayload,
)
from packages.valory.skills.proposal_collector_abci.rounds import (
    CollectActiveSnapshotProposalsRound,
    CollectActiveTallyProposalsRound,
    ProposalCollectorAbciApp,
    SynchronizeDelegationsRound,
    SynchronizedData,
)
from packages.valory.skills.proposal_collector_abci.snapshot import (
    snapshot_proposal_query,
)
from packages.valory.skills.proposal_collector_abci.tally import (
    governor_query,
    proposal_query,
)


HTTP_OK = 200
SNAPSHOT_REQUEST_STEP = 200
SNAPSHOT_PROPOSAL_ROUND_LIMIT = 200  # avoids too big payloads
MAX_RETRIES = 3


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

    def get_current_block(self) -> Generator[None, None, Optional[int]]:
        """Get the current block"""
        ledger_api_response = yield from self.get_ledger_api_response(
            performative=LedgerApiMessage.Performative.GET_STATE,
            ledger_callable="get_block",
            block_identifier="latest",
        )
        if ledger_api_response.performative != LedgerApiMessage.Performative.STATE:
            self.context.logger.error(
                f"Error retrieving the latest block: {ledger_api_response.performative}"
            )
            return None
        return int(ledger_api_response.state.body.get("number"))


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


class CollectActiveTallyProposalsBehaviour(ProposalCollectorBaseBehaviour):
    """
    CollectActiveProposals

    Behaviour used to collect active proposals from Tally for the governors
    for which the Governatooorr has received delegations.
    """

    matching_round: Type[AbstractRound] = CollectActiveTallyProposalsRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Clear the new delegations # TODO: move this elsewhere
            self.context.state.new_delegations = []

            updated_proposals = yield from self._get_updated_proposals()
            sender = self.context.agent_address
            payload = CollectActiveTallyProposalsPayload(
                sender=sender, proposals=updated_proposals
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_updated_proposals(self) -> Generator[None, None, str]:
        """Get proposals mentions"""

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Api-key": "{api_key}".format(api_key=self.params.tally_api_key),
        }

        # Get all the governors, sorted by number of active proposals
        variables = {
            "chainIds": "eip155:1",
            "addresses": [],
            "includeInactive": False,
            "sort": {"field": "ACTIVE_PROPOSALS", "order": "DESC"},
            "pagination": {"limit": 200, "offset": 0},
        }

        self.context.logger.info(
            f"Retrieving governors from Tally API [{self.params.tally_api_endpoint}]. Request variables: {variables}"
        )

        # Make the request
        response = yield from self.get_http_response(
            method="POST",
            url=self.params.tally_api_endpoint,
            headers=headers,
            content=json.dumps(
                {"query": governor_query, "variables": variables}
            ).encode("utf-8"),
        )

        if response.status_code != HTTP_OK:
            self.context.logger.error(
                f"Could not retrieve data from Tally API. "
                f"Received status code {response.status_code}."
            )
            retries = self.synchronized_data.tally_api_retries + 1
            if retries >= MAX_RETRIES:
                return CollectActiveTallyProposalsRound.MAX_RETRIES_PAYLOAD
            return CollectActiveTallyProposalsRound.ERROR_PAYLOAD

        response_json = json.loads(response.body)

        if "errors" in response_json:
            self.context.logger.error("Got errors while retrieving the data from Tally")
            return CollectActiveTallyProposalsRound.ERROR_PAYLOAD

        # Filter out governors with no active proposals
        governors = response_json["data"]["governors"]

        governors_with_active_proposals = list(
            filter(lambda g: int(g["proposalStats"]["active"]) > 0, governors)
        )
        governor_ids = [g["id"].split(":")[-1] for g in governors_with_active_proposals]

        self.context.logger.info(
            f"Retrieved governors with active proposals: {governor_ids}"
        )

        active_proposals = []
        for gid in governor_ids:
            # Get all the proposals for this governor
            variables = {
                "chainId": "eip155:1",
                "proposers": [],
                "governors": gid,
                "pagination": {"limit": 200, "offset": 0},
            }

            self.context.logger.info(
                f"Retrieving proposals from Tally API [{self.params.tally_api_endpoint}]. Request variables: {variables}"
            )

            # Wait for a couple seconds to avoid 429
            yield from self.sleep(self.params.tally_api_call_sleep_seconds)

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
                retries = self.synchronized_data.tally_api_retries + 1
                if retries >= MAX_RETRIES:
                    return CollectActiveTallyProposalsRound.MAX_RETRIES_PAYLOAD
                return CollectActiveTallyProposalsRound.ERROR_PAYLOAD

            response_json = json.loads(response.body)

            if "errors" in response_json:
                self.context.logger.error(
                    "Got errors while retrieving the data from Tally"
                )
                return CollectActiveTallyProposalsRound.ERROR_PAYLOAD

            # Filter out non-active proposals and those which use non-erc20 tokens
            filtered_proposals = list(
                filter(
                    lambda p: p["statusChanges"][-1]["type"] == "ACTIVE"
                    and len(p["governor"]["tokens"]) == 1
                    and "erc20" in p["governor"]["tokens"][0]["id"],
                    response_json["data"]["proposals"],
                )
            )

            p_ids = [p["id"] for p in filtered_proposals]

            self.context.logger.info(
                f"Retrieved active proposals (erc20 only) for governor {gid}: {p_ids}"
            )

            active_proposals.extend(filtered_proposals)

        # Remove proposals for which the vote end block is in the past
        current_block = yield from self.get_current_block()
        if current_block is None:
            return CollectActiveTallyProposalsRound.BLOCK_RETRIEVAL_ERROR

        active_proposals = filter(
            lambda ap: ap["end"]["number"] > current_block, active_proposals
        )

        # Update the current proposals
        proposals = self.synchronized_data.proposals

        # Set all the current proposals "votable" field to False
        for proposal in proposals.values():
            proposal["votable"] = False

        proposals_to_refresh = set()

        for active_proposal in active_proposals:
            if active_proposal["id"] not in proposals:  # This is a new proposal
                proposals[active_proposal["id"]] = {
                    **active_proposal,
                    "votable": True,
                    "vote_intention": None,
                    "vote_choice": None,
                    "vote": None,  # We have not voted for this one yet
                    "remaining_blocks": active_proposal["end"]["number"]
                    - current_block,
                }
                proposals_to_refresh.add(active_proposal["id"])
            else:
                # The proposal is still votable
                proposals[active_proposal["id"]]["votable"] = True
                proposals[active_proposal["id"]]["remaining_blocks"] = (
                    proposals[active_proposal["id"]]["end"]["number"] - current_block
                )

        # Get all the governors from the current delegations
        delegation_governors = [
            d["governor_address"] for d in self.synchronized_data.delegations
        ]

        # Get the proposals where we can vote:
        # - Votable
        # - Not voted before
        # - Governor in the delegation list
        votable_proposals = (
            proposal
            for proposal in proposals.values()
            if proposal["votable"]
            and not proposal["vote"]
            and proposal["governor"]["id"].split(":")[-1] in delegation_governors
        )

        # Sort votable_proposals by vote end block number, in ascending order
        votable_proposal_ids = [
            p["id"]
            for p in sorted(votable_proposals, key=lambda p: p["remaining_blocks"])
        ]

        return json.dumps(
            {
                "proposals": proposals,
                "votable_proposal_ids": votable_proposal_ids,
                "proposals_to_refresh": list(proposals_to_refresh),
            },
            sort_keys=True,
        )


class CollectActiveSnapshotProposalsBehaviour(ProposalCollectorBaseBehaviour):
    """
    CollectActiveSnapshotProposals

    Behaviour used to collect active proposals from Snapshot
    """

    matching_round: Type[AbstractRound] = CollectActiveSnapshotProposalsRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            updated_proposals = yield from self._get_updated_proposals()
            sender = self.context.agent_address
            payload = CollectActiveSnapshotProposalsPayload(
                sender=sender, proposals=updated_proposals
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_updated_proposals(self) -> Generator[None, None, str]:
        """Get updated proposals"""

        active_proposals = []
        i = 0
        n_retrieved_proposals = len(self.synchronized_data.snapshot_proposals)

        self.context.logger.info(
            f"Getting proposals from Snapshot API: {self.params.snapshot_api_endpoint}"
        )

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        finished = False

        while True:
            skip = n_retrieved_proposals + SNAPSHOT_REQUEST_STEP * i

            self.context.logger.info(
                f"Getting {SNAPSHOT_REQUEST_STEP} proposals skipping the first {skip}"
            )

            variables = {
                "first": SNAPSHOT_REQUEST_STEP,
                "skip": skip,
            }

            # Make the request
            response = yield from self.get_http_response(
                method="POST",
                url=self.params.snapshot_api_endpoint,
                headers=headers,
                content=json.dumps(
                    {"query": snapshot_proposal_query, "variables": variables}
                ).encode("utf-8"),
            )

            if response.status_code != HTTP_OK:
                self.context.logger.error(
                    f"Could not retrieve proposals from Snapshot API. "
                    f"Received status code {response.status_code}.\n{response}"
                )
                retries = self.synchronized_data.snapshot_api_retries + 1
                if retries >= MAX_RETRIES:
                    return CollectActiveSnapshotProposalsRound.MAX_RETRIES_PAYLOAD
                return CollectActiveSnapshotProposalsRound.ERROR_PAYLOAD

            response_json = json.loads(response.body)

            if "errors" in response_json:
                self.context.logger.error(
                    f"Got errors while retrieving the data from Snapshot: {response_json}"
                )
                return CollectActiveTallyProposalsRound.ERROR_PAYLOAD

            new_proposals = response_json["data"]["proposals"]

            if not new_proposals:
                finished = True
                break

            active_proposals.extend(new_proposals)
            i += 1
            self.context.logger.info(f"Accumulated proposals: {len(active_proposals)}")

            if len(active_proposals) >= SNAPSHOT_PROPOSAL_ROUND_LIMIT:
                self.context.logger.info("Reached proposal payload limit")
                break

        return json.dumps(
            {
                "snapshot_proposals": active_proposals,
                "finished": finished,
            },
            sort_keys=True,
        )


class ProposalCollectorRoundBehaviour(AbstractRoundBehaviour):
    """ProposalCollectorRoundBehaviour"""

    initial_behaviour_cls = SynchronizeDelegationsBehaviour
    abci_app_cls = ProposalCollectorAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        CollectActiveTallyProposalsBehaviour,
        SynchronizeDelegationsBehaviour,
        CollectActiveSnapshotProposalsBehaviour,
    ]
