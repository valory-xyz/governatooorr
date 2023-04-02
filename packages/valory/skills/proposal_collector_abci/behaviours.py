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

"""This package contains round behaviours of ProposalCollectorAbciApp."""

import json
from abc import ABC
from copy import deepcopy
from typing import Generator, List, Optional, Set, Type, cast

from packages.valory.contracts.compound.contract import CompoundContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.proposal_collector_abci.models import Params
from packages.valory.skills.proposal_collector_abci.payloads import (
    CollectActiveProposalsPayload,
    SelectProposalPayload,
    SynchronizeDelegationsPayload,
    VerifyDelegationsPayload,
)
from packages.valory.skills.proposal_collector_abci.rounds import (
    CollectActiveProposalsRound,
    ProposalCollectorAbciApp,
    SelectProposalRound,
    SynchronizeDelegationsRound,
    SynchronizedData,
    VerifyDelegationsRound,
)
from packages.valory.skills.proposal_collector_abci.tally import proposal_query


HTTP_OK = 200


class ProposalCollectorBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour for the proposal_collector_abci skill."""

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def params(self) -> Params:
        """Return the params."""
        return cast(Params, super().params)


class SynchronizeDelegationsBehaviour(ProposalCollectorBaseBehaviour):
    """
    SynchronizeDelegations

    Synchronizes delegations across all agents.

    When there are multiple agents in the service not all agents have necessarily the same data before synchronizing.
    """

    matching_round: Type[AbstractRound] = SynchronizeDelegationsRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            new_delegations = json.dumps(
                self.context.state.new_delegations
            )  # no sorting needed here as there is no consensus over this data
            sender = self.context.agent_address
            # TODO: we also need to reset the new_delegations -> we do this on the next round (VerifyDelegationsRound), once every agent has all the data
            payload = SynchronizeDelegationsPayload(
                sender=sender, new_delegations=new_delegations
            )
            self.context.logger.info(f"New delegations = {new_delegations}")

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class VerifyDelegationsBehaviour(ProposalCollectorBaseBehaviour):
    """
    VerifyDelegations

    We verify the delegations received from the frontend against the chain state.

    After verification we optimistically assume no change in delegations until we re-enter this
    behaviour.
    """

    matching_round: Type[AbstractRound] = VerifyDelegationsRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            sender = self.context.agent_address

            # FIX: Not sure this makes sense... the new_delegations can constantly change...
            # Remove delegations that have already been added to the synchronized data from the agent
            delegation_number = self.synchronized_data.agent_to_new_delegation_number[
                sender
            ]
            self.context.state.new_delegations = self.context.state.new_delegations[
                delegation_number:
            ]

            # Validate delegations on-chain
            validated_new_delegations = yield from self._get_validated_delegations()

            self.context.logger.info(
                f"validated_new_delegations = {validated_new_delegations}"
            )

            if validated_new_delegations is None:
                payload = VerifyDelegationsPayload(
                    sender=sender,
                    new_token_to_delegations=VerifyDelegationsRound.ERROR_PAYLOAD,
                )

            else:
                # Create the new_token_to_delegations mapping from the validated_new_delegations

                # new_token_to_delegations = {  # noqa: E800
                #     "token_address_a": {  # noqa: E800
                #         "user_address_a": {  # noqa: E800
                #             "delegation_amount": 1000,  # noqa: E800
                #             "voting_preference": "Good",  # noqa: E800
                #         },  # noqa: E800
                #         ...  # noqa: E800
                #     },  # noqa: E800
                #     ...  # noqa: E800
                # }  # noqa: E800
                new_token_to_delegations = {}
                for d in validated_new_delegations:

                    token_address = d["token_address"]
                    user_address = d["user_address"]

                    delegation_data = {
                        "delegation_amount": d["delegation_amount"],
                        "voting_preference": d["voting_preference"],
                        "user_address": d["user_address"],
                        "token_address": d["token_address"],
                    }

                    # Token does not exist
                    if token_address not in new_token_to_delegations:
                        new_token_to_delegations[token_address] = {
                            user_address: delegation_data,
                        }
                        continue

                    # Token exists, user does not exist
                    if user_address not in new_token_to_delegations[token_address]:
                        new_token_to_delegations[token_address][
                            user_address
                        ] = delegation_data
                        continue

                    # Token exists, user exists
                    # We should not reach here as that means that an user has
                    # multiple delegations for the same token
                    raise ValueError(
                        f"User {user_address} has multiple delegations for token {token_address}"
                    )

                payload = VerifyDelegationsPayload(
                    sender=sender,
                    new_token_to_delegations=json.dumps(
                        new_token_to_delegations, sort_keys=True
                    ),
                )

                self.context.logger.info(
                    f"new_token_to_delegations = {new_token_to_delegations}"
                )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_validated_delegations(
        self,
    ) -> Generator[None, None, Optional[List]]:
        """Get token id to member data."""

        # TODO: check for DelegateVotesChanged events to get the correct amount

        validated_delegations = []

        for d in self.synchronized_data.new_delegations:

            user_address = d["user_address"]
            token_address = d["token_address"]

            self.context.logger.info(
                f"Retrieving delegations for wallet {user_address}. Token: {token_address}"
            )
            contract_api_msg = yield from self.get_contract_api_response(
                performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
                contract_address=token_address,
                contract_id=str(
                    CompoundContract.contract_id
                ),  # Compound contract is an ERC20 contract
                contract_callable="get_current_votes",
                address=user_address,
            )
            if contract_api_msg.performative != ContractApiMessage.Performative.STATE:
                self.context.logger.info(
                    f"Error retrieving the delegations {contract_api_msg.performative}"
                )
                return None  # TODO: should we return if just one fails?

            votes = cast(int, contract_api_msg.state.body["votes"])

            # add the delegation amount for this user
            delegation = deepcopy(d)
            delegation["delegation_amount"] = int(votes)
            validated_delegations.append(delegation)

        return validated_delegations


class CollectActiveProposalsBehaviour(ProposalCollectorBaseBehaviour):
    """
    CollectActiveProposals

    Behaviour used to collect active proposals from Tally for the governors
    for which the Governatooorr has received delegations.
    """

    matching_round: Type[AbstractRound] = CollectActiveProposalsRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            active_proposals = yield from self._get_active_proposals()
            sender = self.context.agent_address
            payload = CollectActiveProposalsPayload(
                sender=sender, active_proposals=active_proposals
            )
            self.context.logger.info(f"active_proposals = {active_proposals}")

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_active_proposals(self) -> Generator[None, None, str]:
        """Get proposals mentions"""

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Api-key": "{api_key}".format(api_key=self.params.tally_api_key),
        }

        # Get all governors from the current delegations
        governor_addresses = set()
        for d in self.synchronized_data.current_delegations:
            governor_addresses.add(d["governor_address"])

        variables = {
            "chainId": "eip155:1",
            "proposers": [],
            "governors": list(governor_addresses),
            "pagination": {"limit": 200, "offset": 0},
        }

        self.context.logger.info(
            f"Retrieving proposals from Tally API [{self.params.tally_api_endpoint}] for governors: {governor_addresses}"
        )

        # Make the request
        response = yield from self.get_http_response(
            method="POST",
            url=self.params.tally_api_endpoint,
            headers=headers,
            content=json.dumps(
                {"query": proposal_query, "variables": variables}
            ).encode("utf-8"),
        )

        if response.status_code != HTTP_OK:
            self.context.logger.error(
                f"Could not retrieve data from Tally API. "
                f"Received status code {response.status_code}."
            )
            return CollectActiveProposalsRound.ERROR_PAYLOAD

        response_json = json.loads(response.body)

        # Filter out non-active proposals and those which use non-erc20 tokens
        # TOFIX: I think the second condition is not necessary, as we only allow valid governors
        active_proposals = list(
            filter(
                lambda p: p["statusChanges"][-1]["type"] == "ACTIVE"
                and len(p["governor"]["tokens"]) == 1
                and "erc20" in p["governor"]["tokens"][0]["id"],
                response_json["data"]["proposals"],
            )
        )

        return json.dumps(
            {
                "active_proposals": active_proposals,
            },
            sort_keys=True,
        )


class SelectProposalBehaviour(ProposalCollectorBaseBehaviour):
    """
    SelectProposal

    Select the proposal on which to vote.
    """

    matching_round: Type[AbstractRound] = SelectProposalRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            active_proposals = self.synchronized_data.active_proposals

            # TODO: we enter this round after a successful tx_submission
            # We need to check if that is the case and remove the first proposal
            # from the list.
            # TODO: we want to make sure we only vote towards the end of the voting period.
            # But it would be great if we could get the voting intention right away, so we can
            # display this on the frontend.

            # Some proposals have an ETA, some dont
            # We will prioritise those with it
            active_proposals_with_eta = list(
                filter(lambda p: p["eta"] != "", active_proposals)
            )
            active_proposals_no_eta = list(
                filter(lambda p: p["eta"] == "", active_proposals)
            )

            # Sort by ETA
            active_proposals_with_eta_sorted = sorted(
                active_proposals_with_eta, key=lambda p: int(p["eta"]), reverse=False
            )

            # Sort by ID
            active_proposals_no_eta_sorted = sorted(
                active_proposals_no_eta, key=lambda p: int(p["id"]), reverse=False
            )

            # Add all sorted proposals
            sorted_proposals = (
                active_proposals_with_eta_sorted + active_proposals_no_eta_sorted
            )

            # Select the first proposal
            proposal_id = sorted_proposals[0]["id"] if sorted_proposals else None

            # Check whether we have delegations
            if not proposal_id or not self.synchronized_data.current_delegations:
                proposal_id = SelectProposalRound.NO_PROPOSAL

            sender = self.context.agent_address
            payload = SelectProposalPayload(sender=sender, proposal_id=proposal_id)

            self.context.logger.info(f"proposal_id = {proposal_id}")

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class ProposalCollectorRoundBehaviour(AbstractRoundBehaviour):
    """ProposalCollectorRoundBehaviour"""

    initial_behaviour_cls = SynchronizeDelegationsBehaviour
    abci_app_cls = ProposalCollectorAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        CollectActiveProposalsBehaviour,
        SelectProposalBehaviour,
        SynchronizeDelegationsBehaviour,
    ]
