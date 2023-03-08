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
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Hashable,
    List,
    Mapping,
    Optional,
    Type,
)

import pytest

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectDifferentUntilThresholdRoundTest,
    BaseCollectSameUntilThresholdRoundTest,
    BaseOnlyKeeperSendsRoundTest,
    BaseRoundTestClass,
)
from packages.valory.skills.proposal_collector.payloads import (
    CollectActiveProposalsPayload,
    SelectProposalPayload,
    SynchronizeDelegationsPayload,
    VerifyDelegationsPayload,
)
from packages.valory.skills.proposal_collector.rounds import (
    AbstractRound,
    CollectActiveProposalsRound,
    Event,
    SelectProposalRound,
    SynchronizeDelegationsRound,
    SynchronizedData,
    VerifyDelegationsRound,
)


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


DUMMY_TOKEN_TO_DELEGATIONS = {
    "dummy_token_address": {
        "dummy_user_address": {
            "delegation_amount": 1000,
            "voting_preference": "good",
        }
    }
}


def get_dummy_verify_delegations_payload_serialized() -> str:
    """Dummy verify_delegations payload"""

    return json.dumps(
        DUMMY_TOKEN_TO_DELEGATIONS,
        sort_keys=True,
    )


@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, BaseTxPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


class BaseProposalCollectorRoundTestClass(BaseCollectSameUntilThresholdRoundTest):
    """Base test class for ProposalCollector rounds."""

    synchronized_data: SynchronizedData
    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def run_test(self, test_case: RoundTestCase, **kwargs: Any) -> None:
        """Run the test"""

        self.synchronized_data.update(**test_case.initial_data)

        test_round = self.round_class(
            synchronized_data=self.synchronized_data,
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=test_case.payloads,
                synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                    **test_case.final_data
                ),
                synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
                most_voted_payload=test_case.most_voted_payload,
                exit_event=test_case.event,
            )
        )


class TestVerifyDelegationsRoundRound(BaseProposalCollectorRoundTestClass):
    """Tests for VerifyDelegationsRound."""

    round_class = VerifyDelegationsRound

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={"new_delegations": []},
                payloads=get_payloads(
                    payload_cls=VerifyDelegationsPayload,
                    data=get_dummy_verify_delegations_payload_serialized(),
                ),
                final_data={
                    "current_token_to_delegations": json.loads(
                        get_dummy_verify_delegations_payload_serialized()
                    ),
                },
                event=Event.DONE,
                most_voted_payload=get_dummy_verify_delegations_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.current_token_to_delegations,
                    lambda _synchronized_data: _synchronized_data.new_delegations,
                    lambda _synchronized_data: _synchronized_data.agent_to_new_delegation_number,
                ],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)
