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
from packages.valory.skills.proposal_collector_abci.models import Params, SharedState
from packages.valory.skills.proposal_collector_abci.payloads import (
    CollectActiveSnapshotProposalsPayload,
    CollectActiveTallyProposalsPayload,
    SynchronizeDelegationsPayload,
    WriteDBPayload,
)
from packages.valory.skills.proposal_collector_abci.rounds import (
    CollectActiveSnapshotProposalsRound,
    CollectActiveTallyProposalsRound,
    ProposalCollectorAbciApp,
    SynchronizeDelegationsRound,
    SynchronizedData,
    WriteDBRound,
)
from packages.valory.skills.proposal_collector_abci.snapshot import (
    snapshot_proposal_query,
    snapshot_vp_query,
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


class WriteDBBehaviour(ProposalCollectorBaseBehaviour):
    """
    WriteDBBehaviour

    Prepares write data before writing to Ceramic.
    """

    matching_round: Type[AbstractRound] = WriteDBRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            write_data = [
                {
                    "op": "update",
                    "stream_id": self.params.ceramic_stream_id,
                    "did_str": self.params.ceramic_did_str,
                    "did_seed": self.params.ceramic_did_seed,
                    "data": self.synchronized_data.ceramic_db,
                }
            ]

            sender = self.context.agent_address
            payload = WriteDBPayload(
                sender=sender, write_data=json.dumps(write_data, sort_keys=True)
            )

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

            updated_proposal_data = yield from self._get_updated_proposal_data()
            sender = self.context.agent_address
            payload = CollectActiveTallyProposalsPayload(
                sender=sender, proposal_data=updated_proposal_data
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_updated_proposal_data(self) -> Generator[None, None, str]:
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

            # Filter out non-active proposals and those which use non-erc20 tokens, as well as those which use more than 1 token
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

        # Remove proposals where we don't have voting power
        ceramic_db = self.synchronized_data.ceramic_db
        delegations = ceramic_db["delegations"]
        delegated_tokens = [d["token_address"] for d in delegations]
        delegation_governors = [d["governor_address"] for d in delegations]

        active_proposals = filter(
            lambda ap: ap["governor"]["tokens"][0]["id"] in delegated_tokens
            and ap["governor"]["id"].split(":")[-1] in delegation_governors,
            active_proposals,
        )

        # Remove proposals where we have already voted
        active_proposals = filter(
            lambda ap: ap["id"] not in ceramic_db["voted_proposals"]["tally"],
            active_proposals,
        )

        # Process active proposals
        previous_proposals = self.synchronized_data.active_proposals["tally"]
        previous_proposals = {
            k: v
            for k, v in previous_proposals.items()
            if v["end"]["number"] > current_block  # remove previous expired proposals
        }

        for active_proposal in active_proposals:
            if (
                active_proposal["id"] not in previous_proposals
            ):  # This is a new proposal
                previous_proposals[active_proposal["id"]] = {
                    **active_proposal,
                    "vote_intention": None,
                    "remaining_blocks": active_proposal["end"]["number"]
                    - current_block,
                }
            else:
                previous_proposals[active_proposal["id"]]["remaining_blocks"] = (
                    previous_proposals[active_proposal["id"]]["end"]["number"]
                    - current_block
                )

        return json.dumps(
            {
                "updated_tally_proposals": previous_proposals,
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
            proposal_data = yield from self._get_updated_proposal_data()
            sender = self.context.agent_address
            payload = CollectActiveSnapshotProposalsPayload(
                sender=sender, proposal_data=proposal_data
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_updated_proposal_data(self) -> Generator[None, None, str]:
        """Get updated proposal data"""

        self.context.logger.info(
            f"Getting proposals from Snapshot API: {self.params.snapshot_api_endpoint}"
        )

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        finished = False
        i = 0
        n_retrieved_proposals = self.synchronized_data.n_snapshot_retrieved_proposals
        active_proposals = []

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

        n_retrieved_proposals += len(active_proposals)
        ceramic_db = self.synchronized_data.ceramic_db
        previous_proposals = self.synchronized_data.active_proposals["snapshot"]

        # Remove previous expired proposals
        now = cast(
            SharedState, self.context.state
        ).round_sequence.last_round_transition_timestamp.timestamp()

        previous_proposals = {
            k: v for k, v in previous_proposals.items() if v["end"] > now
        }

        # Remove active proposals where we have already voted
        active_proposals = filter(
            lambda ap: ap["id"] not in ceramic_db["vote_data"]["snapshot"],
            active_proposals,
        )

        # Filter out proposals that do not use the erc20-balance-of strategy
        active_proposals = filter(
            lambda ap: "erc20-balance-of" in [s["name"] for s in ap["strategies"]],
            active_proposals,
        )

        # Remove proposals where we dont have voting power
        votable_proposals = []
        for ap in active_proposals:
            has_voting_power = yield from self._has_snapshot_voting_power(ap)
            if has_voting_power:
                votable_proposals.append(ap)

        for votable_proposal in votable_proposals:
            if (
                votable_proposal["id"] not in previous_proposals
            ):  # This is a new proposal
                previous_proposals[votable_proposal["id"]] = {
                    **votable_proposal,
                    "vote_intention": None,
                    "remaining_seconds": votable_proposal["end"] - now,
                }
            else:
                previous_proposals[votable_proposal["id"]]["remaining_seconds"] = (
                    votable_proposal["end"] - now
                )

        return json.dumps(
            {
                "updated_snapshot_proposals": previous_proposals,
                "n_retrieved_proposals": n_retrieved_proposals,
                "finished": finished,
            },
            sort_keys=True,
        )

    def _has_snapshot_voting_power(self, proposal) -> Generator[None, None, bool]:
        """Checks whether the safe has voting power on this proposal"""

        variables = {
            "voter": self.synchronized_data.safe_contract_address,
            "space": proposal["space"]["name"],
            "proposal": proposal["id"],
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Wait for a couple seconds to avoid 429
        yield from self.sleep(self.params.tally_api_call_sleep_seconds)

        # Make the request
        response = yield from self.get_http_response(
            method="POST",
            url=self.params.snapshot_api_endpoint,
            content=json.dumps(
                {"query": snapshot_vp_query, "variables": variables}
            ).encode("utf-8"),
            headers=headers,
        )

        if response.status_code != HTTP_OK:
            self.context.logger.error(
                f"Could not retrieve voting power from Snapshot API. "
                f"Received status code {response.status_code}."
            )
            return False  # we skip this proposal for now

        response_json = json.loads(response.body)

        if "errors" in response_json:
            self.context.logger.error(
                f"Got errors while retrieving voting power from Snapshot: {response_json}"
            )
            return False  # we skip this proposal for now

        voting_power = response_json["data"]["vp"]["vp"]
        has_voting_power = voting_power > 0
        self.context.logger.info(
            f"Voting power for proposal {proposal['id']} [{proposal['space']['name']}]: {voting_power}"
        )
        return has_voting_power


class ProposalCollectorRoundBehaviour(AbstractRoundBehaviour):
    """ProposalCollectorRoundBehaviour"""

    initial_behaviour_cls = SynchronizeDelegationsBehaviour
    abci_app_cls = ProposalCollectorAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        CollectActiveTallyProposalsBehaviour,
        SynchronizeDelegationsBehaviour,
        WriteDBBehaviour,
        CollectActiveSnapshotProposalsBehaviour,
    ]
