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
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Hashable,
    List,
    Mapping,
    Optional,
    cast,
)

import pytest

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
    CollectSameUntilThresholdRound,
)
from packages.valory.skills.proposal_voter_abci.payloads import (
    EstablishVotePayload,
    PrepareVoteTransactionPayload,
)
from packages.valory.skills.proposal_voter_abci.rounds import (
    EstablishVoteRound,
    Event,
    PrepareVoteTransactionRound,
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


def get_participants() -> FrozenSet[str]:
    """Participants"""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


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
            "tx_hash": tx_hash,
            "proposals": [],
            "votable_proposal_ids": [],
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
            synchronized_data=self.synchronized_data,
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


class TestPreparehVoteTransactionRoundRound(BaseProposalVoterRoundTest):
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
                    "proposals": json.loads(
                        get_dummy_prepare_vote_tx_payload_serialized()
                    )["proposals"],
                    "votable_proposal_ids": json.loads(
                        get_dummy_prepare_vote_tx_payload_serialized()
                    )["votable_proposal_ids"],
                },
                event=Event.VOTE,
                most_voted_payload=get_dummy_prepare_vote_tx_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.most_voted_tx_hash,
                    lambda _synchronized_data: _synchronized_data.proposals,
                    lambda _synchronized_data: _synchronized_data.votable_proposal_ids,
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
