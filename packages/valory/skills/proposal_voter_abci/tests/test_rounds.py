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

"""This package contains the tests for rounds of GenericScoring."""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Hashable, List, Mapping, Optional, cast
from unittest import mock

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    AbstractRound,
    BaseTxPayload,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
    BaseOnlyKeeperSendsRoundTest,
    CollectSameUntilThresholdRound,
)
from packages.valory.skills.proposal_voter_abci.payloads import (
    EstablishVotePayload,
    PostVoteDecisionMakingPayload,
    PrepareVoteTransactionPayload,
    SnapshotAPISendPayload,
    SnapshotAPISendRandomnessPayload,
    SnapshotAPISendSelectKeeperPayload,
)
from packages.valory.skills.proposal_voter_abci.rounds import (
    EstablishVoteRound,
    Event,
    PostVoteDecisionMakingRound,
    PrepareVoteTransactionRound,
    SnapshotAPISendRandomnessRound,
    SnapshotAPISendRound,
    SnapshotAPISendSelectKeeperRound,
    SynchronizedData,
)


@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, BaseTxPayload]
    final_data: Dict[str, Any]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


def get_participants() -> List[str]:
    """Participants"""
    return [f"agent_{i}" for i in range(MAX_PARTICIPANTS)]


def get_payloads(
    payload_cls: BaseTxPayload,
    data: Optional[str],
) -> Mapping[str, BaseTxPayload]:
    """Get payloads."""
    return {
        participant: payload_cls(participant, data)
        for participant in get_participants()
    }


def get_dummy_establish_vote_payload_serialized():
    """Dummy payload"""
    return json.dumps(
        {"proposals": [], "votable_snapshot_proposals": []}, sort_keys=True
    )


def get_dummy_prepare_vote_tx_payload_serialized(
    no_vote: bool = False, error: bool = False
):
    """Dummy payload"""
    tx_hash = "tx_hash"
    if no_vote:
        tx_hash = "NO_VOTE"
    if error:
        tx_hash = "ERROR"
    return json.dumps(
        {
            "target_proposals": {},
            "expiring_proposals": {},
            "ceramic_db": {},
            "pending_write": True,
            "tx_hash": tx_hash,
            "snapshot_api_data": {},
        },
        sort_keys=True,
    )


class BaseProposalVoterRoundTest(BaseCollectSameUntilThresholdRoundTest):
    """Base test class for ProposalVoter rounds."""

    synchronized_data: SynchronizedData
    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def run_test(self, test_case: RoundTestCase) -> None:
        """Run the test"""

        self.synchronized_data.update(**test_case.initial_data)

        test_round = self.round_class(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=cast(CollectSameUntilThresholdRound, test_round),
                round_payloads=test_case.payloads,
                synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                    **test_case.final_data
                ),
                synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
                most_voted_payload=test_case.most_voted_payload,
                exit_event=test_case.event,
            )
        )


class TestEstablishVoteRoundRound(BaseProposalVoterRoundTest):
    """Tests for EstablishVoteRound."""

    round_class = EstablishVoteRound

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=EstablishVotePayload,
                    data=get_dummy_establish_vote_payload_serialized(),
                ),
                final_data={
                    "proposals": json.loads(
                        get_dummy_establish_vote_payload_serialized()
                    )["proposals"],
                },
                event=Event.DONE,
                most_voted_payload=get_dummy_establish_vote_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.proposals,
                ],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)


class TestPrepareVoteTransactionRoundRound(BaseProposalVoterRoundTest):
    """Tests for PrepareVoteTransactionRound."""

    round_class = PrepareVoteTransactionRound

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path: vote",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=PrepareVoteTransactionPayload,
                    data=get_dummy_prepare_vote_tx_payload_serialized(),
                ),
                final_data={
                    "most_voted_tx_hash": json.loads(
                        get_dummy_prepare_vote_tx_payload_serialized()
                    )["tx_hash"],
                    "target_proposals": json.loads(
                        get_dummy_prepare_vote_tx_payload_serialized()
                    )["target_proposals"],
                },
                event=Event.VOTE,
                most_voted_payload=get_dummy_prepare_vote_tx_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.most_voted_tx_hash,
                    lambda _synchronized_data: _synchronized_data.target_proposals,
                ],
            ),
            RoundTestCase(
                name="Happy path: no vote",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=PrepareVoteTransactionPayload,
                    data=get_dummy_prepare_vote_tx_payload_serialized(no_vote=True),
                ),
                final_data={},
                event=Event.NO_VOTE,
                most_voted_payload=get_dummy_prepare_vote_tx_payload_serialized(
                    no_vote=True
                ),
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="Error",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=PrepareVoteTransactionPayload,
                    data=get_dummy_prepare_vote_tx_payload_serialized(error=True),
                ),
                final_data={},
                event=Event.CONTRACT_ERROR,
                most_voted_payload=get_dummy_prepare_vote_tx_payload_serialized(
                    error=True
                ),
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)


def get_dummy_retrieve_signature_payload_serialized(error: bool = False):
    """get_dummy_retrieve_signature_payload_serialized"""
    return json.dumps(
        {"snapshot_api_data_signature": None if error else "dummy_signature"}
    )


class TestRetrieveSignatureTransactionRoundRound(BaseProposalVoterRoundTest):
    """Tests for PostVoteDecisionMakingRound."""

    round_class = PostVoteDecisionMakingRound

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=PostVoteDecisionMakingPayload,
                    data=get_dummy_retrieve_signature_payload_serialized(),
                ),
                final_data={
                    "snapshot_api_data_signature": "dummy_signature",
                },
                event=Event.DONE,
                most_voted_payload=get_dummy_retrieve_signature_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.snapshot_api_data_signature
                ],
            ),
            RoundTestCase(
                name="Skip payload",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=PostVoteDecisionMakingPayload,
                    data="skip_payload",
                ),
                final_data={},
                event=Event.DONE,
                most_voted_payload="skip_payload",
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="No signature",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=PostVoteDecisionMakingPayload,
                    data=get_dummy_retrieve_signature_payload_serialized(True),
                ),
                final_data={},
                event=Event.RETRIEVAL_ERROR,
                most_voted_payload=get_dummy_retrieve_signature_payload_serialized(
                    True
                ),
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)


# -----------------------------------------------------------------------
# Randomness and select keeper tests are ported from Hello World abci app
# -----------------------------------------------------------------------

RANDOMNESS: str = "d1c29dce46f979f9748210d24bce4eae8be91272f5ca1a6aea2832d3dd676f51"


class BaseRoundTestClass:
    """Base test class for Rounds."""

    synchronized_data: SynchronizedData
    participants: List[str]

    @classmethod
    def setup(
        cls,
    ) -> None:
        """Setup the test class."""

        cls.participants = get_participants()
        cls.synchronized_data = SynchronizedData(
            AbciAppDB(
                setup_data=dict(
                    participants=[cls.participants],
                    all_participants=[cls.participants],
                    consensus_threshold=[3],
                ),
            )
        )

    def _test_no_majority_event(self, round_obj: AbstractRound) -> None:
        """Test the NO_MAJORITY event."""
        with mock.patch.object(round_obj, "is_majority_possible", return_value=False):
            result = round_obj.end_block()
            assert result is not None
            synchronized_data, event = result
            assert event == Event.NO_MAJORITY


class TestCollectRandomnessRound(BaseRoundTestClass):
    """Tests for CollectRandomnessRound."""

    def test_run(
        self,
    ) -> None:
        """Run tests."""

        test_round = SnapshotAPISendRandomnessRound(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )
        first_payload, *payloads = [
            SnapshotAPISendRandomnessPayload(
                sender=participant, randomness=RANDOMNESS, round_id=0
            )
            for participant in self.participants
        ]

        test_round.process_payload(first_payload)
        assert test_round.collection[first_payload.sender] == first_payload
        assert test_round.end_block() is None

        self._test_no_majority_event(test_round)

        for payload in payloads:
            test_round.process_payload(payload)

        actual_next_behaviour = self.synchronized_data.update(
            participant_to_randomness=test_round.serialized_collection,
            most_voted_randomness=test_round.most_voted_payload,
        )

        res = test_round.end_block()
        assert res is not None
        synchronized_data, event = res
        assert all(
            [
                key
                in cast(SynchronizedData, synchronized_data).participant_to_randomness
                for key in cast(
                    SynchronizedData, actual_next_behaviour
                ).participant_to_randomness
            ]
        )
        assert event == Event.DONE


class TestSelectKeeperRound(BaseRoundTestClass):
    """Tests for SelectKeeperRound."""

    def test_run(
        self,
    ) -> None:
        """Run tests."""

        test_round = SnapshotAPISendSelectKeeperRound(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        first_payload, *payloads = [
            SnapshotAPISendSelectKeeperPayload(sender=participant, keeper="keeper")
            for participant in self.participants
        ]

        test_round.process_payload(first_payload)
        assert test_round.collection[first_payload.sender] == first_payload
        assert test_round.end_block() is None

        self._test_no_majority_event(test_round)

        for payload in payloads:
            test_round.process_payload(payload)

        actual_next_behaviour = self.synchronized_data.update(
            participant_to_selection=test_round.serialized_collection,
            most_voted_keeper_address=test_round.most_voted_payload,
        )

        res = test_round.end_block()
        assert res is not None
        synchronized_data, event = res
        assert all(
            [
                key
                in cast(SynchronizedData, synchronized_data).participant_to_selection
                for key in cast(
                    SynchronizedData, actual_next_behaviour
                ).participant_to_selection
            ]
        )
        assert event == Event.DONE


class TestSnapshotAPISendRound(BaseOnlyKeeperSendsRoundTest):
    """Test SnapshotAPISendRound."""

    _synchronized_data_class = SynchronizedData
    _event_class = Event
    _round_class = SnapshotAPISendRound

    @pytest.mark.parametrize(
        "payload_str, exit_event",
        (
            (
                json.dumps(
                    {
                        "ceramic_db": {},
                        "pending_write": [],
                    }
                ),
                Event.DONE,
            ),
        ),
    )
    def test_round(
        self,
        payload_str: str,
        exit_event: Event,
    ) -> None:
        """Runs tests."""

        sender = "agent_0-----------------------------------"

        self.participants = frozenset([f"agent_{i}" + "-" * 35 for i in range(4)])
        self.synchronized_data = cast(
            SynchronizedData,
            self.synchronized_data.update(
                participants=[f"agent_{i}" + "-" * 35 for i in range(4)],
                keeper=sender,
                most_voted_keeper_address=sender,
            ),
        )

        test_round = self._round_class(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                keeper_payloads=SnapshotAPISendPayload(
                    sender=sender,
                    content=payload_str,
                ),
                synchronized_data_update_fn=lambda _synchronized_data, _: _synchronized_data.update(
                    keeper=sender,
                ),
                synchronized_data_attr_checks=[],
                exit_event=exit_event,
            )
        )
