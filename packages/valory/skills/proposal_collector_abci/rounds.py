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
    WriteDBPayload,
)


SNAPSHOT_PROPOSAL_TOTAL_LIMIT = 50


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
    WRITE_DB = "write_db"
    REPEAT = "repeat"


class SynchronizedData(BaseSynchronizedData):
    """
    Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def ceramic_db(self) -> dict:
        """Get the delegations and votes."""
        return cast(dict, self.db.get_strict("ceramic_db"))

    @property
    def target_proposals(self) -> dict:
        """Get the active proposals: proposals where the service has voting power"""
        return cast(
            dict, self.db.get("target_proposals", {"tally": {}, "snapshot": {}})
        )

    @property
    def tally_active_proposals(self) -> dict:
        """Get the open proposals: all proposals even if the service does not have voting power"""
        return cast(dict, self.db.get("tally_active_proposals", {}))

    @property
    def n_snapshot_retrieved_proposals(self) -> int:
        """Get the amount of retrieved proposals."""
        return cast(int, self.db.get("n_snapshot_retrieved_proposals", 0))

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

    @property
    def pending_write(self) -> bool:
        """Signal if the DB needs writing."""
        return cast(bool, self.db.get("pending_write", False))


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
            ceramic_db = cast(SynchronizedData, self.synchronized_data).ceramic_db
            delegations = ceramic_db["delegations"]

            new_delegations = []
            for payload in self.collection.values():
                # Add this agent's new delegations
                new_delegations.extend(json.loads(payload.json["new_delegations"]))

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

            event = (
                Event.DONE
                if not new_delegations
                and not cast(SynchronizedData, self.synchronized_data).pending_write
                else Event.WRITE_DB
            )

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.ceramic_db): ceramic_db,
                },
            )
            return synchronized_data, event

        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class WriteDBRound(CollectSameUntilThresholdRound):
    """WriteDBRound"""

    payload_class = WriteDBPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            write_data = json.loads(self.most_voted_payload)
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
            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(
                        SynchronizedData.pending_write
                    ): False,  #  we reset this after writing
                },
            )

            if (
                self.most_voted_payload
                == CollectActiveTallyProposalsRound.ERROR_PAYLOAD
            ):
                tally_api_retries = cast(
                    SynchronizedData, self.synchronized_data
                ).tally_api_retries

                synchronized_data = synchronized_data.update(
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
                return synchronized_data, Event.DONE

            if (
                self.most_voted_payload
                == CollectActiveTallyProposalsRound.BLOCK_RETRIEVAL_ERROR
            ):
                return synchronized_data, Event.BLOCK_RETRIEVAL_ERROR

            payload = json.loads(self.most_voted_payload)

            target_proposals = cast(
                SynchronizedData, self.synchronized_data
            ).target_proposals

            target_proposals["tally"] = payload["tally_target_proposals"]

            synchronized_data = synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.target_proposals): target_proposals,
                    get_name(SynchronizedData.tally_active_proposals): payload[
                        "tally_active_proposals"
                    ],
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

            target_proposals = cast(
                SynchronizedData, self.synchronized_data
            ).target_proposals

            target_proposals["snapshot"] = payload["snapshot_target_proposals"]
            n_retrieved_proposals = payload["n_retrieved_proposals"]

            finished = (
                payload["finished"]
                or n_retrieved_proposals >= SNAPSHOT_PROPOSAL_TOTAL_LIMIT
            )

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.target_proposals): target_proposals,
                    get_name(
                        SynchronizedData.n_snapshot_retrieved_proposals
                    ): n_retrieved_proposals,
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
            Event.WRITE_DB: WriteDBRound,
            Event.NO_MAJORITY: SynchronizeDelegationsRound,
            Event.ROUND_TIMEOUT: SynchronizeDelegationsRound,
        },
        WriteDBRound: {
            Event.DONE: FinishedWriteDelegationsRound,
            Event.NO_MAJORITY: SynchronizeDelegationsRound,
            Event.ROUND_TIMEOUT: SynchronizeDelegationsRound,
        },
        CollectActiveTallyProposalsRound: {
            Event.DONE: CollectActiveSnapshotProposalsRound,
            Event.API_ERROR: CollectActiveTallyProposalsRound,
            Event.BLOCK_RETRIEVAL_ERROR: CollectActiveTallyProposalsRound,
            Event.NO_MAJORITY: CollectActiveTallyProposalsRound,
            Event.ROUND_TIMEOUT: CollectActiveSnapshotProposalsRound,
        },
        CollectActiveSnapshotProposalsRound: {
            Event.DONE: FinishedProposalRound,
            Event.REPEAT: CollectActiveSnapshotProposalsRound,
            Event.API_ERROR: CollectActiveSnapshotProposalsRound,
            Event.NO_MAJORITY: CollectActiveSnapshotProposalsRound,
            Event.ROUND_TIMEOUT: FinishedProposalRound,
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
        get_name(SynchronizedData.ceramic_db),
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        SynchronizeDelegationsRound: set(),
        CollectActiveTallyProposalsRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedWriteDelegationsRound: set(),
        FinishedProposalRound: {
            get_name(SynchronizedData.ceramic_db),
            get_name(SynchronizedData.target_proposals),
            get_name(SynchronizedData.tally_active_proposals),
        },
    }
