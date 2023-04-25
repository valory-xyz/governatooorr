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

"""This package contains round behaviours of ProposalCollector."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Type

import pytest
from aea.exceptions import AEAActException
from aea.helpers.transaction.base import State

from packages.valory.connections.openai.connection import (
    PUBLIC_ID as LLM_CONNECTION_PUBLIC_ID,
)
from packages.valory.contracts.delegate.contract import DelegateContract
from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.llm.message import LlmMessage
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.behaviours import (
    make_degenerate_behaviour,
)
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.proposal_voter_abci.behaviours import (
    EstablishVoteBehaviour,
    PrepareVoteTransactionBehaviour,
    ProposalVoterBaseBehaviour,
)
from packages.valory.skills.proposal_voter_abci.models import PendingVote
from packages.valory.skills.proposal_voter_abci.rounds import (
    Event,
    FinishedTransactionPreparationNoVoteRound,
    FinishedTransactionPreparationVoteRound,
    SynchronizedData,
)


DUMMY_GOVERNOR_ADDRESS = "0xEC568fffba86c094cf06b22134B23074DFE2252c"


def get_dummy_proposals(remaining_blocks: int = 1000) -> dict:
    """get_dummy_proposals"""
    return {
        "0": {"votable": False},
        "1": {
            "votable": True,
            "title": "dummy title",
            "description": "dummy description",
            "governor": {
                "id": f"eip155:1:{DUMMY_GOVERNOR_ADDRESS}",
                "type": "AAVE",
                "name": "Aave",
                "tokens": [
                    {
                        "id": "eip155:1/erc20aave:0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9"
                    }
                ],
            },
            "end": {"number": 50},
            "vote": None,
            "remaining_blocks": remaining_blocks,
            "vote_choice": "FOR",
        },
    }


@dataclass
class BehaviourTestCase:
    """BehaviourTestCase"""

    name: str
    initial_data: Dict[str, Any]
    event: Event
    next_behaviour_class: Optional[Type[ProposalVoterBaseBehaviour]] = None


class BaseProposalVoterTest(FSMBehaviourBaseCase):
    """Base test case."""

    path_to_skill = Path(__file__).parent.parent

    behaviour: ProposalVoterBaseBehaviour  # type: ignore
    behaviour_class: Type[ProposalVoterBaseBehaviour]
    next_behaviour_class: Type[ProposalVoterBaseBehaviour]
    synchronized_data: SynchronizedData
    done_event = Event.DONE

    @classmethod
    def setup_class(cls, **kwargs: Any) -> None:
        """setup_class"""
        super().setup_class(**kwargs)
        cls.llm_handler = cls._skill.skill_context.handlers.llm

    def fast_forward(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Fast-forward on initialization"""

        data = data if data is not None else {}
        self.fast_forward_to_behaviour(
            self.behaviour,  # type: ignore
            self.behaviour_class.auto_behaviour_id(),
            SynchronizedData(AbciAppDB(setup_data=AbciAppDB.data_to_lists(data))),
        )
        assert (
            self.behaviour.current_behaviour.auto_behaviour_id()  # type: ignore
            == self.behaviour_class.auto_behaviour_id()
        )

    def complete(self, event: Event) -> None:
        """Complete test"""

        self.behaviour.act_wrapper()
        self.mock_a2a_transaction()
        self._test_done_flag_set()
        self.end_round(done_event=event)
        assert (
            self.behaviour.current_behaviour.auto_behaviour_id()  # type: ignore
            == self.next_behaviour_class.auto_behaviour_id()
        )

    def mock_llm_request(self, request_kwargs: Dict, response_kwargs: Dict) -> None:
        """
        Mock LLM request.

        :param request_kwargs: keyword arguments for request check.
        :param response_kwargs: keyword arguments for mock response.
        """

        self.assert_quantity_in_outbox(1)
        actual_llm_message = self.get_message_from_outbox()
        assert actual_llm_message is not None, "No message in outbox."  # nosec
        has_attributes, error_str = self.message_has_attributes(
            actual_message=actual_llm_message,
            message_type=LlmMessage,
            to=str(LLM_CONNECTION_PUBLIC_ID),
            sender=str(self.skill.skill_context.skill_id),
            **request_kwargs,
        )

        assert has_attributes, error_str  # nosec
        incoming_message = self.build_incoming_message(
            message_type=LlmMessage,
            dialogue_reference=(
                actual_llm_message.dialogue_reference[0],
                "stub",
            ),
            target=actual_llm_message.message_id,
            message_id=-1,
            to=str(self.skill.skill_context.skill_id),
            sender=str(LLM_CONNECTION_PUBLIC_ID),
            **response_kwargs,
        )
        self.llm_handler.handle(incoming_message)
        self.behaviour.act_wrapper()


class TestEstablishVoteBehaviour(BaseProposalVoterTest):
    """Tests EstablishVoteBehaviour"""

    behaviour_class = EstablishVoteBehaviour
    next_behaviour_class = PrepareVoteTransactionBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(
                        proposals=get_dummy_proposals(),
                        delegations=[
                            {
                                "user_address": "dummy_address",
                                "token_address": "eip155:1/erc20aave:0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
                                "voting_preference": "GOOD",
                                "governor_address": "dummy_address",
                                "delegated_amount": 100,
                            }
                        ],
                    ),
                    event=Event.DONE,
                ),
                {},
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        self.mock_llm_request(
            request_kwargs=dict(performative=LlmMessage.Performative.REQUEST),
            response_kwargs=dict(
                performative=LlmMessage.Performative.RESPONSE, value="FOR"
            ),
        )
        self.complete(test_case.event)

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Invalid vote",
                    initial_data=dict(proposals=get_dummy_proposals()),
                    event=Event.DONE,
                ),
                {},
            ),
        ],
    )
    def test_raises(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        with pytest.raises(AEAActException):
            self.fast_forward(test_case.initial_data)
            self.behaviour.act_wrapper()
            self.mock_llm_request(
                request_kwargs=dict(performative=LlmMessage.Performative.REQUEST),
                response_kwargs=dict(
                    performative=LlmMessage.Performative.RESPONSE, value="INVALID"
                ),
            )


class TestPrepareVoteTransactionNoVoteBehaviour(BaseProposalVoterTest):
    """Tests PrepareVoteTransactionBehaviour"""

    behaviour_class = PrepareVoteTransactionBehaviour
    next_behaviour_class = make_degenerate_behaviour(  # type: ignore
        FinishedTransactionPreparationNoVoteRound
    )

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(
                        votable_proposal_ids=["1"],
                        proposals=get_dummy_proposals(),
                    ),
                    event=Event.NO_VOTE,
                ),
                {},
            ),
            (
                BehaviourTestCase(
                    "Just voted",
                    initial_data=dict(
                        final_verification_status=1,
                        votable_proposal_ids=["1"],
                        proposals=get_dummy_proposals(1),
                        safe_contract_address="dummy_safe_contract_address",
                    ),
                    event=Event.NO_VOTE,
                ),
                {},
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.behaviour.context.state.pending_vote = PendingVote("1", "FOR")
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        self.complete(test_case.event)


class TestPrepareVoteTransactionVoteBehaviour(BaseProposalVoterTest):
    """Tests PrepareVoteTransactionBehaviour"""

    behaviour_class = PrepareVoteTransactionBehaviour
    next_behaviour_class = make_degenerate_behaviour(  # type: ignore
        FinishedTransactionPreparationVoteRound
    )

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(
                        votable_proposal_ids=["1"],
                        proposals=get_dummy_proposals(1),
                        safe_contract_address="dummy_safe_contract_address",
                    ),
                    event=Event.VOTE,
                ),
                {},
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""

        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()

        self.mock_contract_api_request(
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
            ),
            contract_id=str(DelegateContract.contract_id),
            response_kwargs=dict(
                performative=ContractApiMessage.Performative.STATE,
                callable="get_cast_vote_data",
                state=State(ledger_id="ethereum", body={"data": b"data"}),
            ),
        )
        self.mock_contract_api_request(
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
            ),
            contract_id=str(GnosisSafeContract.contract_id),
            response_kwargs=dict(
                performative=ContractApiMessage.Performative.STATE,
                callable="get_raw_safe_transaction_hash",
                state=State(
                    ledger_id="ethereum", body={"tx_hash": "0xb0e6add595e00477cf347d09797b156719dc5233283ac76e4efce2a674fe72d9"}  # type: ignore
                ),
            ),
        )

        self.complete(test_case.event)


class TestPrepareVoteTransactionContractErrorBehaviour(BaseProposalVoterTest):
    """Tests PrepareVoteTransactionBehaviour"""

    behaviour_class = PrepareVoteTransactionBehaviour
    next_behaviour_class = PrepareVoteTransactionBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(
                        votable_proposal_ids=["1"],
                        proposals=get_dummy_proposals(1),
                        safe_contract_address="dummy_safe_contract_address",
                    ),
                    event=Event.CONTRACT_ERROR,
                ),
                {
                    "delegate_response_performative": ContractApiMessage.Performative.ERROR,
                    "safe_response_performative": ContractApiMessage.Performative.STATE,
                },
            ),
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(
                        votable_proposal_ids=["1"],
                        proposals=get_dummy_proposals(1),
                        safe_contract_address="dummy_safe_contract_address",
                    ),
                    event=Event.CONTRACT_ERROR,
                ),
                {
                    "delegate_response_performative": ContractApiMessage.Performative.STATE,
                    "safe_response_performative": ContractApiMessage.Performative.ERROR,
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()

        self.mock_contract_api_request(
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
            ),
            contract_id=str(DelegateContract.contract_id),
            response_kwargs=dict(
                performative=kwargs.get("delegate_response_performative"),
                callable="get_cast_vote_data",
                state=State(ledger_id="ethereum", body={"data": b"data"}),
            ),
        )
        if (
            kwargs.get("delegate_response_performative")
            == ContractApiMessage.Performative.STATE
        ):
            self.mock_contract_api_request(
                request_kwargs=dict(
                    performative=ContractApiMessage.Performative.GET_STATE,
                ),
                contract_id=str(GnosisSafeContract.contract_id),
                response_kwargs=dict(
                    performative=kwargs.get("safe_response_performative"),
                    callable="get_raw_safe_transaction_hash",
                    state=State(
                        ledger_id="ethereum", body={"tx_hash": "0xb0e6add595e00477cf347d09797b156719dc5233283ac76e4efce2a674fe72d9"}  # type: ignore
                    ),
                ),
            )

        self.complete(test_case.event)