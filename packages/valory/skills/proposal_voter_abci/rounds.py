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

"""This package contains the rounds of ProposalVoterAbciApp."""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    DegenerateRound,
    EventToTimeout,
    OnlyKeeperSendsRound,
    get_name,
)
from packages.valory.skills.proposal_voter_abci.payloads import (
    DecisionMakingPayload,
    EstablishVotePayload,
    MechCallCheckPayload,
    PostTxDecisionMakingPayload,
    PostVoteDecisionMakingPayload,
    PrepareMechRequestPayload,
    PrepareVoteTransactionsPayload,
    SnapshotAPISendPayload,
    SnapshotAPISendRandomnessPayload,
    SnapshotAPISendSelectKeeperPayload,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    VerificationStatus,
)


MAX_VOTE_RETRIES = 3


@dataclass
class MechMetadata:
    """A Mech's metadata."""

    prompt: str
    tool: str
    nonce: str


@dataclass
class MechRequest:
    """A Mech's request."""

    data: str = ""
    requestId: int = 0


@dataclass
class MechInteractionResponse(MechRequest):
    """A structure for the response of a mech interaction task."""

    nonce: str = ""
    result: Optional[str] = None
    error: str = "Unknown"

    def retries_exceeded(self) -> None:
        """Set an incorrect format response."""
        self.error = "Retries were exceeded while trying to get the mech's response."

    def incorrect_format(self, res: Any) -> None:
        """Set an incorrect format response."""
        self.error = f"The response's format was unexpected: {res}"


class Event(Enum):
    """ProposalVoterAbciApp Events"""

    NO_MAJORITY = "no_majority"
    ROUND_TIMEOUT = "round_timeout"
    DONE = "done"
    VOTE = "vote"
    NO_VOTE = "no_vote"
    SKIP_CALL = "skip_call"
    SNAPSHOT_CALL = "snapshot_call"
    NO_ALLOWANCE = "no_allowance"
    POST_REQUEST_TX = "post_request_tx"
    MECH_REQUEST = "mech_request"
    POST_VOTE = "post_vote"
    ESTABLISH_VOTE = "establish_vote"


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
        """Get the active proposals."""
        return cast(dict, self.db.get("target_proposals", {}))

    @property
    def expiring_proposals(self) -> dict:
        """Get the expiring_proposals."""
        return cast(
            dict, self.db.get("expiring_proposals", {"tally": {}, "snapshot": {}})
        )

    @property
    def pending_transactions(self) -> dict:
        """Get the snapshot_api_data."""
        return cast(
            dict, self.db.get("pending_transactions", {"tally": {}, "snapshot": {}})
        )

    @property
    def most_voted_tx_hash(self) -> str:
        """Get the most_voted_tx_hash."""
        return cast(str, self.db.get_strict("most_voted_tx_hash"))

    @property
    def most_voted_randomness_round(self) -> int:  # pragma: no cover
        """Get the most voted randomness round."""
        round_ = self.db.get_strict("most_voted_randomness_round")
        return cast(int, round_)

    @property
    def final_tx_hash(self) -> str:
        """Get the verified tx hash."""
        return cast(str, self.db.get_strict("final_tx_hash"))

    @property
    def snapshot_api_retries(self) -> int:
        """Get the amount of API call retries."""
        return cast(int, self.db.get("snapshot_api_retries", 0))

    @property
    def selected_proposal(self) -> dict:
        """Get the selected proposal."""
        return cast(dict, self.db.get_strict("selected_proposal"))

    @property
    def pending_write(self) -> bool:
        """Signal if the DB needs writing."""
        return cast(bool, self.db.get("pending_write", False))

    @property
    def is_vote_verified(self) -> bool:
        """Check if the vote has been verified."""
        status = self.db.get("final_verification_status", None)
        return status == VerificationStatus.VERIFIED.value

    @property
    def current_path(self) -> str:
        """Get the current execution path."""
        return cast(str, self.db.get_strict("current_path"))

    @property
    def mech_requests(self) -> List[MechMetadata]:
        """Get the mech requests."""
        serialized = self.db.get("mech_requests", "[]")
        requests = json.loads(serialized)
        return [MechMetadata(**metadata_item) for metadata_item in requests]

    @property
    def mech_responses(self) -> List[MechInteractionResponse]:
        """Get the mech responses."""
        serialized = self.db.get("mech_responses", "[]")
        responses = json.loads(serialized)
        return [MechInteractionResponse(**response_item) for response_item in responses]


class MechCallCheckRound(CollectSameUntilThresholdRound):
    """OpenAICallCheckRound"""

    payload_class = MechCallCheckPayload
    synchronized_data_class = SynchronizedData

    CALLS_REMAINING = "CALLS_REMAINING"

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            # Happy path
            if self.most_voted_payload == self.CALLS_REMAINING:
                return self.synchronized_data, Event.DONE

            # No allowance
            return self.synchronized_data, Event.NO_ALLOWANCE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class PrepareMechRequestRound(CollectSameUntilThresholdRound):
    """PrepareMechRequestRound"""

    payload_class = PrepareMechRequestPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            payload = json.loads(self.most_voted_payload)

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.expiring_proposals): payload[
                        "expiring_proposals"
                    ],
                    get_name(SynchronizedData.mech_requests): payload["mech_requests"],
                    get_name(SynchronizedData.current_path): "establish_vote",
                },
            )

            event = Event.DONE if not payload["mech_requests"] else Event.MECH_REQUEST
            return synchronized_data, event
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class EstablishVoteRound(CollectSameUntilThresholdRound):
    """EstablishVoteRound"""

    payload_class = EstablishVotePayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            payload = json.loads(self.most_voted_payload)
            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.expiring_proposals): payload[
                        "expiring_proposals"
                    ],
                },
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class PrepareVoteTransactionsRound(CollectSameUntilThresholdRound):
    """EstablishVoteRound"""

    payload_class = PrepareVoteTransactionsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            payload = json.loads(self.most_voted_payload)
            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.pending_transactions): payload[
                        "pending_transactions"
                    ],
                },
            )
            return synchronized_data, Event.DONE
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class DecisionMakingRound(CollectSameUntilThresholdRound):
    """DecisionMakingRound"""

    payload_class = DecisionMakingPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            payload = json.loads(self.most_voted_payload)

            if "selected_proposal" not in payload:
                synchronized_data = self.synchronized_data.update(
                    synchronized_data_class=SynchronizedData,
                    **{
                        get_name(SynchronizedData.pending_transactions): payload[
                            "pending_transactions"
                        ],
                    },
                )
                return synchronized_data, Event.NO_VOTE

            selected_proposal = payload["selected_proposal"]
            tx_hash = cast(
                SynchronizedData, self.synchronized_data
            ).pending_transactions[selected_proposal["platform"]][
                selected_proposal["proposal_id"]
            ][
                "tx_hash"
            ]

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(SynchronizedData.most_voted_tx_hash): tx_hash,
                    get_name(SynchronizedData.selected_proposal): payload[
                        "selected_proposal"
                    ],
                    get_name(SynchronizedData.pending_transactions): payload[
                        "pending_transactions"
                    ],
                    get_name(SynchronizedData.current_path): "post_vote",
                },
            )
            return synchronized_data, Event.VOTE

        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class PostVoteDecisionMakingRound(CollectSameUntilThresholdRound):
    """PostVoteDecisionMakingRound"""

    payload_class = PostVoteDecisionMakingPayload
    synchronized_data_class = SynchronizedData

    SKIP_PAYLOAD = "skip_payload"
    CALL_PAYLOAD = "call_payload"
    RETRY_PAYLOAD = "retry_payload"

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            synchronized_data = cast(SynchronizedData, self.synchronized_data)
            selected_proposal = synchronized_data.selected_proposal
            pending_transactions = synchronized_data.pending_transactions
            ceramic_db = synchronized_data.ceramic_db

            if self.most_voted_payload == self.RETRY_PAYLOAD:
                # Increase retries
                pending_transactions[selected_proposal["platform"]][
                    selected_proposal["proposal_id"]
                ]["retries"] += 1

                synchronized_data = self.synchronized_data.update(
                    synchronized_data_class=SynchronizedData,
                    **{
                        get_name(
                            SynchronizedData.pending_transactions
                        ): pending_transactions,
                    },
                )
                return synchronized_data, Event.SKIP_CALL

            if self.most_voted_payload == self.CALL_PAYLOAD:
                return synchronized_data, Event.SNAPSHOT_CALL

            # The vote has already succeeded, move it into the vote history
            ceramic_db["vote_data"][selected_proposal["platform"]].append(
                selected_proposal["proposal_id"]
            )
            del pending_transactions[selected_proposal["platform"]][
                selected_proposal["proposal_id"]
            ]

            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=SynchronizedData,
                **{
                    get_name(
                        SynchronizedData.pending_transactions
                    ): pending_transactions,
                    get_name(SynchronizedData.ceramic_db): ceramic_db,
                    get_name(SynchronizedData.pending_write): True,
                },
            )

            return synchronized_data, Event.SKIP_CALL

        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class SnapshotAPISendRandomnessRound(CollectSameUntilThresholdRound):
    """A round for generating randomness"""

    payload_class = SnapshotAPISendRandomnessPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_randomness)
    selection_key = (
        get_name(SynchronizedData.most_voted_randomness_round),
        get_name(SynchronizedData.most_voted_randomness),
    )


class SnapshotAPISendSelectKeeperRound(CollectSameUntilThresholdRound):
    """A round in which a keeper is selected for transaction submission"""

    payload_class = SnapshotAPISendSelectKeeperPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_selection)
    selection_key = get_name(SynchronizedData.most_voted_keeper_address)


class SnapshotAPISendRound(OnlyKeeperSendsRound):
    """StreamWriteRound"""

    payload_class = SnapshotAPISendPayload
    synchronized_data_class = SynchronizedData

    def end_block(
        self,
    ) -> Optional[
        Tuple[BaseSynchronizedData, Enum]
    ]:  # pylint: disable=too-many-return-statements
        """Process the end of the block."""
        if self.keeper_payload is None:
            return None

        synchronized_data = cast(SynchronizedData, self.synchronized_data)
        selected_proposal = synchronized_data.selected_proposal
        pending_transactions = synchronized_data.pending_transactions
        ceramic_db = synchronized_data.ceramic_db
        pending_write = synchronized_data.pending_write

        # We only move the vote into the history if the call succeeded
        if cast(SnapshotAPISendPayload, self.keeper_payload).success:
            ceramic_db["vote_data"][selected_proposal["platform"]].append(
                selected_proposal["proposal_id"]
            )
            pending_write = True

        # We remove the vote from pending in any case. If the call has failed, we will retry in the future.
        del pending_transactions[selected_proposal["platform"]][
            selected_proposal["proposal_id"]
        ]

        synchronized_data = self.synchronized_data.update(
            synchronized_data_class=SynchronizedData,
            **{
                get_name(SynchronizedData.pending_transactions): pending_transactions,
                get_name(SynchronizedData.ceramic_db): ceramic_db,
                get_name(SynchronizedData.pending_write): pending_write,
            },
        )
        return synchronized_data, Event.DONE


class PostTxDecisionMakingRound(CollectSameUntilThresholdRound):
    """PostTxDecisionMakingRound"""

    payload_class = PostTxDecisionMakingPayload
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Event]]:
        """Process the end of the block."""
        if self.threshold_reached:
            # Event.ESTABLISH_VOTE, Event.POST_VOTE
            event = Event(self.most_voted_payload)
            return self.synchronized_data, event

        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY
        return None


class FinishedTransactionPreparationVoteRound(DegenerateRound):
    """FinishedTransactionPreparationRound"""


class FinishedTransactionPreparationNoVoteRound(DegenerateRound):
    """FinishedTransactionPreparationRound"""


class FinishedMechRequestPreparationRound(DegenerateRound):
    """FinishedMechRequestPreparationRound"""


class FinishedToMechResponseRound(DegenerateRound):
    """FinishedToMechResponseRound"""


class ProposalVoterAbciApp(AbciApp[Event]):
    """ProposalVoterAbciApp"""

    initial_round_cls: AppState = MechCallCheckRound
    initial_states: Set[AppState] = {
        MechCallCheckRound,
        PostTxDecisionMakingRound,
        EstablishVoteRound,
    }
    transition_function: AbciAppTransitionFunction = {
        MechCallCheckRound: {
            Event.DONE: PrepareMechRequestRound,
            Event.NO_ALLOWANCE: FinishedTransactionPreparationNoVoteRound,
            Event.NO_MAJORITY: MechCallCheckRound,
            Event.ROUND_TIMEOUT: MechCallCheckRound,
        },
        PrepareMechRequestRound: {
            Event.DONE: EstablishVoteRound,
            Event.MECH_REQUEST: FinishedMechRequestPreparationRound,
            Event.NO_MAJORITY: PrepareMechRequestRound,
            Event.ROUND_TIMEOUT: PrepareMechRequestRound,
        },
        PostTxDecisionMakingRound: {
            Event.POST_VOTE: PostVoteDecisionMakingRound,
            Event.ESTABLISH_VOTE: FinishedToMechResponseRound,
            Event.NO_MAJORITY: PostTxDecisionMakingRound,
            Event.ROUND_TIMEOUT: PostTxDecisionMakingRound,
        },
        EstablishVoteRound: {
            Event.DONE: PrepareVoteTransactionsRound,
            Event.NO_MAJORITY: EstablishVoteRound,
            Event.ROUND_TIMEOUT: EstablishVoteRound,
        },
        DecisionMakingRound: {
            Event.NO_VOTE: FinishedTransactionPreparationNoVoteRound,
            Event.VOTE: FinishedTransactionPreparationVoteRound,
            Event.NO_MAJORITY: DecisionMakingRound,
            Event.ROUND_TIMEOUT: DecisionMakingRound,
        },
        PrepareVoteTransactionsRound: {
            Event.DONE: DecisionMakingRound,
            Event.NO_MAJORITY: PrepareVoteTransactionsRound,
            Event.ROUND_TIMEOUT: PrepareVoteTransactionsRound,
        },
        PostVoteDecisionMakingRound: {
            Event.SKIP_CALL: DecisionMakingRound,
            Event.SNAPSHOT_CALL: SnapshotAPISendRandomnessRound,
            Event.NO_MAJORITY: PostVoteDecisionMakingRound,
            Event.ROUND_TIMEOUT: PostVoteDecisionMakingRound,
        },
        SnapshotAPISendRandomnessRound: {
            Event.DONE: SnapshotAPISendSelectKeeperRound,
            Event.NO_MAJORITY: SnapshotAPISendRandomnessRound,
            Event.ROUND_TIMEOUT: SnapshotAPISendRandomnessRound,
        },
        SnapshotAPISendSelectKeeperRound: {
            Event.DONE: SnapshotAPISendRound,
            Event.NO_MAJORITY: SnapshotAPISendRandomnessRound,
            Event.ROUND_TIMEOUT: SnapshotAPISendRandomnessRound,
        },
        SnapshotAPISendRound: {
            Event.DONE: DecisionMakingRound,
            Event.ROUND_TIMEOUT: SnapshotAPISendRandomnessRound,
        },
        FinishedTransactionPreparationNoVoteRound: {},
        FinishedTransactionPreparationVoteRound: {},
        FinishedMechRequestPreparationRound: {},
        FinishedToMechResponseRound: {},
    }
    final_states: Set[AppState] = {
        FinishedTransactionPreparationVoteRound,
        FinishedTransactionPreparationNoVoteRound,
        FinishedMechRequestPreparationRound,
        FinishedToMechResponseRound,
    }
    event_to_timeout: EventToTimeout = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    cross_period_persisted_keys: Set[str] = {
        get_name(SynchronizedData.ceramic_db),
        get_name(SynchronizedData.pending_write),
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        MechCallCheckRound: set(),
        PostTxDecisionMakingRound: set(),
        EstablishVoteRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedTransactionPreparationVoteRound: {
            get_name(SynchronizedData.most_voted_tx_hash)
        },
        FinishedTransactionPreparationNoVoteRound: set(),
        FinishedMechRequestPreparationRound: set(),
        FinishedToMechResponseRound: set(),
    }
