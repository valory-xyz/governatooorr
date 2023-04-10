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
    CollectActiveProposalsPayload,
    SynchronizeDelegationsPayload,
)


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
        """Get the proposals."""
        return cast(dict, self.db.get("proposals", {}))

    @property
    def votable_proposal_ids(self) -> list:
        """Get the proposals."""
        return cast(list, self.db.get("votable_proposal_ids", {}))


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

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.delegations): delegations,
                },
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class CollectActiveProposalsRound(CollectSameUntilThresholdRound):
    """CollectActiveProposals"""

    ERROR_PAYLOAD = "ERROR_PAYLOAD"
    BLOCK_RETRIEVAL_ERROR = "BLOCK_RETRIEVAL_ERROR"

    payload_class = CollectActiveProposalsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            if self.most_voted_payload == CollectActiveProposalsRound.ERROR_PAYLOAD:
                return self.synchronized_data, Event.API_ERROR

            if (
                self.most_voted_payload
                == CollectActiveProposalsRound.BLOCK_RETRIEVAL_ERROR
            ):
                return self.synchronized_data, Event.BLOCK_RETRIEVAL_ERROR

            payload = json.loads(self.most_voted_payload)

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.proposals): payload["proposals"],
                    get_name(SynchronizedData.votable_proposal_ids): payload[
                        "votable_proposal_ids"
                    ],
                },
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class FinishedProposalRound(DegenerateRound):
    """FinishedProposalRound"""


class ProposalCollectorAbciApp(AbciApp[Event]):
    """ProposalCollectorAbciApp"""

    initial_round_cls: AppState = SynchronizeDelegationsRound
    initial_states: Set[AppState] = {SynchronizeDelegationsRound}
    transition_function: AbciAppTransitionFunction = {
        SynchronizeDelegationsRound: {
            Event.DONE: CollectActiveProposalsRound,
            Event.NO_MAJORITY: SynchronizeDelegationsRound,
            Event.ROUND_TIMEOUT: SynchronizeDelegationsRound,
        },
        CollectActiveProposalsRound: {
            Event.DONE: FinishedProposalRound,
            Event.API_ERROR: CollectActiveProposalsRound,
            Event.BLOCK_RETRIEVAL_ERROR: CollectActiveProposalsRound,
            Event.NO_MAJORITY: CollectActiveProposalsRound,
            Event.ROUND_TIMEOUT: CollectActiveProposalsRound,
        },
        FinishedProposalRound: {},
    }
    final_states: Set[AppState] = {
        FinishedProposalRound,
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
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedProposalRound: set(),
    }
