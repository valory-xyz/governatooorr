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

"""This package contains the rounds of ProposalCollectorAbciApp."""

import json
from enum import Enum
from typing import Dict, Optional, Set, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    BaseSynchronizedData,
    CollectDifferentUntilAllRound,
    CollectSameUntilThresholdRound,
    DegenerateRound,
    EventToTimeout,
    TransactionNotValidError,
    get_name,
)
from packages.valory.skills.proposal_collector_abci.payloads import (
    CollectActiveSnapshotProposalsPayload,
    CollectActiveTallyProposalsPayload,
    SynchronizeDelegationsPayload,
)


SNAPSHOT_PROPOSAL_TOTAL_LIMIT = 200  # we focus on the first expiring proposals only


class Event(Enum):
    """ProposalCollectorAbciApp Events"""

    VOTE = "vote"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"
    DONE = "done"
    API_ERROR = "api_error"
    NO_PROPOSAL = "no_proposal"
    CONTRACT_ERROR = "contract_error"
    BLOCK_RETRIEVAL_ERROR = "block_retrieval_error"
    WRITE_DELEGATIONS = "write_delegations"
    REPEAT = "repeat"


class SynchronizedData(BaseSynchronizedData):
    """
    Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def delegations(self) -> list:
        """Get the delegations."""
        return cast(list, self.db.get("delegations", []))

    @property
    def proposals(self) -> dict:
        """Get the proposals from Tally."""
        return cast(dict, self.db.get("proposals", {}))

    @property
    def snapshot_proposals(self) -> list:
        """Get the proposals from Snapshot."""
        return cast(list, self.db.get("snapshot_proposals", []))

    @property
    def votable_proposal_ids(self) -> set:
        """Get the votable proposal ids, sorted by their remaining blocks until expiration, in ascending order."""
        return cast(set, self.db.get("votable_proposal_ids", {}))

    @property
    def proposals_to_refresh(self) -> list:
        """Get the proposals that need to be refreshed: vote intention."""
        return cast(list, self.db.get("proposals_to_refresh", []))

    @property
    def tally_api_retries(self) -> int:
        """Get the amount of API call retries."""
        return cast(int, self.db.get("tally_api_retries", 0))

    @property
    def snapshot_api_retries(self) -> int:
        """Get the amount of API call retries."""
        return cast(int, self.db.get("snapshot_api_retries", 0))

    @property
    def write_data(self) -> list:
        """Get the write_data."""
        return cast(list, self.db.get_strict("write_data"))


class SynchronizeDelegationsRound(CollectDifferentUntilAllRound):
    """SynchronizeDelegations"""

    payload_class = SynchronizeDelegationsPayload
    synchronized_data_class = SynchronizedData

    def check_payload(self, payload: SynchronizeDelegationsPayload) -> None:
        """Check Payload"""
        new = payload.values
        existing = [
            collection_payload.values
            for collection_payload in self.collection.values()
            # do not consider empty delegations
            if json.loads(collection_payload.json["new_delegations"])
        ]

        if payload.sender not in self.collection and new in existing:
            raise TransactionNotValidError(
                f"`CollectDifferentUntilAllRound` encountered a value {new!r} that already exists. "
                f"All values: {existing}"
            )

        if payload.round_count != self.synchronized_data.round_count:
            raise TransactionNotValidError(
                f"Expected round count {self.synchronized_data.round_count} and got {payload.round_count}."
            )

        if payload.sender in self.collection:
            raise TransactionNotValidError(
                f"sender {payload.sender} has already sent value for round: {self.round_id}"
            )

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""

        if self.collection_threshold_reached:
            delegations = cast(SynchronizedData, self.synchronized_data).delegations
            proposals = cast(SynchronizedData, self.synchronized_data).proposals
            proposals_to_refresh = set()

            new_delegations = []
            for payload in self.collection.values():
                # Add this agent's new delegations
                new_delegations.extend(json.loads(payload.json["new_delegations"]))

            if not new_delegations:
                synchronized_data = self.synchronized_data.update(
                    synchronized_data_class=SynchronizedData,
                    **{
                        get_name(SynchronizedData.proposals_to_refresh): list(
                            proposals_to_refresh
                        ),
                    },
                )
                return synchronized_data, Event.DONE

            for nd in new_delegations:
                # Check if new delegation needs to replace a previous one
                existing = False
                for i, d in enumerate(delegations):
                    if (
                        nd["user_address"] == d["user_address"]
                        and nd["token_address"] == d["token_address"]
                    ):
                        delegations[i] = nd
                        existing = True
                        break
                if not existing:
                    delegations.append(nd)

                # Do we need to refresh any proposal?
                for p in proposals.values():
                    if nd["token_address"] in p["governor"]["tokens"][0]["id"]:
                        proposals_to_refresh.add(p["id"])

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.delegations): delegations,
                    get_name(SynchronizedData.proposals_to_refresh): list(
                        proposals_to_refresh
                    ),
                },
            )
            return synchronized_data, Event.WRITE_DELEGATIONS
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class WriteDelegationsRound(CollectSameUntilThresholdRound):
    """WriteDelegationsRound"""

    ERROR_PAYLOAD = "ERROR_PAYLOAD"
    MAX_RETRIES_PAYLOAD = "MAX_RETRIES_PAYLOAD"

    payload_class = CollectActiveSnapshotProposalsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            write_data = json.loads(self.most_voted_payload)
            write_data["data"] = cast(
                SynchronizedData, self.synchronized_data
            ).delegations

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.write_data): write_data,
                },
            )
            return (synchronized_data, Event.DONE)
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class CollectActiveTallyProposalsRound(CollectSameUntilThresholdRound):
    """CollectActiveProposals"""

    ERROR_PAYLOAD = "ERROR_PAYLOAD"
    MAX_RETRIES_PAYLOAD = "MAX_RETRIES_PAYLOAD"
    BLOCK_RETRIEVAL_ERROR = "BLOCK_RETRIEVAL_ERROR"

    payload_class = CollectActiveTallyProposalsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            if (
                self.most_voted_payload
                == CollectActiveTallyProposalsRound.ERROR_PAYLOAD
            ):
                tally_api_retries = cast(
                    SynchronizedData, self.synchronized_data
                ).tally_api_retries
                synchronized_data = self.synchronized_data.update(
                    synchronized_data_class=SynchronizedData,
                    **{
                        get_name(SynchronizedData.tally_api_retries): tally_api_retries
                        + 1,
                    },
                )
                return synchronized_data, Event.API_ERROR

            if (
                self.most_voted_payload
                == CollectActiveTallyProposalsRound.MAX_RETRIES_PAYLOAD
            ):
                synchronized_data = self.synchronized_data.update(
                    synchronized_data_class=SynchronizedData,
                    **{
                        get_name(SynchronizedData.votable_proposal_ids): [],
                        get_name(
                            SynchronizedData.snapshot_proposals
                        ): [],  # clean snapshot proposals
                    },
                )
                return synchronized_data, Event.DONE

            if (
                self.most_voted_payload
                == CollectActiveTallyProposalsRound.BLOCK_RETRIEVAL_ERROR
            ):
                return self.synchronized_data, Event.BLOCK_RETRIEVAL_ERROR

            payload = json.loads(self.most_voted_payload)
            proposals_to_refresh = cast(
                SynchronizedData, self.synchronized_data
            ).proposals_to_refresh
            proposals_to_refresh = set(proposals_to_refresh).union(
                payload["proposals_to_refresh"]
            )

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.proposals): payload["proposals"],
                    get_name(SynchronizedData.votable_proposal_ids): payload[
                        "votable_proposal_ids"
                    ],
                    get_name(SynchronizedData.proposals_to_refresh): list(
                        proposals_to_refresh
                    ),
                    get_name(
                        SynchronizedData.snapshot_proposals
                    ): [],  # clean snapshot proposals
                },
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class CollectActiveSnapshotProposalsRound(CollectSameUntilThresholdRound):
    """CollectActiveSnapshotProposals"""

    ERROR_PAYLOAD = "ERROR_PAYLOAD"
    MAX_RETRIES_PAYLOAD = "MAX_RETRIES_PAYLOAD"

    payload_class = CollectActiveSnapshotProposalsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            if self.most_voted_payload == self.ERROR_PAYLOAD:
                snapshot_api_retries = cast(
                    SynchronizedData, self.synchronized_data
                ).snapshot_api_retries
                synchronized_data = self.synchronized_data.update(
                    synchronized_data_class=SynchronizedData,
                    **{
                        get_name(
                            SynchronizedData.snapshot_api_retries
                        ): snapshot_api_retries
                        + 1,
                    },
                )
                return synchronized_data, Event.API_ERROR

            if (
                self.most_voted_payload
                == CollectActiveSnapshotProposalsRound.MAX_RETRIES_PAYLOAD
            ):
                return self.synchronized_data, Event.DONE

            payload = json.loads(self.most_voted_payload)

            snapshot_proposals = cast(
                SynchronizedData, self.synchronized_data
            ).snapshot_proposals
            snapshot_proposals.extend(payload["snapshot_proposals"])
            finished = (
                payload["finished"]
                or len(snapshot_proposals) >= SNAPSHOT_PROPOSAL_TOTAL_LIMIT
            )

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.snapshot_proposals): snapshot_proposals,
                },
            )
            return (
                synchronized_data,
                Event.DONE if finished else Event.REPEAT,
            )
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class FinishedWriteDelegationsRound(DegenerateRound):
    """FinishedWriteDelegationsRound"""


class FinishedProposalRound(DegenerateRound):
    """FinishedProposalRound"""


class ProposalCollectorAbciApp(AbciApp[Event]):
    """ProposalCollectorAbciApp"""

    initial_round_cls: AppState = SynchronizeDelegationsRound
    initial_states: Set[AppState] = {
        SynchronizeDelegationsRound,
        CollectActiveTallyProposalsRound,
    }
    transition_function: AbciAppTransitionFunction = {
        SynchronizeDelegationsRound: {
            Event.DONE: CollectActiveTallyProposalsRound,
            Event.WRITE_DELEGATIONS: WriteDelegationsRound,
            Event.NO_MAJORITY: SynchronizeDelegationsRound,
            Event.ROUND_TIMEOUT: SynchronizeDelegationsRound,
        },
        WriteDelegationsRound: {
            Event.DONE: FinishedWriteDelegationsRound,
            Event.NO_MAJORITY: SynchronizeDelegationsRound,
            Event.ROUND_TIMEOUT: SynchronizeDelegationsRound,
        },
        CollectActiveTallyProposalsRound: {
            Event.DONE: CollectActiveSnapshotProposalsRound,
            Event.API_ERROR: CollectActiveTallyProposalsRound,
            Event.BLOCK_RETRIEVAL_ERROR: CollectActiveTallyProposalsRound,
            Event.NO_MAJORITY: CollectActiveTallyProposalsRound,
            Event.ROUND_TIMEOUT: CollectActiveTallyProposalsRound,
        },
        CollectActiveSnapshotProposalsRound: {
            Event.DONE: FinishedProposalRound,
            Event.REPEAT: CollectActiveSnapshotProposalsRound,
            Event.API_ERROR: CollectActiveSnapshotProposalsRound,
            Event.NO_MAJORITY: CollectActiveSnapshotProposalsRound,
            Event.ROUND_TIMEOUT: CollectActiveSnapshotProposalsRound,
        },
        FinishedWriteDelegationsRound: {},
        FinishedProposalRound: {},
    }
    final_states: Set[AppState] = {
        FinishedProposalRound,
        FinishedWriteDelegationsRound,
    }
    event_to_timeout: EventToTimeout = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    cross_period_persisted_keys: Set[str] = {
        get_name(SynchronizedData.delegations),
        get_name(SynchronizedData.proposals),
        get_name(SynchronizedData.votable_proposal_ids),
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        SynchronizeDelegationsRound: set(),
        CollectActiveTallyProposalsRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedWriteDelegationsRound: set(),
        FinishedProposalRound: {
            get_name(SynchronizedData.delegations),
            get_name(SynchronizedData.proposals),
            get_name(SynchronizedData.votable_proposal_ids),
        },
    }
