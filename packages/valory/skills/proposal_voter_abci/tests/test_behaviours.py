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

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Type, cast

import pytest
from aea.exceptions import AEAActException
from aea.helpers.transaction.base import State

from packages.valory.connections.openai.connection import (
    PUBLIC_ID as LLM_CONNECTION_PUBLIC_ID,
)
from packages.valory.contracts.delegate.contract import DelegateContract
from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.contracts.sign_message_lib.contract import SignMessageLibContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.llm.message import LlmMessage
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.behaviours import (
    make_degenerate_behaviour,
)
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.abstract_round_abci.test_tools.common import (
    BaseRandomnessBehaviourTest,
)
from packages.valory.skills.proposal_voter_abci.behaviours import (
    EstablishVoteBehaviour,
    PrepareVoteTransactionBehaviour,
    ProposalVoterBaseBehaviour,
    SnapshotAPISendBehaviour,
    SnapshotAPISendRandomnessBehaviour,
    SnapshotAPISendSelectKeeperBehaviour,
    PostVoteDecisionMakingBehaviour,
)
from packages.valory.skills.proposal_voter_abci.models import PendingVote, SharedState
from packages.valory.skills.proposal_voter_abci.rounds import (
    Event,
    FinishedTransactionPreparationNoVoteRound,
    FinishedTransactionPreparationVoteRound,
    SynchronizedData,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    VerificationStatus,
)


PACKAGE_DIR = Path(__file__).parent.parent

DUMMY_GOVERNOR_ADDRESS = "0xEC568fffba86c094cf06b22134B23074DFE2252c"
SNAPSHOT_VOTE_ENDPOINT = "https://relayer.snapshot.org/"

NULL_ADDRESS = "0x0000000000000000000000000000000000000000"


def get_dummy_proposals(remaining_blocks: int = 1000) -> dict:
    """get_dummy_proposals"""
    return {
        "0": {
            "votable": False,
            "remaining_blocks": remaining_blocks,
        },
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
        "2": {
            "votable": True,
            "remaining_blocks": remaining_blocks,
            "governor": {
                "id": f"eip155:1:{DUMMY_GOVERNOR_ADDRESS}",
                "type": "AAVE",
                "name": "Aave",
                "tokens": [
                    {
                        "id": "eip155:1/erc20aave:0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaAA"
                    }
                ],
            },
        },
    }


def get_dummy_snapshot_proposals(include_voted=False) -> dict:
    """get_dummy_proposals"""
    proposals = {
        "0x108a9e597560c4f249cd8be23acd409059fcd17bb2290d69a550ac2232676e7d": {
            "id": "0x108a9e597560c4f249cd8be23acd409059fcd17bb2290d69a550ac2232676e7d",
            "title": "dummy_title",
            "body": "dummy_body",
            "space": {
                "id": "0x108a9e597560c4f249cd8be23acd409059fcd17bb2290d69a550ac2232676e7d",
                "name": "dummy_space_id",
            },
            "choice": 1,
            "strategies": [{"name": "erc20-balance-of"}],
            "end": 1000,
            "choices": ["0", "1", "2"],
            "remaining_seconds": 100,
        },
    }

    return proposals


def get_dummy_delegations() -> list:
    """get_dummy_delegations"""
    return [
        {
            "user_address": "dummy_address",
            "token_address": "eip155:1/erc20aave:0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
            "voting_preference": "GOOD",
            "governor_address": "dummy_address",
            "delegated_amount": 100,
        }
    ]


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

    def complete(self, event: Event, sends: bool = True) -> None:
        """Complete test"""

        self.behaviour.act_wrapper()
        if sends:
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
                        snapshot_proposals=[],
                        delegations=get_dummy_delegations(),
                        tally_proposals_to_refresh=["0", "1", "2"],
                    ),
                    event=Event.DONE,
                ),
                {},
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        time_in_future = datetime.datetime.now() + datetime.timedelta(hours=10)
        state = cast(SharedState, self._skill.skill_context.state)
        state.round_sequence._last_round_transition_timestamp = time_in_future
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
                    initial_data=dict(
                        proposals=get_dummy_proposals(),
                        delegations=get_dummy_delegations(),
                        tally_proposals_to_refresh=["1"],
                    ),
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


class TestEstablishVoteSnapshotBehaviour(BaseProposalVoterTest):
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
                        target_proposals={
                            "tally": get_dummy_proposals(),
                            "snapshot": get_dummy_snapshot_proposals(),
                        },
                        delegations=get_dummy_delegations(),
                        safe_contract_address=NULL_ADDRESS,
                    ),
                    event=Event.DONE,
                ),
                {
                    "http_code": 200,
                    "response_body": {"data": {"vp": {"vp": 1}}},
                    "vote": "0",
                },
            ),
            (
                BehaviourTestCase(
                    "Error: code 400",
                    initial_data=dict(
                        proposals=get_dummy_proposals(),
                        snapshot_proposals=get_dummy_snapshot_proposals(),
                        delegations=get_dummy_delegations(),
                        tally_proposals_to_refresh=[],
                        safe_contract_address=NULL_ADDRESS,
                    ),
                    event=Event.DONE,
                ),
                {
                    "http_code": 400,
                    "response_body": {"data": {"vp": {"vp": 1}}},
                    "vote": "0",
                },
            ),
            (
                BehaviourTestCase(
                    "Error: errors in response",
                    initial_data=dict(
                        proposals=get_dummy_proposals(),
                        snapshot_proposals=get_dummy_snapshot_proposals(),
                        delegations=get_dummy_delegations(),
                        tally_proposals_to_refresh=[],
                        safe_contract_address=NULL_ADDRESS,
                    ),
                    event=Event.DONE,
                ),
                {
                    "http_code": 200,
                    "response_body": {"errors": [], "data": {"vp": {"vp": 1}}},
                    "vote": "0",
                },
            ),
            (
                BehaviourTestCase(
                    "Error: vote not in response",
                    initial_data=dict(
                        proposals=get_dummy_proposals(),
                        snapshot_proposals=get_dummy_snapshot_proposals(),
                        delegations=get_dummy_delegations(),
                        tally_proposals_to_refresh=[],
                        safe_contract_address=NULL_ADDRESS,
                    ),
                    event=Event.DONE,
                ),
                {
                    "http_code": 200,
                    "response_body": {"data": {"vp": {"vp": 1}}},
                    "vote": "XXX",
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        time_in_future = datetime.datetime.now() + datetime.timedelta(hours=10)
        state = cast(SharedState, self._skill.skill_context.state)
        state.round_sequence._last_round_transition_timestamp = time_in_future
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()

        self.mock_llm_request(
            request_kwargs=dict(performative=LlmMessage.Performative.REQUEST),
            response_kwargs=dict(
                performative=LlmMessage.Performative.RESPONSE,
                value=kwargs.get("vote"),
            ),
        )
        self.complete(test_case.event)


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
                        target_proposals=get_dummy_proposals(),
                        expiring_proposals={
                            "tally": {"1": {"vote": "Yes"}},
                            "snapshot": {"1": {"vote": "Yes"}},
                        },
                        ceramic_db={"vote_data": {"tally": {}}},
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
                        proposals=get_dummy_proposals(1),
                        expiring_proposals={"1": {"vote": "Yes"}},
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
        self.behaviour.context.state.pending_vote = PendingVote("1", "FOR", False)
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        self.complete(test_case.event)


class TestPrepareVoteTransactionVoteTallyBehaviour(BaseProposalVoterTest):
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
                        target_proposals=get_dummy_proposals(),
                        expiring_proposals={
                            "tally": {"1": {"vote": "Yes"}},
                            "snapshot": {"1": {"vote": "Yes"}},
                        },
                        ceramic_db={"vote_data": {"tally": {}}},
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
        time_in_future = datetime.datetime.now() + datetime.timedelta(hours=10)
        state = cast(SharedState, self._skill.skill_context.state)
        state.round_sequence._last_round_transition_timestamp = time_in_future
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


class TestPrepareVoteTransactionVoteSnapshotBehaviour(BaseProposalVoterTest):
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
                    "Happy path: snapshot",
                    initial_data=dict(
                        votable_proposal_ids=[],
                        proposals=get_dummy_proposals(1),
                        safe_contract_address=NULL_ADDRESS,
                        votable_snapshot_proposals=get_dummy_snapshot_proposals(True),
                        expiring_proposals={
                            "tally": {},
                            "snapshot": {
                                "1": {
                                    "vote": 1,
                                    "id": "1",
                                    "space_id": "dummy_space_id",
                                }
                            },
                        },
                        ceramic_db={},
                    ),
                    event=Event.VOTE,
                ),
                {
                    "pending_vote": PendingVote("1", "FOR", True),
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        pending_vote = kwargs.get("pending_vote")
        self.behaviour.context.state.pending_vote = pending_vote
        time_in_future = datetime.datetime.now() + datetime.timedelta(hours=10)
        state = cast(SharedState, self._skill.skill_context.state)
        state.round_sequence._last_round_transition_timestamp = time_in_future
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()

        self.mock_contract_api_request(
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
            ),
            contract_id=str(SignMessageLibContract.contract_id),
            response_kwargs=dict(
                performative=ContractApiMessage.Performative.STATE,
                callable="get_safe_signature",
                state=State(
                    ledger_id="ethereum",
                    body={"signature": "0xb0e6add595e00477cf347d09797b"},
                ),
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


class TestPrepareVoteTransactionVoteSnapshotErrorBehaviour(BaseProposalVoterTest):
    """Tests PrepareVoteTransactionBehaviour"""

    behaviour_class = PrepareVoteTransactionBehaviour
    next_behaviour_class = PrepareVoteTransactionBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path: snapshot",
                    initial_data=dict(
                        votable_proposal_ids=[],
                        proposals=get_dummy_proposals(1),
                        safe_contract_address=NULL_ADDRESS,
                        votable_snapshot_proposals=get_dummy_snapshot_proposals(True),
                        final_verification_status=VerificationStatus.VERIFIED.value,
                    ),
                    event=Event.CONTRACT_ERROR,
                ),
                {
                    "pending_vote": PendingVote("1", "FOR", True),
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        pending_vote = kwargs.get("pending_vote")
        self.behaviour.context.state.pending_vote = pending_vote
        time_in_future = datetime.datetime.now() + datetime.timedelta(hours=10)
        state = cast(SharedState, self._skill.skill_context.state)
        state.round_sequence._last_round_transition_timestamp = time_in_future
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()

        self.mock_contract_api_request(
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
            ),
            contract_id=str(SignMessageLibContract.contract_id),
            response_kwargs=dict(
                performative=ContractApiMessage.Performative.ERROR,
                callable="get_safe_signature",
                state=State(
                    ledger_id="ethereum",
                    body={"signature": "0xb0e6add595e00477cf347d09797b"},
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


class TestRetrieveSignatureNoSnapshotVoteBehaviour(BaseProposalVoterTest):
    """Tests PostVoteDecisionMakingBehaviour"""

    behaviour_class = PostVoteDecisionMakingBehaviour
    next_behaviour_class = PrepareVoteTransactionBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path: no snapshot vote",
                    initial_data=dict(),
                    event=Event.DONE,
                ),
                {"pending_vote": PendingVote("1", "FOR", False)},
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        pending_vote = kwargs.get("pending_vote")
        self.behaviour.context.state.pending_vote = pending_vote
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        self.complete(test_case.event)


class TestRandomnessBehaviour(BaseRandomnessBehaviourTest):
    """Test randomness in operation."""

    path_to_skill = PACKAGE_DIR

    randomness_behaviour_class = SnapshotAPISendRandomnessBehaviour
    next_behaviour_class = SnapshotAPISendSelectKeeperBehaviour
    done_event = Event.DONE


class BaseSelectKeeperSnapshotBehaviourTest(BaseProposalVoterTest):
    """Test SelectKeeperBehaviour."""

    select_keeper_behaviour_class: Type[BaseBehaviour]
    next_behaviour_class: Type[BaseBehaviour]

    def test_select_keeper(
        self,
    ) -> None:
        """Test select keeper agent."""
        participants = [self.skill.skill_context.agent_address, "a_1", "a_2"]
        self.fast_forward_to_behaviour(
            behaviour=self.behaviour,
            behaviour_id=self.select_keeper_behaviour_class.auto_behaviour_id(),
            synchronized_data=SynchronizedData(
                AbciAppDB(
                    setup_data=dict(
                        participants=[participants],
                        most_voted_randomness=[
                            "56cbde9e9bbcbdcaf92f183c678eaa5288581f06b1c9c7f884ce911776727688"
                        ],
                        most_voted_keeper_address=["a_1"],
                    ),
                )
            ),
        )
        assert (
            cast(
                BaseBehaviour,
                cast(BaseBehaviour, self.behaviour.current_behaviour),
            ).behaviour_id
            == self.select_keeper_behaviour_class.auto_behaviour_id()
        )
        self.behaviour.act_wrapper()
        self.mock_a2a_transaction()
        self._test_done_flag_set()
        self.end_round(done_event=Event.DONE)
        behaviour = cast(BaseBehaviour, self.behaviour.current_behaviour)
        assert behaviour.behaviour_id == self.next_behaviour_class.auto_behaviour_id()


class TestSelectKeeperSnapshotBehaviour(BaseSelectKeeperSnapshotBehaviourTest):
    """Test SelectKeeperBehaviour."""

    select_keeper_behaviour_class = SnapshotAPISendSelectKeeperBehaviour
    next_behaviour_class = SnapshotAPISendBehaviour


class TestSnapshotAPISendBehaviourNonSender(BaseProposalVoterTest):
    """Tests StreamWriteBehaviour"""

    behaviour_class = SnapshotAPISendBehaviour
    next_behaviour_class = PrepareVoteTransactionBehaviour

    @pytest.mark.parametrize(
        "test_case",
        [
            BehaviourTestCase(
                "Happy path",
                initial_data=dict(most_voted_keeper_address="not_my_address"),
                event=Event.DONE,
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.complete(event=test_case.event, sends=False)


class TestSnapshotAPISendBehaviourSender(BaseProposalVoterTest):
    """Tests SnapshotAPISendBehaviour"""

    behaviour_class = SnapshotAPISendBehaviour
    next_behaviour_class = PrepareVoteTransactionBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(
                        most_voted_keeper_address="test_agent_address",
                        safe_contract_address="dummy_safe_contract_address",
                    ),
                    event=Event.DONE,
                ),
                {
                    "body": json.dumps(
                        {},
                    ),
                    "status": 200,
                    "headers": "Accept: application/json\r\nContent-Type: application/json\r\n",
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        self.mock_http_request(
            request_kwargs=dict(
                method="POST",
                headers=kwargs.get("headers"),
                version="",
                url=SNAPSHOT_VOTE_ENDPOINT,
            ),
            response_kwargs=dict(
                version="",
                status_code=kwargs.get("status"),
                status_text="",
                body=kwargs.get("body").encode(),
            ),
        )

        self.complete(test_case.event)


class TestSnapshotAPISendBehaviourSenderError(BaseProposalVoterTest):
    """Tests SnapshotAPISendBehaviour"""

    behaviour_class = SnapshotAPISendBehaviour
    next_behaviour_class = SnapshotAPISendRandomnessBehaviour

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    "Happy path",
                    initial_data=dict(
                        most_voted_keeper_address="test_agent_address",
                        safe_contract_address="dummy_safe_contract_address",
                    ),
                    event=Event.DONE,
                ),
                {
                    "body": json.dumps(
                        {},
                    ),
                    "status": 400,
                    "headers": "Accept: application/json\r\nContent-Type: application/json\r\n",
                },
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Run tests."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()
        self.mock_http_request(
            request_kwargs=dict(
                method="POST",
                headers=kwargs.get("headers"),
                version="",
                url=SNAPSHOT_VOTE_ENDPOINT,
            ),
            response_kwargs=dict(
                version="",
                status_code=kwargs.get("status"),
                status_text="",
                body=kwargs.get("body").encode(),
                headers="",
            ),
        )

        self.complete(test_case.event)
