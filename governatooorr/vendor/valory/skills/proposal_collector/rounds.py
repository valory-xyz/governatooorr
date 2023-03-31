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
from typing import Dict, List, Optional, Set, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AbstractRound,
    AppState,
    BaseSynchronizedData,
    CollectDifferentUntilAllRound,
    CollectSameUntilThresholdRound,
    DegenerateRound,
    EventToTimeout,
    get_name,
)
from packages.valory.skills.proposal_collector.payloads import (
    CollectActiveProposalsPayload,
    SelectProposalPayload,
    SynchronizeDelegationsPayload,
    VerifyDelegationsPayload,
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


class SynchronizedData(BaseSynchronizedData):
    """
    Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def new_delegations(self) -> list:
        """Get the delegations."""
        return cast(list, self.db.get("new_delegations", []))

    @property
    def agent_to_new_delegation_number(self) -> dict:
        """Get the number of delegations each agent has added."""
        return cast(dict, self.db.get("agent_to_new_delegation_number", {}))

    @property
    def current_token_to_delegations(self) -> dict:
        """Get the current delegations."""
        return cast(dict, self.db.get("current_token_to_delegations", {}))

    @property
    def active_proposals(self) -> dict:
        """Get the active proposals."""
        return cast(dict, self.db.get("active_proposals", {}))

    @property
    def selected_proposal_id(self) -> str:
        """Get the selected_proposal_id."""
        return cast(str, self.db.get_strict("selected_proposal_id"))


class SynchronizeDelegationsRound(CollectDifferentUntilAllRound):
    """SynchronizeDelegations"""

    payload_class = SynchronizeDelegationsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""

        if self.collection_threshold_reached:

            all_new_delegations = []
            agent_to_new_delegation_number = {}

            for sender, payload in self.collection.items():
                new_delegations = json.loads(payload.json["new_delegations"])

                # Add this agent's new delegations
                all_new_delegations.extend(new_delegations)

                # Remember how many delegations this agent sent so we can
                # remove them from its local state during next round
                agent_to_new_delegation_number[sender] = len(new_delegations)

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.new_delegations): all_new_delegations,
                    get_name(
                        SynchronizedData.agent_to_new_delegation_number
                    ): agent_to_new_delegation_number,
                }
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class VerifyDelegationsRound(CollectSameUntilThresholdRound):
    """VerifyDelegations"""

    payload_class = VerifyDelegationsPayload
    synchronized_data_class = SynchronizedData

    ERROR_PAYLOAD = "ERROR_PAYLOAD"

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            if self.most_voted_payload == VerifyDelegationsRound.ERROR_PAYLOAD:
                return self.synchronized_data, Event.CONTRACT_ERROR

            new_token_to_delegations = json.loads(self.most_voted_payload)

            current_token_to_delegations = cast(
                SynchronizedData, self.synchronized_data
            ).current_token_to_delegations

            for token_address, delegation_data in new_token_to_delegations.items():
                # Token not in current delegations
                if token_address not in current_token_to_delegations:
                    current_token_to_delegations[token_address] = delegation_data
                    continue

                # Token already in current delegations
                # This will overwrite previous user delegatiosn for the same token
                current_token_to_delegations[token_address].update(delegation_data)

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(
                        SynchronizedData.current_token_to_delegations
                    ): current_token_to_delegations,
                    get_name(
                        SynchronizedData.new_delegations
                    ): [],  # we have already added these into current delegations
                    get_name(
                        SynchronizedData.agent_to_new_delegation_number
                    ): {},  # empty this to avoid deleting already synced delegations multiple times
                }
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

    payload_class = CollectActiveProposalsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            if self.most_voted_payload == CollectActiveProposalsRound.ERROR_PAYLOAD:
                return self.synchronized_data, Event.API_ERROR

            active_proposals = json.loads(self.most_voted_payload)["active_proposals"]

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.active_proposals): active_proposals,
                }
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class SelectProposalRound(CollectSameUntilThresholdRound):
    """SelectProposal"""

    NO_PROPOSAL = "NO_PROPOSAL"

    payload_class = SelectProposalPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:

            proposal_id = self.most_voted_payload

            if proposal_id == SelectProposalRound.NO_PROPOSAL:
                return self.synchronized_data, Event.NO_PROPOSAL

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.selected_proposal_id): proposal_id,
                }
            )
            return synchronized_data, Event.VOTE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class FinishedProposalSelectionDoneRound(DegenerateRound):
    """FinishedProposalSelectionDone"""


class FinishedProposalSelectionVoteRound(DegenerateRound):
    """FinishedProposalSelectionVote"""


class ProposalCollectorAbciApp(AbciApp[Event]):
    """ProposalCollectorAbciApp"""

    initial_round_cls: AppState = SynchronizeDelegationsRound
    initial_states: Set[AppState] = {SynchronizeDelegationsRound, SelectProposalRound}
    transition_function: AbciAppTransitionFunction = {
        SynchronizeDelegationsRound: {
            Event.DONE: VerifyDelegationsRound,
            Event.NO_MAJORITY: SynchronizeDelegationsRound,
            Event.ROUND_TIMEOUT: SynchronizeDelegationsRound,
        },
        VerifyDelegationsRound: {
            Event.DONE: CollectActiveProposalsRound,
            Event.CONTRACT_ERROR: VerifyDelegationsRound,
            Event.NO_MAJORITY: VerifyDelegationsRound,
            Event.ROUND_TIMEOUT: VerifyDelegationsRound,
        },
        CollectActiveProposalsRound: {
            Event.DONE: SelectProposalRound,
            Event.API_ERROR: CollectActiveProposalsRound,
            Event.NO_MAJORITY: CollectActiveProposalsRound,
            Event.ROUND_TIMEOUT: CollectActiveProposalsRound,
        },
        SelectProposalRound: {
            Event.NO_PROPOSAL: FinishedProposalSelectionDoneRound,
            Event.VOTE: FinishedProposalSelectionVoteRound,
            Event.NO_MAJORITY: SelectProposalRound,
            Event.ROUND_TIMEOUT: SelectProposalRound,
        },
        FinishedProposalSelectionDoneRound: {},
        FinishedProposalSelectionVoteRound: {},
    }
    final_states: Set[AppState] = {
        FinishedProposalSelectionDoneRound,
        FinishedProposalSelectionVoteRound,
    }
    event_to_timeout: EventToTimeout = {}
    cross_period_persisted_keys: Set[str] = {
        "current_token_to_delegations",
        "active_proposals",
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        SynchronizeDelegationsRound: set(),
        SelectProposalRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedProposalSelectionDoneRound: set(),
        FinishedProposalSelectionVoteRound: set(),
    }
