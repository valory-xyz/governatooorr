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

"""This package contains the tests for rounds of ProposalCollector."""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Union, cast

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    BaseTxPayload,
    CollectDifferentUntilAllRound,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectDifferentUntilAllRoundTest,
    BaseCollectSameUntilThresholdRoundTest,
    CollectSameUntilThresholdRound,
)
from packages.valory.skills.proposal_collector_abci.payloads import (
    CollectActiveProposalsPayload,
    SynchronizeDelegationsPayload,
)
from packages.valory.skills.proposal_collector_abci.rounds import (
    CollectActiveProposalsRound,
    Event,
    SynchronizeDelegationsRound,
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
    data: Union[str, List[str]],
) -> Union[Mapping[str, BaseTxPayload], List[BaseTxPayload]]:
    """Get payloads."""
    if type(data) is list:
        return [
            payload_cls(participant, data[i])
            for i, participant in enumerate(get_participants())
        ]
    else:
        return {
            participant: payload_cls(participant, data)
            for participant in get_participants()
        }


def get_dummy_synchronize_delegations_payload_serialized():
    """Dummy payload"""
    return [
        json.dumps(
            [
                {
                    "user_address": f"user_address_{i}",
                    "token_address": "token_address_1",
                    "voting_preference": f"voting_preference_{i}",
                    "governor_address": f"governor_address_{i}",
                    "delegated_amount": f"delegated_amount_{i}",
                }
            ],
            sort_keys=True,
        )
        for i in range(4)
    ]


def get_dummy_collect_active_proposals_payload_serialized():
    """Dummy payload"""
    return json.dumps(
        {"proposals": [], "votable_proposal_ids": [], "proposals_to_refresh": []},
        sort_keys=True,
    )


class TestSynchronizeDelegationsRoundTest(BaseCollectDifferentUntilAllRoundTest):
    """Base test class for ProposalCollector rounds."""

    synchronized_data: SynchronizedData
    _synchronized_data_class = SynchronizedData
    _event_class = Event
    round_class = SynchronizeDelegationsRound

    def run_test(self, test_case: RoundTestCase) -> None:
        """Run the test"""

        self.synchronized_data.update(**test_case.initial_data)

        test_round = self.round_class(
            synchronized_data=self.synchronized_data,
        )

        self._complete_run(
            self._test_round(
                test_round=cast(CollectDifferentUntilAllRound, test_round),
                round_payloads=test_case.payloads,
                synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                    **test_case.final_data
                ),
                synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
                exit_event=test_case.event,
            )
        )

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={
                    "delegations": [
                        {
                            "user_address": "user_address_0",
                            "token_address": "token_address_1",
                            "voting_preference": "voting_preference_0",
                            "governor_address": "governor_address_0",
                            "delegated_amount": "delegated_amount_0",
                        },
                    ],
                    "proposals": [
                        {
                            "id": "dummy_proposal_id",
                            "governor": {"tokens": [{"id": "token_address_1"}]},
                        },
                    ],
                },
                payloads=get_payloads(
                    payload_cls=SynchronizeDelegationsPayload,
                    data=get_dummy_synchronize_delegations_payload_serialized(),
                ),
                final_data={
                    "delegations": [
                        {
                            "delegated_amount": "delegated_amount_0",
                            "governor_address": "governor_address_0",
                            "token_address": "token_address_1",
                            "user_address": "user_address_0",
                            "voting_preference": "voting_preference_0",
                        },
                        {
                            "delegated_amount": "delegated_amount_1",
                            "governor_address": "governor_address_1",
                            "token_address": "token_address_1",
                            "user_address": "user_address_1",
                            "voting_preference": "voting_preference_1",
                        },
                        {
                            "delegated_amount": "delegated_amount_2",
                            "governor_address": "governor_address_2",
                            "token_address": "token_address_1",
                            "user_address": "user_address_2",
                            "voting_preference": "voting_preference_2",
                        },
                        {
                            "delegated_amount": "delegated_amount_3",
                            "governor_address": "governor_address_3",
                            "token_address": "token_address_1",
                            "user_address": "user_address_3",
                            "voting_preference": "voting_preference_3",
                        },
                    ]
                },
                event=Event.DONE,
                most_voted_payload=None,
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.delegations,
                ],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)


class BaseProposalCollectorRoundTest(BaseCollectSameUntilThresholdRoundTest):
    """Base test class for ProposalCollector rounds."""

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


class TestCollectActiveProposalsRound(BaseProposalCollectorRoundTest):
    """Tests for CollectActiveProposalsRound."""

    round_class = CollectActiveProposalsRound

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CollectActiveProposalsPayload,
                    data=get_dummy_collect_active_proposals_payload_serialized(),
                ),
                final_data={
                    "proposals": json.loads(
                        get_dummy_collect_active_proposals_payload_serialized()
                    )["proposals"],
                    "votable_proposal_ids": json.loads(
                        get_dummy_collect_active_proposals_payload_serialized()
                    )["votable_proposal_ids"],
                },
                event=Event.DONE,
                most_voted_payload=get_dummy_collect_active_proposals_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.proposals,
                    lambda _synchronized_data: _synchronized_data.votable_proposal_ids,
                ],
            ),
            RoundTestCase(
                name="API error",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CollectActiveProposalsPayload,
                    data="ERROR_PAYLOAD",
                ),
                final_data={},
                event=Event.API_ERROR,
                most_voted_payload="ERROR_PAYLOAD",
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="Block retrieval error",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CollectActiveProposalsPayload,
                    data="BLOCK_RETRIEVAL_ERROR",
                ),
                final_data={},
                event=Event.BLOCK_RETRIEVAL_ERROR,
                most_voted_payload="BLOCK_RETRIEVAL_ERROR",
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)
